# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppFinishAndMentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_meeting_reports_missing_live_audio(self):
        service = build_service()
        whatsapp_updates = []

        async def fake_send_whatsapp_message(body):
            whatsapp_updates.append(body)

        service.send_whatsapp_message = fake_send_whatsapp_message
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-30T09:34:16Z",
            live_stt_requested=True,
        )

        await service.handle_session_finished(state)

        self.assertEqual(
            whatsapp_updates,
            [
                "Orbit finished Meet abc-defg-hij. Captured 0 chat message(s). "
                "Live audio transcription did not start because no audio chunk was received."
            ],
        )

    async def test_finished_meeting_marks_missing_live_audio_failed(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-30T09:34:16Z",
            live_stt_requested=True,
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message
        await service.handle_session_finished(state)

        self.assertEqual(
            service.meeting_store.failed_capture_sessions[-1]["error_code"],
            "NO_AUDIO_CHUNKS_RECEIVED",
        )

    async def test_finished_unadmitted_meeting_marks_capture_session_failed(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            status="waiting_for_host",
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message

        await service.handle_session_finished(state)

        self.assertEqual(
            service.meeting_store.failed_capture_sessions[-1]["error_code"],
            "CAPTURE_NOT_ADMITTED",
        )

    async def test_finished_meeting_reports_leave_reason(self):
        service = build_service()
        whatsapp_updates = []

        async def fake_send_whatsapp_message(body):
            whatsapp_updates.append(body)

        service.send_whatsapp_message = fake_send_whatsapp_message
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-30T09:34:16Z",
            leave_reason="Orbit is the only participant left in the meeting.",
        )

        await service.handle_session_finished(state)

        self.assertEqual(
            whatsapp_updates,
            [
                "Orbit finished Meet abc-defg-hij. Captured 0 chat message(s). "
                "Orbit is the only participant left in the meeting."
            ],
        )

    async def test_meet_chat_mention_gets_model_reply(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        previous = ChatMessage(
            fingerprint="fp-1",
            raw_text="Jai\\nwe are discussing pricing",
            normalized_text="we are discussing pricing",
            author="Jai",
            timestamp_text="10:04",
        )
        mention = ChatMessage(
            fingerprint="fp-2",
            raw_text="Jai\\n@orbit are you there?",
            normalized_text="@orbit are you there?",
            author="Jai",
            timestamp_text="10:05",
        )
        state.captured_messages = [previous, mention]

        reply = await service.handle_orbit_mention(state, mention)

        self.assertEqual(reply, "General answer from Orbit.")
        call = service.openai_client.chat.completions.calls[0]
        self.assertIn("are you there?", call["messages"][1]["content"])
        self.assertIn("we are discussing pricing", call["messages"][1]["content"])

