# mypy: disable-error-code="call-arg"
from __future__ import annotations

from .disabled import DisabledMeetingStore
from .postgres import PostgresMeetingStore


def build_meeting_store(database_url: str | None):
    if not database_url:
        return DisabledMeetingStore()

    return PostgresMeetingStore(database_url=database_url)
