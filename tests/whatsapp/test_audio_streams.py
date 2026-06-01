# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppAudioStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_extension_audio_stream_forwards_chunks_to_live_stt(self):
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
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )
        websocket = FakeWebSocket(
            [
                {"text": '{"type":"start","encoding":"linear16","sample_rate":16000,"channels":1}'},
                {"bytes": b"pcm"},
                {"bytes": b"more"},
                {"text": '{"type":"stop"}'},
            ]
        )

        await service.handle_audio_stream(websocket, state.session_id)

        self.assertTrue(websocket.accepted)
        self.assertEqual(websocket.sent_json, [{"type": "ready"}])
        fake_session = service.live_stt.sessions[0][2]
        self.assertEqual(fake_session.audio_chunks, [b"pcm", b"more"])
        self.assertEqual(service.live_stt.stopped, [state.session_id])
        self.assertTrue(state.live_stt_started)
        self.assertIsNotNone(state.live_stt_audio_confirmed_at)
        self.assertEqual(
            state.live_stt_status_detail,
            "Deepgram stream connected and first audio chunk forwarded.",
        )
        self.assertEqual(
            whatsapp_updates,
            ["Orbit confirmed live audio transcription for Meet abc-defg-hij."],
        )
        self.assertEqual(
            service.meeting_store.capture_session_updates[-1]["status"],
            "streaming_audio",
        )
        audio = service.active_sessions[state.session_id].capture_health_metadata["audio"]
        self.assertTrue(audio["streaming_started"])
        self.assertIsNotNone(audio["first_chunk_at"])
        self.assertEqual(audio["chunk_count"], 2)
        self.assertEqual(audio["bytes_received"], 7)
        self.assertEqual(audio["bytes_forwarded_to_stt"], 7)
        self.assertTrue(service.meeting_store.capture_session_metadata_updates)

    async def test_deepgram_health_tracks_connection_and_transcripts_without_text(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )
        service.active_sessions[state.session_id] = active

        await service._handle_live_stt_health_event(state, "connect_started", {})
        await service._handle_live_stt_health_event(state, "connected", {})
        await service._handle_live_stt_health_event(
            state,
            "transcript",
            {"is_final": False, "transcript": "must not be stored"},
        )
        await service._handle_live_stt_health_event(
            state,
            "transcript",
            {"is_final": True, "transcript": "must not be stored"},
        )
        await service._handle_live_stt_health_event(state, "keepalive", {})

        deepgram = active.capture_health_metadata["deepgram"]
        self.assertIsNotNone(deepgram["connect_started_at"])
        self.assertIsNotNone(deepgram["connected_at"])
        self.assertIsNotNone(deepgram["first_transcript_at"])
        self.assertEqual(deepgram["final_transcript_count"], 1)
        self.assertEqual(deepgram["interim_transcript_count"], 1)
        self.assertEqual(deepgram["keepalive_count"], 1)
        self.assertIsNotNone(deepgram["last_keepalive_at"])
        self.assertNotIn("must not be stored", str(service.meeting_store.capture_session_metadata))

    async def test_extension_audio_stream_drops_sustained_pcm_silence_and_sends_keepalive(self):
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
            capture_session_id="capture-1",
        )
        speech = pcm16_chunk(2000)
        silence = pcm16_chunk(0)
        websocket = FakeWebSocket(
            [
                {"text": '{"type":"start","encoding":"linear16","sample_rate":16000,"channels":1}'},
                {"bytes": speech},
                *[{"bytes": silence} for _ in range(15)],
                {"text": '{"type":"stop"}'},
            ]
        )

        await service.handle_audio_stream(websocket, state.session_id)

        fake_session = service.live_stt.sessions[0][2]
        self.assertEqual(fake_session.audio_chunks, [speech, *([silence] * 9)])
        self.assertGreaterEqual(fake_session.keepalives, 1)
        audio = service.active_sessions[state.session_id].capture_health_metadata["audio"]
        self.assertEqual(audio["speech_chunk_count"], 1)
        self.assertEqual(audio["silent_chunk_count"], 15)
        self.assertEqual(audio["bytes_received"], len(speech) + len(silence) * 15)
        self.assertEqual(audio["bytes_forwarded_to_stt"], len(speech) + len(silence) * 9)
        self.assertEqual(audio["bytes_dropped_silence"], len(silence) * 6)
        self.assertTrue(audio["silence_gated"])

    async def test_finished_meeting_classifies_audio_only_silence(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-30T09:34:16Z",
            live_stt_requested=True,
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )
        active.capture_health_metadata["audio"]["chunk_count"] = 5
        active.capture_health_metadata["audio"]["silent_chunk_count"] = 5
        service.active_sessions[state.session_id] = active

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message
        await service.handle_session_finished(state)

        self.assertEqual(
            service.meeting_store.failed_capture_sessions[-1]["error_code"],
            "AUDIO_ONLY_SILENCE",
        )

    async def test_finished_meeting_classifies_missing_transcript(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-30T09:34:16Z",
            live_stt_requested=True,
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
        )
        active.capture_health_metadata["audio"]["chunk_count"] = 5
        active.capture_health_metadata["audio"]["speech_chunk_count"] = 2
        service.active_sessions[state.session_id] = active

        async def fake_send_whatsapp_message(body):
            return None

        service.send_whatsapp_message = fake_send_whatsapp_message
        await service.handle_session_finished(state)

        self.assertEqual(
            service.meeting_store.failed_capture_sessions[-1]["error_code"],
            "NO_TRANSCRIPT_RECEIVED",
        )

    async def test_deepgram_keepalive_failure_is_classified(self):
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
            capture_session_id="capture-1",
        )

        await service._handle_live_stt_health_event(
            state,
            "keepalive_failed",
            {"error": "connection closed"},
        )

        failure = service.meeting_store.failed_capture_sessions[-1]
        self.assertEqual(failure["error_code"], "DEEPGRAM_KEEPALIVE_FAILED")
        self.assertEqual(failure["metadata"]["deepgram"]["error"], "connection closed")

    async def test_audio_metadata_writes_are_throttled(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-1",
            last_capture_metadata_flush_at=asyncio.get_running_loop().time(),
        )

        for _ in range(CAPTURE_AUDIO_METADATA_FLUSH_CHUNKS - 1):
            service._record_audio_chunk_received(active, 3)
            service._record_audio_chunk_forwarded(active, 3)
            await service._flush_capture_audio_health(active)

        self.assertEqual(service.meeting_store.capture_session_metadata_updates, [])

        service._record_audio_chunk_received(active, 3)
        service._record_audio_chunk_forwarded(active, 3)
        await service._flush_capture_audio_health(active)

        self.assertEqual(len(service.meeting_store.capture_session_metadata_updates), 1)
        self.assertEqual(
            service.meeting_store.capture_session_metadata["audio"]["chunk_count"],
            CAPTURE_AUDIO_METADATA_FLUSH_CHUNKS,
        )

    async def test_deepgram_connect_failure_is_classified(self):
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
            capture_session_id="capture-1",
        )

        await service._handle_live_stt_health_event(
            state,
            "connect_failed",
            {"error": "provider unavailable"},
        )

        failure = service.meeting_store.failed_capture_sessions[-1]
        self.assertEqual(failure["error_code"], "DEEPGRAM_CONNECT_FAILED")
        self.assertEqual(failure["metadata"]["deepgram"]["error"], "provider unavailable")

    async def test_extension_audio_stream_is_not_confirmed_before_first_chunk(self):
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
        websocket = FakeWebSocket(
            [
                {"text": '{"type":"start","encoding":"linear16","sample_rate":16000,"channels":1}'},
                {"text": '{"type":"stop"}'},
            ]
        )

        await service.handle_audio_stream(websocket, state.session_id)

        self.assertFalse(state.live_stt_started)
        self.assertIsNone(state.live_stt_audio_confirmed_at)
        self.assertEqual(
            state.live_stt_status_detail,
            "Extension audio WebSocket connected. Waiting for the first audio chunk.",
        )

    async def test_extension_audio_stream_failure_marks_capture_session_failed(self):
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
            capture_session_id="capture-1",
        )
        websocket = FakeWebSocket(
            [
                {"text": '{"type":"start","encoding":"linear16","sample_rate":16000,"channels":1}'},
            ]
        )

        await service.handle_audio_stream(websocket, state.session_id)

        self.assertEqual(
            service.meeting_store.failed_capture_sessions[-1]["error_code"],
            "AUDIO_WEBSOCKET_CLOSED",
        )

    async def test_extension_empty_audio_chunk_does_not_confirm_live_stt(self):
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
            capture_session_id="capture-1",
        )
        websocket = FakeWebSocket(
            [
                {"text": '{"type":"start","encoding":"linear16","sample_rate":16000,"channels":1}'},
                {"bytes": b""},
                {"text": '{"type":"stop"}'},
            ]
        )

        await service.handle_audio_stream(websocket, state.session_id)

        self.assertFalse(state.live_stt_started)
        fake_session = service.live_stt.sessions[0][2]
        self.assertEqual(fake_session.audio_chunks, [])
        self.assertEqual(
            service.active_sessions[state.session_id]
            .capture_health_metadata["audio"]["silent_or_empty_chunk_count"],
            1,
        )

    async def test_extension_missing_unknown_session_closes_websocket(self):
        service = build_service()
        websocket = FakeWebSocket([])

        await service.handle_audio_stream(websocket, "missing")

        self.assertEqual(websocket.closed[0], 4404)

    async def test_extension_audio_stream_rejects_bad_session_token(self):
        service = build_service()
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            live_stt_audio_token="expected-token",
        )
        service.active_sessions[state.session_id] = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
        )
        websocket = FakeWebSocket([], query_params={"token": "wrong-token"})

        await service.handle_audio_stream(websocket, state.session_id)

        self.assertEqual(websocket.closed[0], 4403)
        self.assertFalse(websocket.accepted)

