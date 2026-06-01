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


class WhatsAppResponseMixin:
    async def send_whatsapp_message(self, body):
        log(f"Sending WhatsApp update: {body}", level="info")
        try:
            configure_dependency_logging()
            await asyncio.to_thread(
                self.twilio_client.messages.create,
                body=body,
                from_=self.twilio_whatsapp_from,
                to=self.twilio_allowed_from,
            )
        except Exception as error:
            log(f"WhatsApp send failed: {error}", level="error")

    async def answer_question(self, question):
        context_sections = await self.build_meeting_context()
        if not context_sections:
            return "I do not have enough live Meet chat context yet to answer that."

        prompt = (
            "Answer the WhatsApp question using only the meeting chat context below. "
            "If the context is insufficient, say so. If multiple meetings are relevant, name the meeting codes.\n\n"
            f"Question:\n{question}\n\n"
            f"Meeting chat context:\n{context_sections}"
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Orbit. Answer briefly and only from the supplied Google Meet chat context. "
                            "Do not invent meeting details or claim audio/transcript access."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            )
        except Exception as error:
            log(f"WhatsApp Q&A failed: {error}", level="error")
            return "I could not answer that right now because the Q&A model call failed."

        content = response.choices[0].message.content if response.choices else ""
        return (content or "").strip() or "I do not have enough meeting context to answer that."

    async def answer_general_question(self, question):
        try:
            memory_answer = await self.memory.answer_from_memory(question)
        except Exception as error:
            log(f"Memory Q&A failed: {error}", level="error")
            memory_answer = MemoryAnswer(
                "Stored company memory was unavailable for this question.",
                mode="insufficient_memory",
            )

        answer = memory_answer.answer.strip()
        sources = self.format_memory_sources(memory_answer.sources)
        if memory_answer.mode == "memory_answer" and answer:
            return self.format_answer_mode_message("memory_answer", answer, sources)

        general_answer = await self.answer_general_model_question(question)
        fallback_intro = (
            answer
            or "Stored company memory did not have enough grounded context for this question."
        )
        fallback_body = (
            f"{fallback_intro}\n\n"
            "This answer is not based on stored company memory.\n\n"
            f"{general_answer}"
        )
        return self.format_answer_mode_message("general_fallback", fallback_body)

    async def answer_general_model_question(self, question):
        dialogue_context = self.format_dialogue_history()
        prompt = question
        if dialogue_context:
            prompt = (
                "Use the recent WhatsApp dialogue only to resolve references in the user's latest message. "
                "Do not treat it as a source of company facts.\n\n"
                f"Recent dialogue:\n{dialogue_context}\n\n"
                f"Latest message:\n{question}"
            )
        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Orbit, a concise WhatsApp assistant. Answer general world, business, "
                            "and technology questions directly. If the question appears to ask about company "
                            "or meeting memory and no memory was available, say that you do not have stored "
                            "company context yet, then answer generally if useful."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as error:
            log(f"General WhatsApp answer failed: {error}", level="error")
            return "I could not answer that right now because the general model call failed."

        content = response.choices[0].message.content if response.choices else ""
        return (content or "").strip() or "I could not generate an answer for that."

    def format_memory_sources(self, sources: list[MemorySource]):
        labels = []
        seen = set()
        for source in sources:
            label = source.label
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) >= 3:
                break
        return "; ".join(labels)

    def format_answer_mode_message(self, mode: str, answer: str, sources: str = ""):
        label = ANSWER_MODE_LABELS.get(mode, mode.replace("_", " "))
        sections = [f"Answer mode: {label}", answer.strip()]
        if sources:
            sections.append(f"Sources: {sources}")
        return "\n\n".join(section for section in sections if section)

    async def build_meeting_context(self):
        async with self.lock:
            active_states = [active.state for active in self.active_sessions.values()]

        sections = []
        for state in active_states:
            if not state.captured_messages:
                continue

            recent_messages = state.captured_messages[-15:]
            lines = []
            for message in recent_messages:
                author = message.author or "unknown"
                timestamp = f" [{message.timestamp_text}]" if message.timestamp_text else ""
                lines.append(f"{author}{timestamp}: {message.normalized_text}")

            sections.append(
                f"Meet {state.meeting_code} ({state.status}):\n" + "\n".join(lines)
            )

        return "\n\n".join(sections)

