# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppDialogueLiveRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_resets_dialogue_without_stopping_meetings(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )
        service.dialogue_history = [
            type("Turn", (), {"inbound": "old", "reply": "old reply"})()
        ]

        xml = await service.handle_incoming_message("whatsapp:+15551234567", "/new")

        self.assertIn("context reset", xml)
        self.assertEqual(service.dialogue_history, [])
        self.assertIn(state.session_id, service.active_sessions)

    async def test_dialogue_history_is_bounded_and_truncated(self):
        service = build_service()

        for index in range(14):
            service.record_dialogue_turn(f"user-{index}", "x" * 2500)

        self.assertEqual(len(service.dialogue_history), 12)
        self.assertEqual(service.dialogue_history[0].inbound, "user-2")
        self.assertEqual(len(service.dialogue_history[-1].reply), 2000)

    async def test_status_lists_active_meeting(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            status="joined",
            joined_at="2026-05-30T09:34:16Z",
            live_stt_requested=True,
            live_stt_available=True,
            live_stt_started=True,
        )
        state.live_transcript_segments = [
            TranscriptSegment(
                source_id="s1",
                raw_text="hello",
                clean_text="Hello.",
                memory_text="Hello.",
            )
        ]
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )

        xml = await service.handle_incoming_message("whatsapp:+15551234567", "status")

        self.assertIn("abc-defg-hij", xml)
        self.assertIn("transcript segments: 1", xml)

    async def test_multiple_meetings_ask_for_code_for_live_recall(self):
        service = build_service()
        for code in ["abc-defg-hij", "xyz-abcd-uvw"]:
            state = MeetingState(
                session_id=f"{code}-session",
                meet_url=f"https://meet.google.com/{code}",
                meeting_code=code,
                display_name="Orbit",
            )
            service.active_sessions[state.session_id] = ActiveMeeting(
                session_id=state.session_id,
                meet_url=state.meet_url,
                state=state,
            )

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "what are people discussing?",
        )

        self.assertIn("Multiple meetings are active", xml)
        self.assertIn("abc-defg-hij", xml)
        self.assertIn("xyz-abcd-uvw", xml)

    async def test_live_recall_uses_selected_live_transcript(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            live_stt_requested=True,
            live_stt_available=True,
            live_stt_started=True,
        )
        state.live_transcript_segments = [
            TranscriptSegment(
                source_id="s1",
                raw_text="pricing",
                clean_text="We are discussing pricing.",
                memory_text="We are discussing pricing.",
                speaker_name="Priya",
                start_ms=1000,
                end_ms=3000,
            ),
            TranscriptSegment(
                source_id="s2",
                raw_text="launch",
                clean_text="The launch date is Friday.",
                memory_text="The launch date is Friday.",
                speaker_name="Jai",
                start_ms=4000,
                end_ms=6000,
            ),
        ]
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "summarize the meeting",
        )

        self.assertIn("Answer mode: live transcript", xml)
        self.assertIn("Sources:", xml)
        call = service.openai_client.chat.completions.calls[0]
        self.assertIn("We are discussing pricing.", call["messages"][1]["content"])
        self.assertIn("The launch date is Friday.", call["messages"][1]["content"])
        self.assertEqual(service.memory.questions, [])

    async def test_live_recall_does_not_fall_back_to_memory_when_stt_is_sparse(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            live_stt_requested=True,
            live_stt_available=True,
            live_stt_started=True,
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "what are people discussing?",
        )

        self.assertIn("too little live transcript context", xml)
        self.assertEqual(service.memory.questions, [])

    async def test_stop_sets_state_and_waits_for_cleanup(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )

        async def done():
            return None

        task = asyncio.create_task(done())
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            task=task,
        )

        xml = await service.handle_incoming_message("whatsapp:+15551234567", "stop monitoring")

        self.assertTrue(state.stop_requested)
        self.assertIn("completed cleanup", xml)

    async def test_leave_in_normal_question_does_not_stop_meeting(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "what is our parental leave policy?",
        )

        self.assertFalse(state.stop_requested)
        self.assertIn("Answer mode: memory-backed recall", xml)
        self.assertEqual(service.memory.questions, ["what is our parental leave policy?"])

    async def test_chat_messages_are_forwarded_to_memory(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        message = ChatMessage(
            fingerprint="fp-1",
            raw_text="Priya\\nlaunch is Friday",
            normalized_text="launch is Friday",
            author="Priya",
            timestamp_text="10:05",
        )

        await service.handle_chat_message(state, message, "poll")
        await service.handle_session_finished(state)

        self.assertEqual(service.memory.recorded, [(state, message)])
        self.assertEqual(service.memory.finalized, [state])

