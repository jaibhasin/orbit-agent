from __future__ import annotations

from .audio_streams import AudioStreamMixin
from .extraction import MeetingExtractionMixin
from .live_recall import LiveRecallMixin
from .meeting_sessions import MeetingSessionMixin
from .message_flow import WhatsAppMessageFlowMixin
from .responses import WhatsAppResponseMixin
from .runtime import RuntimeMixin


class OrbitWhatsAppService(
    RuntimeMixin,
    WhatsAppMessageFlowMixin,
    MeetingSessionMixin,
    AudioStreamMixin,
    LiveRecallMixin,
    MeetingExtractionMixin,
    WhatsAppResponseMixin,
):
    pass
