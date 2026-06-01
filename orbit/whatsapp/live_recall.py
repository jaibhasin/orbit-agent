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


class LiveRecallMixin:
    async def answer_live_recall(self, question, meeting_code=None):
        active, error = await self.resolve_active_meeting(meeting_code)
        if error:
            return error

        state = active.state
        if state.live_stt_requested and not state.live_stt_available:
            detail = f" {state.live_stt_status_detail}" if state.live_stt_status_detail else ""
            return f"Live transcription is unavailable for Meet {state.meeting_code}.{detail}"
        if not state.live_stt_requested:
            return f"Live transcription has not been requested for Meet {state.meeting_code}."
        if not state.live_stt_started:
            return f"Live transcription has not started for Meet {state.meeting_code} yet. Wait until Orbit confirms the first audio chunk."
        if len(state.live_transcript_segments) < 2:
            return f"Orbit has too little live transcript context for Meet {state.meeting_code} yet. Ask again after more discussion is captured."

        broad = self.is_broad_live_recap(question)
        segments = self.select_live_segments(state.live_transcript_segments, question, broad=broad)
        if not segments:
            return f"Orbit does not have enough relevant live transcript context for Meet {state.meeting_code} yet."

        context = self.format_live_segments_for_prompt(state.meeting_code, segments)
        prompt = (
            "Answer the WhatsApp question using only the live transcript excerpts below. "
            "If the excerpts are insufficient, say so. Keep the answer concise and cite sources inline "
            "using the provided source labels.\n\n"
            f"Question:\n{question}\n\n"
            f"Live transcript excerpts:\n{context}"
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Orbit answering from live Google Meet transcript excerpts only. "
                            "Do not use historical company memory or invent uncited meeting details."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as error:
            log(f"Live recall answer failed: {error}", state.session_id, level="error")
            return "I could not answer from the live transcript right now because the model call failed."

        content = response.choices[0].message.content if response.choices else ""
        answer = (content or "").strip()
        sources = self.format_live_source_summary(state.meeting_code, segments)
        if not answer:
            answer = f"Orbit does not have enough live transcript context for Meet {state.meeting_code} yet."
        return self.format_answer_mode_message("live transcript", answer, sources)

    def is_broad_live_recap(self, question):
        lowered = question.lower()
        return any(
            phrase in lowered
            for phrase in (
                "summarize",
                "summarise",
                "recap",
                "what happened",
                "what are people discussing",
                "what is being discussed",
                "what are they discussing",
            )
        )

    def select_live_segments(self, segments, question, broad=False):
        if broad:
            return self.limit_segments_for_prompt(segments[-LIVE_RECAP_MAX_SEGMENTS:])

        query_terms = {
            term
            for term in re.findall(r"[a-z0-9]+", question.lower())
            if len(term) > 2
            and term
            not in {
                "the",
                "and",
                "are",
                "what",
                "who",
                "why",
                "how",
                "meeting",
                "live",
                "orbit",
            }
        }
        scored: list[tuple[float, int, TranscriptSegment]] = []
        for index, segment in enumerate(segments):
            segment_terms = set(re.findall(r"[a-z0-9]+", segment.clean_text.lower()))
            score = float(len(query_terms & segment_terms))
            score += index / max(len(segments), 1)
            if score > 0:
                scored.append((score, index, segment))
        selected = [item[2] for item in sorted(scored, key=lambda item: item[0], reverse=True)]
        if not selected:
            selected = segments[-LIVE_RECALL_MAX_SEGMENTS:]
        selected = sorted(selected[:LIVE_RECALL_MAX_SEGMENTS], key=lambda segment: segments.index(segment))
        return self.limit_segments_for_prompt(selected)

    def limit_segments_for_prompt(self, segments):
        total_chars = 0
        selected: list[TranscriptSegment] = []
        for segment in segments:
            segment_chars = len(segment.clean_text)
            if selected and total_chars + segment_chars > LIVE_RECALL_MAX_PROMPT_CHARS:
                break
            total_chars += segment_chars
            selected.append(segment)
        return selected

    def format_live_segments_for_prompt(self, meeting_code, segments):
        lines = []
        for segment in segments:
            label = self.format_live_source_label(meeting_code, segment)
            lines.append(f"[{label}] {segment.clean_text}")
        return "\n".join(lines)

    def format_live_source_summary(self, meeting_code, segments):
        labels = []
        seen = set()
        for segment in segments:
            label = self.format_live_source_label(meeting_code, segment)
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) >= 3:
                break
        return "; ".join(labels)

    def format_live_source_label(self, meeting_code, segment: TranscriptSegment):
        parts = [f"Meet {meeting_code}"]
        speaker = segment.speaker_name or segment.speaker_label
        if speaker:
            parts.append(speaker)
        timestamp = self.format_segment_time_range(segment)
        if timestamp:
            parts.append(timestamp)
        return " / ".join(parts)

    def format_segment_time_range(self, segment: TranscriptSegment):
        start = format_timestamp_ms(segment.start_ms)
        end = format_timestamp_ms(segment.end_ms)
        if start and end:
            return f"{start}-{end}"
        return start or end or ""

