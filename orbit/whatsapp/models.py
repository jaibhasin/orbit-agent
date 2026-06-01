# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .dependencies import *



@dataclass
class ActiveMeeting:
    session_id: str
    meet_url: str
    state: MeetingState
    source_id: str | None = None
    meeting_id: str | None = None
    capture_session_id: str | None = None
    task: asyncio.Task | None = None
    created_at: str = field(default_factory=now_iso)
    last_capture_heartbeat_at: float = 0.0
    capture_failure_recorded: bool = False
    capture_health_metadata: dict = field(default_factory=default_capture_session_metadata)
    server_audio_sink_handle: object | None = None
    server_audio_reader_task: asyncio.Task | None = None
    live_stt_session: object | None = None
    audio_chunks_since_metadata_flush: int = 0
    last_capture_metadata_flush_at: float = 0.0
    audio_silence_gate: PCM16SilenceGate | None = None
    last_deepgram_keepalive_at: float = 0.0


@dataclass

class DialogueTurn:
    inbound: str
    reply: str


@dataclass

class WhatsAppIntent:
    kind: str
    text: str
    meeting_code: str | None = None
