# ruff: noqa: F401,F403,F405
from __future__ import annotations

from tests.support.whatsapp_fakes import *  # noqa: F401,F403,F405


class WhatsAppCaptureSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_session_tracks_start_join_live_and_failure(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
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
            meeting_id="meeting-1",
            capture_session_id="capture-1",
        )
        service.active_sessions[state.session_id] = active

        with patch("orbit.whatsapp_service.run_meeting_session", new_callable=AsyncMock):
            await service._run_session(
                active,
                types.SimpleNamespace(live_stt_enabled=False),
            )

        self.assertEqual(store.capture_session_updates[0]["status"], "starting")

        service.active_sessions[state.session_id] = active
        await service.handle_session_status(state, "starting_join", "opening")
        await service.handle_session_status(state, "joined", "joined")
        await service.handle_session_status(state, "join_denied", "denied")

        self.assertEqual(
            [update["status"] for update in store.capture_session_updates],
            ["starting", "joining", "live"],
        )
        self.assertEqual(store.failed_capture_sessions[-1]["error_code"], "JOIN_DENIED")

    async def test_run_session_starts_server_audio_sink_when_configured(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-a",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-a",
        )
        service.active_sessions[state.session_id] = active

        fake_handle = FakeServerAudioSinkHandle(
            session_id="session-a",
            capture_session_id="capture-a",
            sink_name="orbit_meet_session-a",
            pid=4001,
        )

        with patch(
            "orbit.whatsapp_service.get_audio_capture_strategy",
            return_value="server_audio_sink",
        ), patch(
            "orbit.whatsapp_service.start_server_audio_sink_capture",
            new_callable=AsyncMock,
            return_value=fake_handle,
        ) as start_capture, patch("orbit.whatsapp_service.run_meeting_session", new_callable=AsyncMock):
            await service._run_session(
                active,
                types.SimpleNamespace(live_stt_enabled=True),
            )

        start_capture.assert_awaited_once()
        self.assertEqual(start_capture.await_args.args, ("session-a", "capture-a"))
        self.assertIsNone(active.server_audio_sink_handle)
        self.assertEqual(fake_handle.stop_calls, 1)
        self.assertEqual(
            store.capture_session_metadata["audio_capture"]["strategy"],
            "server_audio_sink",
        )
        self.assertEqual(
            store.capture_session_metadata["audio_capture"]["sink_name"],
            "orbit_meet_session-a",
        )
        self.assertEqual(
            store.capture_session_metadata["audio_capture"]["ffmpeg_pid"],
            4001,
        )
        self.assertEqual(
            store.capture_session_metadata["audio_capture"]["routing_mode"],
            "not_implemented",
        )
        self.assertFalse(store.capture_session_metadata["audio_capture"]["browser_audio_routed"])
        self.assertIn("stopped_at", store.capture_session_metadata["audio_capture"])

    async def test_run_session_passes_server_sink_name_to_meeting_launch(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-aa",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-aa",
        )
        service.active_sessions[state.session_id] = active

        captured = {}
        fake_handle = FakeServerAudioSinkHandle(
            session_id="session-aa",
            capture_session_id="capture-aa",
            sink_name="orbit_meet_session_aa",
            pid=4021,
        )

        async def fake_run_meeting_session(config, callbacks=None, state=None):
            captured["config"] = config

        with patch(
            "orbit.whatsapp_service.get_audio_capture_strategy",
            return_value="server_audio_sink",
        ), patch(
            "orbit.whatsapp_service.start_server_audio_sink_capture",
            new_callable=AsyncMock,
            return_value=fake_handle,
        ) as start_capture, patch(
            "orbit.whatsapp_service.run_meeting_session",
            new=fake_run_meeting_session,
        ):
            await service._run_session(
                active,
                types.SimpleNamespace(live_stt_enabled=True),
            )

        start_capture.assert_awaited_once()
        self.assertEqual(start_capture.await_args.args, ("session-aa", "capture-aa"))
        self.assertIsNotNone(captured.get("config"))
        self.assertEqual(
            captured["config"].audio_sink_name,
            "orbit_meet_session_aa",
        )
        self.assertEqual(captured["config"].audio_capture_strategy, "server_audio_sink")
        self.assertEqual(
            store.capture_session_metadata["audio_capture"]["routing_mode"],
            "not_implemented",
        )

    async def test_run_session_keeps_chrome_extension_behavior_by_default(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-b",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-b",
        )
        service.active_sessions[state.session_id] = active

        with patch(
            "orbit.whatsapp_service.get_audio_capture_strategy",
            return_value="chrome_extension",
        ), patch(
            "orbit.whatsapp_service.start_server_audio_sink_capture",
            new_callable=AsyncMock,
        ) as start_capture, patch(
            "orbit.whatsapp_service.run_meeting_session",
            new_callable=AsyncMock,
        ):
            await service._run_session(
                active,
                types.SimpleNamespace(live_stt_enabled=True),
            )

        start_capture.assert_not_awaited()

    async def test_run_session_marks_capture_failed_when_server_audio_sink_fails_to_start(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-c",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-c",
        )
        service.active_sessions[state.session_id] = active

        with patch(
            "orbit.whatsapp_service.get_audio_capture_strategy",
            return_value="server_audio_sink",
        ), patch(
            "orbit.whatsapp_service.start_server_audio_sink_capture",
            new_callable=AsyncMock,
            side_effect=RuntimeError("pactl failed to create sink"),
        ), patch("orbit.whatsapp_service.run_meeting_session", new_callable=AsyncMock):
            await service._run_session(
                active,
                types.SimpleNamespace(live_stt_enabled=True),
            )

        failure = store.failed_capture_sessions[-1]
        self.assertEqual(failure["error_code"], "AUDIO_SINK_CREATE_FAILED")
        self.assertIn("Could not start server-side audio sink capture.", failure["error_message"])

    async def test_server_audio_sink_reader_forwards_ffmpeg_audio_to_shared_stt_handler(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-d",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-d",
        )
        process = FakeServerAudioSinkProcess(pid=51234, returncode=0)
        process.stdout = FakeStdout([pcm16_chunk(1200), b""])
        active.server_audio_sink_handle = FakeServerAudioSinkHandle(
            session_id=state.session_id,
            capture_session_id=active.capture_session_id,
            sink_name="orbit_meet_session_d",
            pid=process.pid,
        )
        active.server_audio_sink_handle.ffmpeg_process = process
        service.active_sessions[state.session_id] = active

        await service._run_server_audio_sink_reader(active)

        self.assertTrue(state.live_stt_started)
        self.assertIsNotNone(service.live_stt.sessions[-1][1])
        fake_session = service.live_stt.sessions[-1][2]
        self.assertEqual(fake_session.audio_chunks, [pcm16_chunk(1200)])
        self.assertEqual(store.capture_session_updates[-1]["status"], "streaming_audio")

    async def test_server_audio_sink_reader_marks_failed_when_only_empty_chunks_seen(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-e",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-e",
        )
        process = FakeServerAudioSinkProcess(pid=51235, returncode=0)
        process.stdout = FakeStdout([b"", b""])
        handle = FakeServerAudioSinkHandle(
            session_id=state.session_id,
            capture_session_id=active.capture_session_id,
            sink_name="orbit_meet_session_e",
            pid=process.pid,
        )
        handle.ffmpeg_process = process
        active.server_audio_sink_handle = handle

        await service._run_server_audio_sink_reader(active)

        self.assertFalse(state.live_stt_started)
        self.assertEqual(store.failed_capture_sessions[-1]["error_code"], "NO_AUDIO_FROM_SINK")

    async def test_server_audio_sink_cleanup_is_idempotent(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state = MeetingState(
            session_id="session-f",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        handle = FakeServerAudioSinkHandle(
            session_id="session-f",
            capture_session_id="capture-f",
            sink_name="orbit_meet_session_f",
            pid=51236,
        )
        active = ActiveMeeting(
            session_id=state.session_id,
            meet_url=state.meet_url,
            state=state,
            capture_session_id="capture-f",
            server_audio_sink_handle=handle,
        )

        await service._stop_server_audio_sink_capture(active)
        await service._stop_server_audio_sink_capture(active)
        self.assertEqual(handle.stop_calls, 1)
        self.assertIsNone(active.server_audio_sink_handle)
        self.assertIn("stopped_at", store.capture_session_metadata["audio_capture"])

    async def test_two_server_audio_sink_handles_do_not_share_state(self):
        store = FakeMeetingStore()
        service = build_service(meeting_store=store)
        state_one = MeetingState(
            session_id="session-g",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        state_two = MeetingState(
            session_id="session-h",
            meet_url="https://meet.google.com/klm-nopq-rst",
            meeting_code="klm-nopq-rst",
            display_name="Orbit",
        )
        active_one = ActiveMeeting(
            session_id=state_one.session_id,
            meet_url=state_one.meet_url,
            state=state_one,
            capture_session_id="capture-g",
        )
        active_two = ActiveMeeting(
            session_id=state_two.session_id,
            meet_url=state_two.meet_url,
            state=state_two,
            capture_session_id="capture-h",
        )
        handle_one = FakeServerAudioSinkHandle(
            session_id="session-g",
            capture_session_id="capture-g",
            sink_name="orbit_meet_session_g",
            pid=1001,
        )
        handle_two = FakeServerAudioSinkHandle(
            session_id="session-h",
            capture_session_id="capture-h",
            sink_name="orbit_meet_session_h",
            pid=1002,
        )

        with patch(
            "orbit.whatsapp_service.start_server_audio_sink_capture",
            new_callable=AsyncMock,
            side_effect=[handle_one, handle_two],
        ) as start_capture:
            await service._start_server_audio_sink_capture(active_one)
            await service._start_server_audio_sink_capture(active_two)

        self.assertEqual(start_capture.await_count, 2)
        self.assertIsNot(active_one.server_audio_sink_handle, active_two.server_audio_sink_handle)
        self.assertIsNot(
            active_one.server_audio_sink_handle.ffmpeg_process,
            active_two.server_audio_sink_handle.ffmpeg_process,
        )
        self.assertNotEqual(
            active_one.server_audio_sink_handle.sink_name,
            active_two.server_audio_sink_handle.sink_name,
        )
        self.assertNotEqual(
            active_one.server_audio_sink_handle.module_id,
            active_two.server_audio_sink_handle.module_id,
        )

