# mypy: disable-error-code="no-redef"
# ruff: noqa: F401
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from orbit.audio_capture import get_audio_capture_strategy, start_server_audio_sink_capture
from orbit.core import (
    env_int,
    configure_dependency_logging,
    extract_meeting_code,
    load_dotenv,
    log,
    now_iso,
)
from orbit.audio_vad import (
    DEFAULT_POST_ROLL_MS,
    DEFAULT_PRE_ROLL_MS,
    DEFAULT_SILENCE_DROP_AFTER_MS,
    DEFAULT_SILENCE_RMS_THRESHOLD,
    PCM16SilenceGate,
)
from orbit.meet import build_default_session_config, run_meeting_session
from orbit.meet_types import (
    ChatMessage,
    MeetingSessionCallbacks,
    MeetingSessionConfig,
    MeetingState,
    build_meeting_state,
)
from orbit.meeting_store import (
    build_meeting_store,
    default_capture_session_metadata,
    merge_capture_session_metadata,
)
from orbit.phone_numbers import normalize_whatsapp_phone
from orbit.memory import MemoryAnswer, MemorySource, build_memory_service
from orbit.live_stt import LiveAudioFormat, LiveSTTManager
from orbit.transcript import TranscriptSegment, format_timestamp_ms
from openai import AsyncOpenAI
try:
    from twilio.rest import Client
    from twilio.twiml.messaging_response import MessagingResponse
except Exception:
    class Client:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("Twilio SDK is not installed.")

    class MessagingResponse:
        def __init__(self, *args, **kwargs):
            self._value = ""

        def message(self, body=None):
            if body is not None:
                self._value = body
            return self._value

        def __str__(self):
            return str(self._value)


MEET_LINK_PATTERN = re.compile(r"https://meet\.google\.com/[^\s<>\"]+", re.IGNORECASE)
MEETING_CODE_PATTERN = re.compile(r"\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b", re.IGNORECASE)
QNA_TRIGGER_PATTERN = re.compile(r"^\s*(?:@orbit\b|orbit\s*:)\s*", re.IGNORECASE)
STOP_COMMAND_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"leave(?:\s+(?:meet(?:ing)?\s+)?)?|"
    r"stop\s+(?:recording|monitoring|orbit)|"
    r"end\s+(?:meeting|recording)"
    r")(?:\s+[a-z]{3}-[a-z]{4}-[a-z]{3})?\s*[.!?]?\s*$",
    re.IGNORECASE,
)
MAX_DIALOGUE_TURNS = 12
MAX_DIALOGUE_MESSAGE_CHARS = 2000
LIVE_RECALL_MAX_SEGMENTS = 30
LIVE_RECAP_MAX_SEGMENTS = 40
LIVE_RECALL_MAX_PROMPT_CHARS = 8000
STOP_TIMEOUT_SECONDS = 10
CAPTURE_HEARTBEAT_INTERVAL_SECONDS = 15
CAPTURE_AUDIO_METADATA_FLUSH_CHUNKS = 25
CAPTURE_AUDIO_METADATA_FLUSH_INTERVAL_SECONDS = 5
DEEPGRAM_KEEPALIVE_INTERVAL_SECONDS = 5
FFMPEG_START_ERROR_CODE = "FFMPEG_START_FAILED"
NO_AUDIO_FROM_SINK_ERROR_CODE = "NO_AUDIO_FROM_SINK"
FFMPEG_STREAM_ENDED_ERROR_CODE = "FFMPEG_STREAM_ENDED"
AUDIO_SINK_CREATE_ERROR_CODE = "AUDIO_SINK_CREATE_FAILED"
FFMPEG_STREAM_EXITED_WITHOUT_CHUNKS = "No audio reached Orbit from the server audio sink."
MEETING_EXTRACTION_PROMPT_VERSION = "meeting-extractor-v1"
MEETING_EXTRACTION_RUN_TYPE = "full_meeting_extraction"
MEETING_EXTRACT_PROMPT = """You are extracting structured company memory from timestamped meeting evidence.

Return only valid JSON. Do not include markdown.

Extract:
- short summary
- long summary
- decisions
- action items
- risks
- open questions
- durable memories

Rules:
- Do not invent information.
- If there are no decisions, return an empty decisions array.
- Do not treat suggestions as decisions.
- Only extract action items if there is a clear task.
- If owner is unclear, use null or empty string.
- Use confidence from 0 to 1.
- Keep output concise.

Meeting evidence:
{transcript}
"""
ANSWER_MODE_LABELS = {
    "memory_answer": "memory-backed recall",
    "insufficient_memory": "insufficient company memory",
    "general_fallback": "general fallback",
}


