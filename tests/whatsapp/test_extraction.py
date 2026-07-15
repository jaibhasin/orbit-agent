# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_finished_marks_meeting_processed(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                    "metadata": {},
                }
            ]
        }
        service = build_service(meeting_store=store)
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Orbit recap","summary_long":"Aman launch update and Ravi issue.","decisions":[],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-31T10:00:00",
            live_stt_requested=True,
            live_stt_started=True,
            finished_at="2026-05-31T11:00:00",
        )
        state.captured_messages = [
            ChatMessage(
                fingerprint="fp",
                raw_text="Orbit\\nhello",
                normalized_text="hello",
                author="Orbit",
                timestamp_text="10:00",
            )
        ]
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            meeting_id="meeting-1",
            source_id="source-1",
            capture_session_id="capture-1",
            capture_health_metadata={
                "audio": {"chunk_count": 1, "speech_chunk_count": 1},
                "deepgram": {"final_transcript_count": 1, "interim_transcript_count": 0},
            },
        )
        service.live_stt = FakeLiveSTT()

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message

        await service.handle_session_finished(state)

        self.assertEqual(store.updates[0]["status"], "processing")
        self.assertEqual(store.updates[-1]["status"], "processed")
        self.assertEqual(store.extraction_runs[-1]["status"], "success")
        self.assertEqual(store.capture_session_updates[-1]["status"], "processing")
        self.assertEqual(store.finished_capture_sessions, ["capture-1"])
        fields = store.updates[-1]["fields"]
        self.assertEqual(fields["ended_at"], "2026-05-31T11:00:00")
        self.assertEqual(fields["started_at"], "2026-05-31T10:00:00")
        self.assertEqual(fields["summary_short"], "Orbit recap")

    async def test_run_meeting_extraction_persists_decisions(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
                {
                    "chunk_index": 1,
                    "speaker_label": "Ravi",
                    "text": "Payments are still failing.",
                },
            ]
        }
        service = build_service(
            memory=FakeMemory(),
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Launch update","summary_long":"Aman said launch and Ravi reported payments issue.","decisions":[{"title":"Delay launch","decision_text":"The team decided to delay launch by one week.","rationale":"Payments are still failing.","owner_text":"Engineering","confidence":0.86},{"title":"Invalid","owner_text":"PM"}],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result.get("decisions_inserted"), 1)
        self.assertEqual(len(store.decisions), 1)
        self.assertEqual(store.decisions[0]["title"], "Delay launch")
        self.assertEqual(store.decisions[0]["decision_text"], "The team decided to delay launch by one week.")
        self.assertEqual(store.decisions[0]["owner_text"], "Engineering")
        self.assertEqual(store.decisions[0]["confidence"], 0.86)

    async def test_run_meeting_extraction_persists_decisions_with_legacy_keys(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
                {
                    "chunk_index": 1,
                    "speaker_label": "Ravi",
                    "text": "Payments are still failing.",
                },
            ]
        }
        service = build_service(
            memory=FakeMemory(),
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Launch update","summary_long":"Aman said launch and Ravi reported payments issue.","decisions":[{"decision":"The team decided to delay launch by one week.","confidence":0.91},{"owner":"PM","decision":"Close pending tasks before launch."}],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result.get("decisions_inserted"), 2)
        self.assertEqual(len(store.decisions), 2)
        self.assertEqual(store.decisions[0]["decision_text"], "The team decided to delay launch by one week.")
        self.assertEqual(store.decisions[1]["decision_text"], "Close pending tasks before launch.")
        self.assertEqual(store.decisions[1]["title"], "")

    async def test_run_meeting_extraction_persists_action_items(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
                {
                    "chunk_index": 1,
                    "speaker_label": "Ravi",
                    "text": "Payments are still failing.",
                },
            ]
        }
        service = build_service(
            memory=FakeMemory(),
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Launch update","summary_long":"Aman said launch and Ravi reported payments issue.","decisions":[],"action_items":[{"task":"Prepare launch checklist","ownerText":"PM","dueDate":"2026-06-03","confidence":0.71},{"due_date":"2026-06-04","owner":"Ops","task":"Schedule launch rehearsal","dueDate":"2026-06-05"},{"task":" ","ownerText":"PM"}],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result.get("action_items_inserted"), 2)
        self.assertEqual(len(store.action_items), 2)
        self.assertEqual(store.action_items[0]["task"], "Prepare launch checklist")
        self.assertEqual(store.action_items[0]["owner_text"], "PM")
        self.assertEqual(store.action_items[0]["due_date"], "2026-06-03")
        self.assertEqual(store.action_items[0]["status"], "open")
        self.assertEqual(store.action_items[0]["confidence"], 0.71)
        self.assertEqual(store.action_items[1]["task"], "Schedule launch rehearsal")
        self.assertEqual(store.action_items[1]["owner_text"], "Ops")

    async def test_run_meeting_extraction_persists_memories(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
                {
                    "chunk_index": 1,
                    "speaker_label": "Ravi",
                    "text": "Payments are still failing.",
                },
            ]
        }
        service = build_service(
            memory=FakeMemory(),
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Launch update","summary_long":"Aman said launch and Ravi reported payments issue.","decisions":[{"title":"Delay launch","decision_text":"The team decided to delay launch by one week."}],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[{"memory_type":"risk","content":"Payment reliability is currently a launch risk.","importance":"high","confidence":0.84},{"content":"The team is prioritizing enterprise customers.","importance":"medium","confidence":0.75}]}'
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result.get("memories_inserted"), 2)
        self.assertEqual(len(store.memories), 2)
        self.assertEqual(store.memories[0]["memory_type"], "risk")
        self.assertEqual(store.memories[0]["content"], "Payment reliability is currently a launch risk.")
        self.assertEqual(store.memories[0]["importance"], "high")
        self.assertEqual(store.memories[0]["confidence"], 0.84)
        self.assertEqual(store.memories[1]["memory_type"], "important_fact")
        self.assertEqual(store.memories[1]["content"], "The team is prioritizing enterprise customers.")
        self.assertEqual(store.memories[1]["importance"], "medium")

    async def test_run_meeting_extraction_success(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
                {
                    "chunk_index": 1,
                    "speaker_label": "Ravi",
                    "text": "Payments are still failing.",
                },
            ]
        }
        service = build_service(
            memory=FakeMemory(),
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Launch update","summary_long":"Aman said launch and Ravi reported payments issue.","decisions":[],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(store.extraction_runs), 1)
        self.assertEqual(store.extraction_runs[0]["status"], "success")
        self.assertEqual(store.updates[0]["status"], "processing")
        self.assertEqual(store.updates[-1]["status"], "processed")
        self.assertEqual(store.extraction_runs[0]["output_json"]["summary_short"], "Launch update")

    async def test_run_meeting_extraction_includes_timestamped_visual_evidence(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "start_ms": 60000,
                    "text": "This is the launch plan.",
                }
            ]
        }
        store.visual_frames_for_meeting = {
            "meeting-1": [
                {
                    "captured_at_ms": 65000,
                    "summary": "Roadmap slide shows beta in August and launch in October.",
                }
            ]
        }
        service = build_service(memory=FakeMemory(), meeting_store=store)
        service.openai_client = FakeOpenAIClient(
            responses=[
                '{"summary_short":"Roadmap","summary_long":"Launch roadmap.","decisions":[],"action_items":[],"risks":[],"open_questions":[],"durable_memories":[]}'
            ]
        )

        result = await service.runMeetingExtraction(
            {"meetingId": "meeting-1", "sourceId": "source-1"}
        )

        self.assertEqual(result["status"], "success")
        prompt = service.openai_client.chat.completions.calls[0]["messages"][1]["content"]
        self.assertIn("[Transcript 00:01:00] Aman: This is the launch plan.", prompt)
        self.assertIn("[Visual 00:01:05] Roadmap slide shows beta in August", prompt)

    async def test_run_meeting_extraction_failed_on_non_json_output(self):
        store = FakeMeetingStore()
        store.source_chunks_for_id = {
            "source-1": [
                {
                    "chunk_index": 0,
                    "speaker_label": "Aman",
                    "text": "We should launch next week.",
                },
            ]
        }
        service = build_service(
            meeting_store=store,
        )
        service.openai_client = FakeOpenAIClient(
            responses=[
                "Sorry I cannot give JSON."
            ]
        )
        result = await service.runMeetingExtraction(
            {
                "meetingId": "meeting-1",
                "sourceId": "source-1",
            }
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(store.extraction_runs), 1)
        self.assertEqual(store.extraction_runs[0]["status"], "failed")
        self.assertEqual(store.updates[-1]["status"], "failed")
        self.assertIn("output_json", store.extraction_runs[0])

    async def test_session_finished_marks_meeting_failed_when_chunk_save_fails(self):
        store = FakeMeetingStore()
        store.fail_save_chunks = True
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-31T10:00:00",
            live_transcript_segments=[
                TranscriptSegment(
                    source_id="s1",
                    raw_text="hello",
                    clean_text="Hello.",
                    memory_text="Hello.",
                )
            ],
            finished_at="2026-05-31T11:00:00",
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            meeting_id="meeting-1",
            source_id="source-1",
        )
        service.live_stt = FakeLiveSTT()

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message

        await service.handle_session_finished(state)

        self.assertEqual(store.updates[0]["status"], "processing")
        self.assertEqual(store.updates[-1]["status"], "failed")
        self.assertEqual(len(store.transcript_save_calls), 1)
        self.assertEqual(store.transcript_save_calls[0][0], "source-1")

    async def test_build_transcript_source_chunks_prefers_clean_text(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            live_transcript_segments=[
                TranscriptSegment(
                    source_id="s1",
                    raw_text="Meet abc-defg-hij transcript - 00:00:01-00:00:02: Hello.",
                    clean_text="Hello.",
                    memory_text="Meet abc-defg-hij transcript - 00:00:01-00:00:02: Hello.",
                )
            ],
        )

        chunks = service._build_transcript_source_chunks(state)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "Hello.")
        self.assertEqual(chunks[0]["metadata"]["memory_text"], "Meet abc-defg-hij transcript - 00:00:01-00:00:02: Hello.")

