# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .dom import evaluate_json


def _log_state(session_id, status):
    if not status:
        return "unknown"
    return (status.get("label") or "").strip()[:80]


async def trigger_extension_audio_capture(page, state, audio_stream_ws_url):
    if not audio_stream_ws_url:
        return False

    async def _read_button_state():
        return await evaluate_json(
            page,
            """() => {
                const button = document.getElementById('orbit-audio-capture-button');
                if (!button) return JSON.stringify({ found: false });
                const rect = button.getBoundingClientRect();
                return JSON.stringify({
                    found: true,
                    disabled: Boolean(button?.disabled),
                    label: String(button?.textContent || ''),
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                });
            }""",
        )

    async def _read_activation_state():
        status = await _read_button_state()
        if not status:
            return None
        label = str(status.get("label") or "").strip().lower()
        if status.get("disabled") or "capture active" in label or "orbit audio capture active" in label:
            return "active"
        if "starting orbit audio" in label:
            return "starting"
        if "use alt+shift+o" in label:
            return "shortcut"
        return None

    async def _wait_for_activation(timeout_seconds: float = 2.5, include_starting: bool = False):
        attempts = max(1, int(timeout_seconds / 0.2))
        for _ in range(attempts):
            activation_state = await _read_activation_state()
            if activation_state and (activation_state != "starting" or include_starting):
                return activation_state
            await asyncio.sleep(0.2)
        return None

    payload = {
        "source": "orbit",
        "type": "ORBIT_START_CAPTURE",
        "sessionId": state.session_id,
        "meetingId": state.meeting_code,
        "webSocketUrl": audio_stream_ws_url,
        "audioFormat": {
            "encoding": "linear16",
            "sampleRate": 16000,
            "channels": 1,
        },
        "visualCapture": {
            "enabled": env_bool("ORBIT_VISUAL_CAPTURE_ENABLED", False),
            "sampleIntervalMs": env_int("ORBIT_VISUAL_SAMPLE_INTERVAL_MS", 3000),
            "cooldownMs": env_int("ORBIT_VISUAL_COOLDOWN_MS", 8000),
            "changeThreshold": float(os.environ.get("ORBIT_VISUAL_CHANGE_THRESHOLD", "0.08")),
            "stabilityThreshold": float(os.environ.get("ORBIT_VISUAL_STABILITY_THRESHOLD", "0.02")),
            "maxWidth": env_int("ORBIT_VISUAL_MAX_WIDTH", 1280),
            "jpegQuality": float(os.environ.get("ORBIT_VISUAL_JPEG_QUALITY", "0.65")),
        },
    }

    try:
        await page.evaluate(
            """(payload) => {
                window.postMessage(payload, window.location.origin);
                return true;
            }""",
            payload,
        )
        state.live_stt_status_detail = "Extension capture start message posted."
        log(
            "evt=stt.extension_message_posted source=browser_message url=%s"
            % state.meeting_code,
            state.session_id,
            level="important",
        )
    except Exception as error:
        state.live_stt_status_detail = f"Extension capture start message failed: {error}"
        log(f"evt=stt.extension_message_post_failed reason={_safe_error(error)}", state.session_id, level="error")
        return False

    button_clicked = False
    for _ in range(10):
        try:
            click_result = await _read_button_state()
            if click_result and click_result["found"]:
                await page.evaluate(
                    """() => {
                        const button = document.getElementById("orbit-audio-capture-button");
                        if (button) {
                            button.click();
                            return true;
                        }
                        return false;
                    }""",
                )
                log(
                    f"evt=stt.extension_button_clicked label={_log_state(state.session_id, click_result)}",
                    state.session_id,
                    level="important",
                )
                button_clicked = True
                break
        except Exception as error:
            log(
                f"evt=stt.extension_button_click_failed reason={_safe_error(error)}",
                state.session_id,
                level="error",
            )
            break
        await asyncio.sleep(0.2)

    if not button_clicked:
        log(
            "evt=stt.extension_button_not_found",
            state.session_id,
            level="important",
        )

    if button_clicked:
        activation_state = await _wait_for_activation(include_starting=True)
        if activation_state == "active":
            state.live_stt_status_detail = "Orbit extension accepted the audio capture request."
            log("evt=stt.extension_active", state.session_id, level="important")
            return True
        if activation_state == "starting":
            state.live_stt_status_detail = (
                "Orbit capture button is starting capture. Treating as accepted."
            )
            log("evt=stt.extension_starting", state.session_id, level="important")
            return True
        if activation_state == "shortcut":
            log("evt=stt.extension_shortcut_prompted", state.session_id, level="important")

    shortcut = os.environ.get("ORBIT_EXTENSION_CAPTURE_SHORTCUT", "Alt+Shift+O")
    try:
        if hasattr(page, "keyboard"):
            await page.keyboard.press(shortcut)
        else:
            await page.press(shortcut)
        state.live_stt_status_detail = f"Tried Orbit extension activation shortcut: {shortcut}"
        log(f"evt=stt.extension_shortcut_attempt shortcut={shortcut}", state.session_id, level="important")
        activation_state = await _wait_for_activation(include_starting=True)
        if activation_state == "active":
            state.live_stt_status_detail = "Orbit extension accepted the audio capture request."
            log("evt=stt.extension_active", state.session_id, level="important")
            return True
        if activation_state == "starting":
            state.live_stt_status_detail = "Orbit extension shortcut is still starting capture. Treating as accepted."
            log("evt=stt.extension_starting", state.session_id, level="important")
            return True
        state.live_stt_status_detail = (
            "Orbit extension activation was attempted, but capture button did not show an active state."
        )
        log("evt=stt.extension_not_active", state.session_id, level="important")
        return False
    except Exception as error:
        state.live_stt_status_detail = f"Orbit extension activation shortcut failed: {error}"
        log(f"evt=stt.extension_shortcut_failed reason={_safe_error(error)}", state.session_id, level="error")
        return False


def _safe_error(error):
    text = str(error or "")
    return text[:120].replace(" ", "_")
