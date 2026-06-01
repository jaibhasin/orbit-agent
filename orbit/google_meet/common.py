# ruff: noqa: F401
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from orbit.caption_attribution import CaptionSnippet
from orbit.audio_capture import get_audio_capture_strategy
from orbit.core import (
    CONVERSATION_DIR,
    DEBUG_DIR,
    configure_dependency_logging,
    ensure_browser_use_runtime,
    env_bool,
    env_int,
    extract_meeting_code,
    load_dotenv,
    log,
    normalize_message_text,
    now_iso,
)
from orbit.meet_types import (
    ChatMessage,
    MeetingSessionConfig,
    PermissionEvent,
    build_meeting_state,
)


POLL_INTERVAL_MS = 3000
PARTICIPANT_CHECK_INTERVAL_MS = 30000
SOLO_PARTICIPANT_POLLS_BEFORE_LEAVE = 2
ORBIT_MENTION_PATTERN = re.compile(r"(?<!\w)@orbit(?!\w)", re.IGNORECASE)
AUDIO_ROUTING_MODE_NOT_IMPLEMENTED = "not_implemented"
AUDIO_ROUTING_MODE_PROCESS_ENV = "process_env"
AUDIO_ROUTING_MODE_LAUNCH_WRAPPER = "launch_wrapper"


def _build_supported_kwargs(target, kwargs: dict) -> dict:
    if not kwargs:
        return {}
    try:
        signature = inspect.signature(target)
    except Exception:
        return kwargs

    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    return {
        key: value
        for key, value in kwargs.items()
        if accepts_var_kwargs or key in signature.parameters
    }


def _build_server_audio_env(sink_name: str | None):
    if not sink_name:
        return None
    return {"PULSE_SINK": sink_name}
