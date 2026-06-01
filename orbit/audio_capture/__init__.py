from __future__ import annotations

from .server_audio_sink import (
    ServerAudioSinkHandle,
    build_ffmpeg_command,
    generate_sink_name,
    start_server_audio_sink_capture,
)

ALLOWED_AUDIO_CAPTURE_STRATEGIES = ("chrome_extension", "server_audio_sink")
DEFAULT_AUDIO_CAPTURE_STRATEGY = "chrome_extension"


def get_audio_capture_strategy() -> str:
    """Return the active audio capture strategy (`chrome_extension` only)."""
    return DEFAULT_AUDIO_CAPTURE_STRATEGY


__all__ = [
    "ALLOWED_AUDIO_CAPTURE_STRATEGIES",
    "DEFAULT_AUDIO_CAPTURE_STRATEGY",
    "ServerAudioSinkHandle",
    "build_ffmpeg_command",
    "generate_sink_name",
    "start_server_audio_sink_capture",
    "get_audio_capture_strategy",
]
