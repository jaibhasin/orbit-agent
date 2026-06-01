from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from orbit.meet import (
    build_intro_message,
    build_task,
    finalize_meeting_status,
    get_participant_count,
    ensure_joined,
    is_orbit_authored_message,
    monitor_chat,
    should_leave_when_only_orbit_remains,
    trigger_extension_audio_capture,
)
from orbit.meet_types import ChatMessage, MeetingState


class MeetChatTests(unittest.TestCase):
    def test_join_task_handles_blocked_media_modal_without_enabling_permissions(self):
        task = build_task("https://meet.google.com/abc-defg-hij", "Orbit")

        self.assertIn('Never click "Allow microphone and camera"', task)
        self.assertIn('click its "Close dialog" button (the X) immediately', task)
        self.assertIn("is not a reason to stop", task)
        self.assertIn("Never combine filling the name with a click", task)
        self.assertIn("Do not click Terms of Service", task)

    def test_orbit_intro_is_detected_as_orbit_authored(self):
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )
        intro = build_intro_message(state.display_name)
        message = ChatMessage(
            fingerprint="fp-1",
            raw_text=f"{intro} Hover over a message to pin it",
            normalized_text=f"{intro} Hover over a message to pin it",
            author=intro,
            timestamp_text="",
        )

        self.assertTrue(is_orbit_authored_message(state, message))

    def test_finished_joined_meeting_becomes_completed(self):
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            status="live_stt_capture_requested",
            joined_at="2026-05-31T00:00:00+05:30",
        )

        finalize_meeting_status(state)

        self.assertEqual(state.status, "completed")

    def test_finished_error_takes_precedence_over_joined(self):
        state = MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
            joined_at="2026-05-31T00:00:00+05:30",
            last_error="browser crashed",
        )

        finalize_meeting_status(state)

        self.assertEqual(state.status, "failed")


