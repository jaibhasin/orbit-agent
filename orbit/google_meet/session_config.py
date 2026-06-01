# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *


def build_task(meet_url, display_name):
    return f"""
Open this Google Meet URL: {meet_url}

This automation is only allowed to join meetings I already have permission to join. Do not attempt to bypass sign-in, host approval, guest restrictions, or any Google security control.

Steps:
1. Stay on the Google Meet page for this URL.
2. Join with microphone and camera disabled. The page may ask "Do you want people to see and hear you in the meeting?" and show an "Allow microphone and camera" button. Ignore that entire prompt. Never click "Allow microphone and camera", never use the page info icon, and never enable browser site permissions.
3. If a modal says "Meet is blocked from using your microphone and camera", click its "Close dialog" button (the X) immediately. This is expected when joining silently and is not a reason to stop. Do not interact with elements behind the modal until it is closed.
4. If and only if a visible button says "Continue without microphone and camera", click that button.
5. If a visible guest name field exists, fill it with "{display_name}".
6. Perform name entry as its own step. After filling the guest name, inspect the refreshed page before clicking anything else. Never combine filling the name with a click in the same action sequence.
7. If microphone or camera toggles are on in the pre-join screen, turn them off.
8. Click the best available visible join button by its text, preferring "Ask to join", then "Join now", then "Request to join", then "Join". Do not click Terms of Service, Privacy Policy, or any footer link.
9. Treat the guest pre-join area as the source of truth. If the page shows a name input and a join button, continue the guest join flow even if a top-right "Sign in" link, tooltip, or helper bubble is also visible.
10. Do not treat a generic top-right "Sign in" link or tooltip as a blocking condition by itself. Only treat sign-in as blocking if the main page content explicitly says sign-in is required or the meeting cannot be joined without it.
11. After clicking the join button, remain on the meeting page and do not navigate away.
12. If the page says you are asking to be let in, you will join when someone lets you in, or a host must bring you into the call, finish successfully immediately and report that the join request was submitted. Orbit will wait for admission outside this browser-agent loop. Do not keep waiting or polling for host approval yourself.
13. If the page says the request was denied or the meeting cannot be joined, stop and report the exact visible reason.
14. Finish only after you have joined successfully, submitted a host-approval request, or clearly determined that Google Meet blocked entry.
""".strip()


def build_intro_message(display_name):
    return (
        "Hi everyone, I’m Orbit. "
        "I’ll be recording and monitoring this meeting."
        "Mention @orbit in chat to get my attention."
    )

def build_default_session_config(meet_url, session_id=None):
    load_dotenv()
    meeting_code = extract_meeting_code(meet_url)
    resolved_session_id = session_id or f"manual-{meeting_code}"
    live_stt_enabled = env_bool("ORBIT_LIVE_STT_ENABLED", bool(os.environ.get("DEEPGRAM_API_KEY")))
    audio_ws_base_url = os.environ.get("ORBIT_AUDIO_WS_BASE_URL", "ws://127.0.0.1:8000").rstrip("/")
    audio_stream_token = secrets.token_urlsafe(24) if live_stt_enabled else None
    audio_stream_ws_url = f"{audio_ws_base_url}/internal/audio-stream/{resolved_session_id}"
    if audio_stream_token:
        audio_stream_ws_url = f"{audio_stream_ws_url}?{urlencode({'token': audio_stream_token})}"
    return MeetingSessionConfig(
        session_id=resolved_session_id,
        meet_url=meet_url,
        display_name=os.environ.get("GMEET_DISPLAY_NAME", "Orbit Agent"),
        wait_after_join_ms=env_int("GMEET_WAIT_AFTER_JOIN_MS", 300000),
        max_steps=env_int("GMEET_BROWSER_USE_MAX_STEPS", 20),
        model_name=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"),
        live_stt_enabled=live_stt_enabled,
        audio_capture_strategy=get_audio_capture_strategy(),
        audio_sink_name=None,
        audio_stream_ws_url=audio_stream_ws_url,
        audio_stream_token=audio_stream_token,
    )
