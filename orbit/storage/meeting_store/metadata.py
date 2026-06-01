from __future__ import annotations

from copy import deepcopy




CAPTURE_SESSION_STATUSES = {
    "scheduled",
    "starting",
    "joining",
    "live",
    "streaming_audio",
    "processing",
    "processed",
    "failed",
}


def default_capture_session_metadata() -> dict:
    return {
        "audio": {
            "first_chunk_at": None,
            "last_chunk_at": None,
            "chunk_count": 0,
            "bytes_received": 0,
            "bytes_forwarded_to_stt": 0,
            "last_chunk_size_bytes": 0,
            "silent_or_empty_chunk_count": 0,
            "streaming_started": False,
            "silence_gate_enabled": True,
            "silence_rms_threshold": 400,
            "speech_chunk_count": 0,
            "silent_chunk_count": 0,
            "bytes_dropped_silence": 0,
            "last_rms": 0,
            "last_speech_at": None,
            "last_silence_at": None,
            "silence_gated": False,
        },
        "deepgram": {
            "connect_started_at": None,
            "connected_at": None,
            "connection_closed_at": None,
            "close_code": None,
            "close_reason": None,
            "error": None,
            "keepalive_count": 0,
            "last_keepalive_at": None,
            "reconnect_count": 0,
            "first_transcript_at": None,
            "last_transcript_at": None,
            "final_transcript_count": 0,
            "interim_transcript_count": 0,
        },
    }


def merge_capture_session_metadata(current: dict | None, patch: dict | None) -> dict:
    merged = deepcopy(current) if isinstance(current, dict) else {}
    if not isinstance(patch, dict):
        return merged

    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_capture_session_metadata(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged
