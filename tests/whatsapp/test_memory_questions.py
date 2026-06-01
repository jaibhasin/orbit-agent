# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppMemoryQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_question_uses_memory_answer(self):
        service = build_service()

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "what is the launch date?",
        )

        self.assertIn("Answer mode: memory-backed recall", xml)
        self.assertIn("The launch date discussed was Friday.", xml)
        self.assertIn("Sources:", xml)
        self.assertEqual(service.memory.questions, ["what is the launch date?"])
        self.assertEqual(service.openai_client.chat.completions.calls, [])

    async def test_normal_question_falls_back_to_general_answer_when_memory_is_empty(self):
        memory = FakeMemory(
            MemoryAnswer(
                "I do not have enough company memory yet to answer that.",
                mode="insufficient_memory",
            )
        )
        service = build_service(memory)

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "what is product market fit?",
        )

        self.assertIn("Answer mode: general fallback", xml)
        self.assertIn("This answer is not based on stored company memory.", xml)
        self.assertIn("General answer from Orbit.", xml)
        self.assertEqual(memory.questions, ["what is product market fit?"])
        self.assertEqual(len(service.openai_client.chat.completions.calls), 1)

    async def test_meet_link_still_starts_session_path(self):
        service = build_service()
        service.dialogue_history = [
            type("Turn", (), {"inbound": "old", "reply": "old reply"})()
        ]

        async def fake_start(meet_links, **kwargs):
            return f"started {len(meet_links)}"

        service.start_meeting_sessions = fake_start

        xml = await service.handle_incoming_message(
            "whatsapp:+15551234567",
            "join https://meet.google.com/abc-defg-hij",
        )

        self.assertIn("started 1", xml)
        self.assertEqual(service.memory.questions, [])
        self.assertEqual(len(service.dialogue_history), 1)
        self.assertEqual(service.dialogue_history[0].inbound, "join https://meet.google.com/abc-defg-hij")

    async def test_start_single_meeting_session_persists_people_source_and_meeting(self):
        store = FakeMeetingStore()
        service = build_service(memory=FakeMemory(), meeting_store=store)
        service._run_session = AsyncMock()
        with patch("orbit.whatsapp_service.run_meeting_session", new_callable=AsyncMock):
            result = await service.start_single_meeting_session(
                "https://meet.google.com/abc-defg-hij",
                from_number="whatsapp:+15551234567",
            )

        self.assertEqual(result["status"], "started")
        self.assertEqual(store.people, [("+15551234567", None)])
        self.assertEqual(store.sources[0]["url"], "https://meet.google.com/abc-defg-hij")
        self.assertEqual(store.meetings[0]["status"], "joining")
        self.assertEqual(store.meetings[0]["requested_by_person_id"], "person-1")
        self.assertEqual(store.meetings[0]["gmeet_url"], "https://meet.google.com/abc-defg-hij")

    async def test_session_status_updates_persistent_meeting_status(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
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
            meeting_id="meeting-1",
        )

        await service.handle_session_status(state, "starting_join", "opening")
        await service.handle_session_status(state, "joined", "joined")

        self.assertEqual(store.updates[0]["status"], "joining")
        self.assertEqual(store.updates[1]["status"], "live")