class ParticipantExitTests(unittest.IsolatedAsyncioTestCase):
    class FakePage:
        def __init__(self, result):
            self.result = result

        async def evaluate(self, script, *args):
            return self.result

    def build_state(self):
        return MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )

    async def test_participant_count_reads_dom_result(self):
        page = self.FakePage('{"count": 3}')

        self.assertEqual(await get_participant_count(page), 3)

    async def test_participant_count_returns_none_when_dom_has_no_count(self):
        page = self.FakePage('{"count": null}')

        self.assertIsNone(await get_participant_count(page))

    async def test_joining_alone_does_not_trigger_early_leave(self):
        state = self.build_state()

        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))
        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))

    async def test_leaves_after_other_participants_depart(self):
        state = self.build_state()

        self.assertFalse(should_leave_when_only_orbit_remains(state, 3))
        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))
        self.assertTrue(should_leave_when_only_orbit_remains(state, 1))

    async def test_unknown_count_resets_solo_poll_streak(self):
        state = self.build_state()

        self.assertFalse(should_leave_when_only_orbit_remains(state, 2))
        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))
        self.assertFalse(should_leave_when_only_orbit_remains(state, None))
        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))

    async def test_leaves_after_solo_poll_threshold_without_other_participants(self):
        state = self.build_state()

        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))
        self.assertFalse(should_leave_when_only_orbit_remains(state, 1))
        self.assertTrue(should_leave_when_only_orbit_remains(state, 1))

    @patch("orbit.google_meet.chat.process_messages", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.collect_visible_chat_messages", new_callable=AsyncMock, return_value=[])
    @patch("orbit.google_meet.chat.collect_visible_captions", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.send_introduction", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.open_chat_panel", new_callable=AsyncMock, return_value=True)
    @patch("orbit.google_meet.chat.get_participant_count", new_callable=AsyncMock, return_value=2)
    @patch("orbit.google_meet.chat.asyncio.sleep", new_callable=AsyncMock)
    async def test_monitor_checks_participants_every_thirty_seconds(
        self,
        sleep,
        get_count,
        open_chat,
        send_intro,
        collect_captions,
        collect_messages,
        process_messages,
    ):
        page = object()
        state = self.build_state()

        await monitor_chat(page, state, wait_after_run_ms=100)

        get_count.assert_awaited_once_with(page)
        collect_captions.assert_not_awaited()
        self.assertEqual(state.leave_reason, "Meeting monitoring duration elapsed.")

    @patch("orbit.google_meet.chat.process_messages", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.collect_visible_chat_messages", new_callable=AsyncMock, return_value=[])
    @patch("orbit.google_meet.chat.collect_visible_captions", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.send_introduction", new_callable=AsyncMock)
    @patch("orbit.google_meet.chat.open_chat_panel", new_callable=AsyncMock, return_value=True)
    @patch("orbit.google_meet.chat.get_participant_count", new_callable=AsyncMock)
    async def test_monitor_exits_when_stop_requested(
        self,
        get_count,
        open_chat,
        send_intro,
        collect_captions,
        collect_messages,
        process_messages,
    ):
        page = object()
        state = self.build_state()
        state.stop_requested = True
        state.stop_reason = "Orbit was asked from WhatsApp to stop monitoring this meeting."

        await monitor_chat(page, state, wait_after_run_ms=100)

        get_count.assert_not_awaited()
        self.assertEqual(
            state.leave_reason,
            "Orbit was asked from WhatsApp to stop monitoring this meeting.",
        )


class JoinDetectionTests(unittest.IsolatedAsyncioTestCase):
    class FakePage:
        def __init__(self, results):
            self.results = iter(results)

        async def evaluate(self, script, *args):
            value = next(self.results)
            return value if isinstance(value, str) else json.dumps(value)

    @patch("orbit.google_meet.chat.asyncio.sleep", new_callable=AsyncMock)
    async def test_waiting_for_host_then_joins(self, sleep):
        on_waiting = AsyncMock()
        page = self.FakePage(
            [
                {"waiting_for_host": True, "denied": False, "blocked": False, "has_joined_control": False},
                {"waiting_for_host": True, "denied": False, "blocked": False, "has_joined_control": False},
                {"waiting_for_host": False, "denied": False, "blocked": False, "has_joined_control": True},
            ]
        )

        joined, status = await ensure_joined(page, timeout_ms=9000, on_waiting=on_waiting)

        self.assertTrue(joined)
        self.assertIsNotNone(status)
        self.assertTrue(status["has_joined_control"])
        on_waiting.assert_awaited_once()
        self.assertGreaterEqual(sleep.await_count, 2)

    @patch("orbit.google_meet.chat.asyncio.sleep", new_callable=AsyncMock)
    async def test_denied_join_stays_not_joined(self, sleep):
        page = self.FakePage(
            [
                {"waiting_for_host": True, "denied": False, "blocked": False, "has_joined_control": False},
                {"waiting_for_host": False, "denied": True, "blocked": False, "has_joined_control": False},
            ]
        )

        joined, status = await ensure_joined(page, timeout_ms=9000)

        self.assertFalse(joined)
        self.assertIsNotNone(status)
        self.assertTrue(status["denied"])


class TriggerExtensionAudioCaptureTests(unittest.IsolatedAsyncioTestCase):
    class FakePage:
        def __init__(self, evaluate_results):
            self.evaluate_results = iter(evaluate_results)
            self._mouse = AsyncMock()
            self.press = AsyncMock()

        async def evaluate(self, script, *args):
            return next(self.evaluate_results)

        @property
        async def mouse(self):
            return self._mouse

    def build_state(self):
        return MeetingState(
            session_id="session-1",
            meet_url="https://meet.google.com/abc-defg-hij",
            meeting_code="abc-defg-hij",
            display_name="Orbit",
        )

    async def test_returns_false_without_audio_stream_url(self):
        page = self.FakePage([])
        state = self.build_state()

        result = await trigger_extension_audio_capture(page, state, None)

        self.assertFalse(result)
        page.press.assert_not_awaited()

    async def test_returns_false_when_capture_config_post_fails(self):
        page = self.FakePage([])
        page.evaluate = AsyncMock(side_effect=RuntimeError("page unavailable"))
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertFalse(result)
        self.assertIn("page unavailable", state.live_stt_status_detail)
        page.press.assert_not_awaited()

    async def test_clicks_injected_audio_button(self):
        page = self.FakePage(
            [
                True,
                '{"found": true, "x": 120.8, "y": 45.2}',
                True,
                '{"label": "Orbit audio active", "disabled": true}',
            ]
        )
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertTrue(result)
        self.assertEqual(
            state.live_stt_status_detail,
            "Orbit extension accepted the audio capture request.",
        )
        page._mouse.click.assert_not_awaited()
        page.press.assert_not_awaited()

    @patch("orbit.google_meet.extension_audio.asyncio.sleep", new_callable=AsyncMock)
    async def test_uses_shortcut_when_audio_button_is_missing(self, sleep):
        page = self.FakePage(
            [True] + ['{"found": false}'] * 10 + ['{"label": "Orbit audio active", "disabled": true}']
        )
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertTrue(result)
        page.press.assert_awaited_once_with("Alt+Shift+O")
        self.assertEqual(sleep.await_count, 10)

    async def test_uses_shortcut_when_audio_button_rejects_capture(self):
        page = self.FakePage(
            [
                True,
                '{"found": true, "x": 120.8, "y": 45.2}',
                True,
                '{"label": "Use Alt+Shift+O or the extension icon", "disabled": false}',
                '{"label": "Orbit audio active", "disabled": true}',
            ]
        )
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertTrue(result)
        page.press.assert_awaited_once_with("Alt+Shift+O")

    async def test_uses_shortcut_when_audio_button_status_check_fails(self):
        page = self.FakePage(
            [
                True,
                '{"found": true, "x": 120.8, "y": 45.2}',
                RuntimeError("page rerendered"),
                '{"label": "Orbit audio active", "disabled": true}',
            ]
        )
        original_evaluate = page.evaluate

        async def evaluate(script, *args):
            result = await original_evaluate(script, *args)
            if isinstance(result, Exception):
                raise result
            return result

        page.evaluate = evaluate
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertTrue(result)
        page.press.assert_awaited_once_with("Alt+Shift+O")

    @patch("orbit.google_meet.extension_audio.asyncio.sleep", new_callable=AsyncMock)
    async def test_returns_false_when_button_and_shortcut_activation_fail(self, sleep):
        page = self.FakePage([True] + ['{"found": false}'] * 10)
        page.press.side_effect = RuntimeError("shortcut unavailable")
        state = self.build_state()

        result = await trigger_extension_audio_capture(
            page,
            state,
            "ws://127.0.0.1:8000/internal/audio-stream/session-1",
        )

        self.assertFalse(result)
        self.assertIn("shortcut unavailable", state.live_stt_status_detail)


if __name__ == "__main__":
    unittest.main()
