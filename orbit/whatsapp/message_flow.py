# mypy: disable-error-code="attr-defined,call-arg,arg-type,var-annotated"
# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .dependencies import *
from .intents import (
    clean_meet_link,
    extract_meet_links,
    extract_meeting_codes,
    format_twiml,
    is_qna_message,
    strip_qna_trigger,
)
from .models import ActiveMeeting, DialogueTurn, WhatsAppIntent


class WhatsAppMessageFlowMixin:
    async def handle_incoming_message(self, from_number, body, profile_name=None):
        if from_number != self.twilio_allowed_from:
            return format_twiml("")

        self._ensure_runtime_fields()
        body = (body or "").strip()
        if not body:
            return self._reply_without_history(
                "Send a Google Meet link to start Orbit, or send @orbit followed by a question."
            )

        meet_links = extract_meet_links(body)
        if meet_links:
            self.reset_dialogue_history()
            reply = await self.start_meeting_sessions(
                meet_links,
                from_number=from_number,
                profile_name=profile_name,
            )
            return self._reply_and_record(body, reply)

        intent = self.parse_whatsapp_intent(body)
        if intent.kind == "new":
            self.reset_dialogue_history()
            return self._reply_without_history("WhatsApp context reset. Active meetings are still running.")

        if intent.kind in {"status", "stop", "live_recall"}:
            reply = await self.execute_whatsapp_intent(intent)
            return self._reply_and_record(body, reply)

        if is_qna_message(body):
            question = strip_qna_trigger(body)
            if not question:
                return self._reply_and_record(body, "Send @orbit followed by your question.")
            answer = await self.answer_question(question)
            return self._reply_and_record(body, answer)

        answer = await self.answer_general_question(body)
        return self._reply_and_record(body, answer)

    def parse_whatsapp_intent(self, body):
        text = strip_qna_trigger(body).strip() if is_qna_message(body) else body.strip()
        lowered = text.lower()
        codes = extract_meeting_codes(text)
        meeting_code = codes[0] if codes else None

        if lowered == "/new":
            return WhatsAppIntent("new", text, meeting_code)

        status_patterns = (
            "status",
            "list meetings",
            "active meetings",
            "what meetings are active",
            "which meetings are active",
            "current meeting",
            "meeting status",
        )
        if any(pattern in lowered for pattern in status_patterns):
            return WhatsAppIntent("status", text, meeting_code)

        if STOP_COMMAND_PATTERN.match(text):
            return WhatsAppIntent("stop", text, meeting_code)

        live_patterns = (
            "what are people discussing",
            "what is being discussed",
            "what are they discussing",
            "summarize the meeting",
            "summarise the meeting",
            "recap the meeting",
            "meeting recap",
            "what happened",
            "what happened in the meeting",
            "what's happening in the meeting",
            "what is happening in the meeting",
            "live meeting",
        )
        if any(pattern in lowered for pattern in live_patterns):
            return WhatsAppIntent("live_recall", text, meeting_code)

        return WhatsAppIntent("fallback", text, meeting_code)

    async def execute_whatsapp_intent(self, intent):
        if intent.kind == "status":
            return await self.format_active_meeting_status(intent.meeting_code)
        if intent.kind == "stop":
            return await self.stop_active_meeting(intent.meeting_code)
        if intent.kind == "live_recall":
            return await self.answer_live_recall(intent.text, intent.meeting_code)
        return await self.answer_general_question(intent.text)

