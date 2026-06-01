from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from orbit.audio_capture import (
    DEFAULT_AUDIO_CAPTURE_STRATEGY,
    ALLOWED_AUDIO_CAPTURE_STRATEGIES,
    get_audio_capture_strategy,
    build_ffmpeg_command,
    generate_sink_name,
)
from orbit.audio_capture.server_audio_sink import ServerAudioSinkHandle


class FakeSubprocess:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", return_code: int | None = 0):
        self.stdout = stdout
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = return_code
        self.return_code = return_code
        self.terminated = False
        self.killed = False
        self.wait_calls = 0
        self.communicate_calls = 0

    async def communicate(self):
        self.communicate_calls += 1
        return self._stdout, self._stderr

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    async def wait(self):
        self.wait_calls += 1
        self.returncode = 0
        self.return_code = 0
        return self.returncode


class AudioCaptureStrategyTests(unittest.TestCase):
    def setUp(self):
        self._orig_strategy = os.environ.get("ORBIT_AUDIO_CAPTURE_STRATEGY")

    def tearDown(self):
        if self._orig_strategy is None:
            os.environ.pop("ORBIT_AUDIO_CAPTURE_STRATEGY", None)
        else:
            os.environ["ORBIT_AUDIO_CAPTURE_STRATEGY"] = self._orig_strategy

    def test_strategy_is_always_chrome_extension(self):
        os.environ.pop("ORBIT_AUDIO_CAPTURE_STRATEGY", None)
        self.assertEqual(get_audio_capture_strategy(), DEFAULT_AUDIO_CAPTURE_STRATEGY)
        self.assertIn("chrome_extension", ALLOWED_AUDIO_CAPTURE_STRATEGIES)

        os.environ["ORBIT_AUDIO_CAPTURE_STRATEGY"] = "server_audio_sink"
        self.assertEqual(get_audio_capture_strategy(), DEFAULT_AUDIO_CAPTURE_STRATEGY)

        os.environ["ORBIT_AUDIO_CAPTURE_STRATEGY"] = "unsupported"
        self.assertEqual(get_audio_capture_strategy(), DEFAULT_AUDIO_CAPTURE_STRATEGY)


class SinkNameTests(unittest.TestCase):
    def test_sink_name_is_prefixed_and_sanitized(self):
        sink_name = generate_sink_name("Ab C!d@e#f$g 123")

        self.assertTrue(sink_name.startswith("orbit_meet_"))
        self.assertNotIn(" ", sink_name)
        self.assertNotIn("@", sink_name)
        self.assertNotIn("#", sink_name)
        self.assertNotIn("$", sink_name)

    def test_different_sessions_get_different_sink_names(self):
        self.assertNotEqual(
            generate_sink_name("meeting-one"),
            generate_sink_name("meeting-two"),
        )


class FfmpegCommandTests(unittest.TestCase):
    def test_build_ffmpeg_command_uses_expected_shape(self):
        self.assertEqual(
            build_ffmpeg_command("orbit_meet_ab12cd34"),
            [
                "ffmpeg",
                "-f",
                "pulse",
                "-i",
                "orbit_meet_ab12cd34.monitor",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "s16le",
                "pipe:1",
            ],
        )


class ServerAudioSinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_calls_load_module_with_expected_sink(self):
        load_module = FakeSubprocess(stdout=b"17\n")
        ffmpeg_process = FakeSubprocess(return_code=None)

        with patch(
            "orbit.audio_capture.server_audio_sink.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as run_subprocess:
            run_subprocess.side_effect = [load_module, ffmpeg_process]

            handle = ServerAudioSinkHandle(
                session_id="session-1",
                capture_session_id="capture-1",
                sink_name="orbit_meet_session_1",
            )
            await handle.start()

        self.assertEqual(handle.module_id, "17")
        self.assertIs(handle.ffmpeg_process, ffmpeg_process)
        self.assertEqual(run_subprocess.await_args_list[0].args, (
            "pactl",
            "load-module",
            "module-null-sink",
            "sink_name=orbit_meet_session_1",
        ))
        self.assertEqual(run_subprocess.await_args_list[1].args, tuple(build_ffmpeg_command("orbit_meet_session_1")))

    async def test_stop_terminates_ffmpeg_and_unloads_module(self):
        ffmpeg_process = FakeSubprocess(return_code=None)
        handle = ServerAudioSinkHandle(
            session_id="session-1",
            capture_session_id="capture-1",
            sink_name="orbit_meet_session_1",
            module_id="17",
            ffmpeg_process=ffmpeg_process,
        )

        unload_module = FakeSubprocess()

        with patch(
            "orbit.audio_capture.server_audio_sink.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as run_subprocess:
            run_subprocess.return_value = unload_module
            await handle.stop()

        self.assertTrue(ffmpeg_process.terminated)
        self.assertGreater(ffmpeg_process.wait_calls, 0)
        self.assertEqual(handle.module_id, None)
        self.assertEqual(run_subprocess.await_args_list[0].args, ("pactl", "unload-module", "17"))

    async def test_stop_is_idempotent(self):
        ffmpeg_process = FakeSubprocess(return_code=None)
        handle = ServerAudioSinkHandle(
            session_id="session-1",
            capture_session_id="capture-1",
            sink_name="orbit_meet_session_1",
            module_id="17",
            ffmpeg_process=ffmpeg_process,
        )

        unload_module = FakeSubprocess()
        with patch(
            "orbit.audio_capture.server_audio_sink.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as run_subprocess:
            run_subprocess.return_value = unload_module
            await handle.stop()
            await handle.stop()

        self.assertTrue(ffmpeg_process.terminated)
        # idempotent stop should perform unload only once after module_id is cleared
        self.assertEqual(run_subprocess.await_count, 1)

    async def test_two_handles_do_not_share_state(self):
        p1_load = FakeSubprocess(stdout=b"12\n")
        p1_ffmpeg = FakeSubprocess(return_code=None)
        p2_load = FakeSubprocess(stdout=b"13\n")
        p2_ffmpeg = FakeSubprocess(return_code=None)

        with patch(
            "orbit.audio_capture.server_audio_sink.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as run_subprocess:
            run_subprocess.side_effect = [p1_load, p1_ffmpeg, p2_load, p2_ffmpeg]
            h1 = ServerAudioSinkHandle(
                session_id="meeting-a",
                capture_session_id="capture-a",
                sink_name=generate_sink_name("meeting-a"),
            )
            h2 = ServerAudioSinkHandle(
                session_id="meeting-b",
                capture_session_id="capture-b",
                sink_name=generate_sink_name("meeting-b"),
            )
            await h1.start()
            await h2.start()

        self.assertNotEqual(h1.sink_name, h2.sink_name)
        self.assertNotEqual(h1.module_id, h2.module_id)
        self.assertIsNot(h1.ffmpeg_process, h2.ffmpeg_process)
