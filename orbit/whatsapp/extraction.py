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


class MeetingExtractionMixin:
    async def runMeetingExtraction(self, payload: dict):
        if not isinstance(payload, dict):
            raise TypeError("runMeetingExtraction expects a payload dict.")

        return await self.run_meeting_extraction(
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            source_id=payload.get("sourceId") or payload.get("source_id"),
            run_type=payload.get("runType") or payload.get("run_type", MEETING_EXTRACTION_RUN_TYPE),
            model=payload.get("model") or self.model_name,
            prompt_version=payload.get("promptVersion") or payload.get("prompt_version", MEETING_EXTRACTION_PROMPT_VERSION),
            summary_short=payload.get("summary_short"),
            summary_long=payload.get("summary_long"),
            started_at=payload.get("started_at"),
            ended_at=payload.get("ended_at"),
            skip_status_updates=payload.get("skip_status_updates", False),
        )

    async def run_meeting_extraction(
        self,
        meeting_id: str,
        source_id: str,
        *,
        run_type: str = MEETING_EXTRACTION_RUN_TYPE,
        model: str | None = None,
        prompt_version: str = MEETING_EXTRACTION_PROMPT_VERSION,
        summary_short: str | None = None,
        summary_long: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        skip_status_updates: bool = False,
    ) -> dict:
        if not meeting_id:
            raise ValueError("meetingId is required for extraction.")
        if not source_id:
            raise ValueError("sourceId is required for extraction.")

        store = self.meeting_store

        if not skip_status_updates:
            await store.update_meeting_status(
                meeting_id,
                "processing",
                ended_at=ended_at,
                started_at=started_at,
                summary_short=summary_short,
                summary_long=summary_long,
            )

        try:
            log(
                f"evt=extraction.start meeting_id={meeting_id} source_id={source_id} "
                f"run_type={run_type} model={model}",
                meeting_id,
                level="important",
            )
            chunks = await store.get_source_chunks_by_source_id(source_id) or []
            log(
                f"evt=extraction.source_chunks_loaded source_id={source_id} count={len(chunks)}",
                meeting_id,
                level="important",
            )

            get_visual_frames = getattr(store, "get_visual_frames_by_meeting_id", None)
            visual_frames = await get_visual_frames(meeting_id) if callable(get_visual_frames) else []
            transcript = self._build_transcript_text(chunks)
            visual_evidence = self._build_visual_evidence_text(visual_frames)
            meeting_evidence = "\n".join(
                section for section in (transcript, visual_evidence) if section
            )
            if not meeting_evidence:
                output_json = self._empty_extraction_output()
                decisions = output_json.get("decisions")
                action_items = output_json.get("action_items")
                memories = output_json.get("durable_memories") or output_json.get("durableMemories")
                self._log_extraction_payload(
                    meeting_id,
                    source_id,
                    decisions=decisions,
                    action_items=action_items,
                    memories=memories,
                )
                extraction_run_id = await store.create_extraction_run(
                    source_id=source_id,
                    meeting_id=meeting_id,
                    run_type=run_type,
                    model=model or self.model_name,
                    prompt_version=prompt_version,
                    output_json=output_json,
                    status="success",
                    error=None,
                )
                decisions_inserted = await store.createDecisionsFromExtraction(
                    meeting_id=meeting_id,
                    source_id=source_id,
                    decisions=decisions,
                )
                action_items_inserted = await store.createActionItemsFromExtraction(
                    meeting_id=meeting_id,
                    source_id=source_id,
                    action_items=action_items,
                )
                memories_inserted = await store.createMemoriesFromExtraction(
                    meeting_id=meeting_id,
                    source_id=source_id,
                    memories=memories,
                )
                log(
                    f"evt=extraction.stored run_id={extraction_run_id} "
                    f"decisions={decisions_inserted} action_items={action_items_inserted} "
                    f"memories={memories_inserted}",
                    meeting_id,
                    level="important",
                )
                if not skip_status_updates:
                    await store.update_meeting_status(
                        meeting_id,
                        "processed",
                        ended_at=ended_at,
                        started_at=started_at,
                        summary_short=summary_short,
                        summary_long=summary_long,
                    )
                log(
                    f"evt=extraction.finished meeting_id={meeting_id} source_id={source_id} status=success",
                    meeting_id,
                    level="important",
                )
                return {
                    "extraction_run_id": extraction_run_id,
                    "status": "success",
                    "output_json": output_json,
                    "decisions_inserted": decisions_inserted,
                    "action_items_inserted": action_items_inserted,
                    "memories_inserted": memories_inserted,
                }

            extraction_prompt = MEETING_EXTRACT_PROMPT.format(transcript=meeting_evidence)
            log(
                f"evt=extraction.prompt_prepared meeting_id={meeting_id} source_id={source_id} prompt_length={len(extraction_prompt)}",
                meeting_id,
                level="important",
            )
            response = await self.openai_client.chat.completions.create(
                model=model or self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": MEETING_EXTRACT_PROMPT.split("Meeting evidence:")[0].strip(),
                    },
                    {"role": "user", "content": extraction_prompt},
                ],
            )
            raw_output = (response.choices[0].message.content or "").strip() if response.choices else ""
            log(
                f"evt=extraction.raw_llm_output meeting_id={meeting_id} source_id={source_id} chars={len(raw_output)}",
                meeting_id,
                level="important",
            )
            output_json = self._parse_extraction_json(raw_output)
            output_json = self._normalize_extraction_output(output_json)
            decisions = output_json.get("decisions") or []
            action_items = output_json.get("action_items") or []
            memories = output_json.get("durable_memories") or output_json.get("durableMemories") or []
            self._log_extraction_payload(
                meeting_id,
                source_id,
                decisions=decisions,
                action_items=action_items,
                memories=memories,
            )
            extraction_run_id = await store.create_extraction_run(
                source_id=source_id,
                meeting_id=meeting_id,
                run_type=run_type,
                model=model or self.model_name,
                prompt_version=prompt_version,
                output_json=output_json,
                status="success",
                error=None,
            )
            decisions_inserted = await store.createDecisionsFromExtraction(
                meeting_id=meeting_id,
                source_id=source_id,
                decisions=decisions,
            )
            action_items_inserted = await store.createActionItemsFromExtraction(
                meeting_id=meeting_id,
                source_id=source_id,
                action_items=action_items,
            )
            memories_inserted = await store.createMemoriesFromExtraction(
                meeting_id=meeting_id,
                source_id=source_id,
                memories=memories,
            )
            log(
                f"evt=extraction.stored run_id={extraction_run_id} "
                f"decisions={decisions_inserted} action_items={action_items_inserted} "
                f"memories={memories_inserted}",
                meeting_id,
                level="important",
            )

            if not skip_status_updates:
                await store.update_meeting_status(
                    meeting_id,
                    "processed",
                    ended_at=ended_at,
                    started_at=started_at,
                    summary_short=summary_short,
                    summary_long=summary_long,
                )
            log(
                f"evt=extraction.finished meeting_id={meeting_id} source_id={source_id} status=success",
                meeting_id,
                level="important",
            )
            return {
                "extraction_run_id": extraction_run_id,
                "status": "success",
                "output_json": output_json,
                "decisions_inserted": decisions_inserted,
                "action_items_inserted": action_items_inserted,
                "memories_inserted": memories_inserted,
            }
        except Exception as error:
            error_message = str(error)
            log(
                f"evt=extraction.failed meeting_id={meeting_id} source_id={source_id} error={error_message[:180]}",
                meeting_id,
                level="error",
            )
            try:
                await store.create_extraction_run(
                    source_id=source_id,
                    meeting_id=meeting_id,
                    run_type=run_type,
                    model=model or self.model_name,
                    prompt_version=prompt_version,
                    output_json=None,
                    status="failed",
                    error=error_message,
                )
            except Exception as nested_error:
                log(
                    f"Failed to save extraction failure row for {meeting_id}: {nested_error}",
                    session_id=meeting_id,
                    level="error",
                )

            if not skip_status_updates:
                try:
                    await store.update_meeting_status(
                        meeting_id,
                        "failed",
                        ended_at=ended_at,
                        started_at=started_at,
                        summary_short=summary_short,
                        summary_long=summary_long,
                    )
                except Exception as nested_error:
                    log(
                        f"Failed to mark meeting as failed for {meeting_id}: {nested_error}",
                        session_id=meeting_id,
                        level="error",
                    )
            return {"extraction_run_id": None, "status": "failed", "error": error_message}

    def _build_transcript_text(self, chunks):
        lines = []
        for chunk in chunks or []:
            if not isinstance(chunk, dict):
                continue
            text = (chunk.get("text") or "").strip()
            if not text:
                continue
            speaker = (chunk.get("speaker_label") or "Unknown") or "Unknown"
            timestamp = format_timestamp_ms(chunk.get("start_ms"))
            prefix = f"[Transcript {timestamp}] " if timestamp else "[Transcript] "
            lines.append(f"{prefix}{speaker}: {text}")
        return "\n".join(lines)

    def _build_visual_evidence_text(self, frames):
        lines = []
        for frame in frames or []:
            if not isinstance(frame, dict):
                continue
            summary = str(frame.get("summary") or "").strip()
            if not summary:
                continue
            timestamp = format_timestamp_ms(frame.get("captured_at_ms"))
            label = f"Visual {timestamp}" if timestamp else "Visual"
            lines.append(f"[{label}] {summary}")
        return "\n".join(lines)

    def _parse_extraction_json(self, raw_output: str):
        if not raw_output:
            raise ValueError("Empty extraction output.")

        trimmed = raw_output.strip()
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            pass

        if trimmed.startswith("```"):
            trimmed = trimmed.strip("`")
            if not trimmed:
                raise ValueError("Extraction output was wrapped in an empty markdown block.")

        brace_start = trimmed.find("{")
        brace_end = trimmed.rfind("}")
        if brace_start == -1 or brace_end <= brace_start:
            raise ValueError("Could not locate JSON object in extraction output.")

        candidate = trimmed[brace_start : brace_end + 1]
        return json.loads(candidate)

    @staticmethod
    def _log_extraction_payload(
        meeting_id,
        source_id,
        *,
        decisions,
        action_items,
        memories,
    ):
        extracted_decisions = MeetingExtractionMixin._coerce_output_list(decisions)
        extracted_action_items = MeetingExtractionMixin._coerce_output_list(action_items)
        extracted_memories = MeetingExtractionMixin._coerce_output_list(memories)
        log(
            f"evt=extraction.payload meeting_id={meeting_id} source_id={source_id} "
            f"decisions={len(extracted_decisions)} action_items={len(extracted_action_items)} "
            f"memories={len(extracted_memories)}",
            meeting_id,
            level="important",
        )
        log(
            f"evt=extraction.decisions sample={MeetingExtractionMixin._preview_list(extracted_decisions)}",
            meeting_id,
            level="important",
        )
        log(
            f"evt=extraction.action_items sample={MeetingExtractionMixin._preview_list(extracted_action_items)}",
            meeting_id,
            level="important",
        )
        log(
            f"evt=extraction.memories sample={MeetingExtractionMixin._preview_list(extracted_memories)}",
            meeting_id,
            level="important",
        )

    @staticmethod
    def _preview_list(values, max_items=3, max_chars=140):
        normalized = MeetingExtractionMixin._coerce_output_list(values)
        if not normalized:
            return "[]"

        compact = []
        for value in normalized[:max_items]:
            compact.append(MeetingExtractionMixin._preview_value(value, max_chars=max_chars))

        if len(normalized) > max_items:
            compact.append("...")
        return f"[{'; '.join(compact)}]"

    @staticmethod
    def _preview_value(value, max_chars=140):
        if isinstance(value, str):
            return MeetingExtractionMixin._truncate(value, max_chars=max_chars)

        if isinstance(value, dict):
            text = (
                value.get("text")
                or value.get("item")
                or value.get("description")
                or value.get("title")
                or ""
            )
            if text:
                return MeetingExtractionMixin._truncate(str(text), max_chars=max_chars)

        rendered = str(value)
        return MeetingExtractionMixin._truncate(rendered, max_chars=max_chars)

    @staticmethod
    def _truncate(text, max_chars=140):
        if not text:
            return ""
        clean_text = str(text).replace("\n", " ").strip()
        if len(clean_text) <= max_chars:
            return clean_text
        return f"{clean_text[: max_chars - 3]}..."

    @staticmethod
    def _coerce_output_list(value):
        return value if isinstance(value, list) else []

    @staticmethod
    def _normalize_extraction_output(value):
        if not isinstance(value, dict):
            raise ValueError("Extraction output is not a JSON object.")

        return {
            "summary_short": str(value.get("summary_short", "")) if value.get("summary_short") is not None else "",
            "summary_long": str(value.get("summary_long", "")) if value.get("summary_long") is not None else "",
            "decisions": MeetingExtractionMixin._coerce_output_list(value.get("decisions")),
            "action_items": MeetingExtractionMixin._coerce_output_list(value.get("action_items")),
            "risks": MeetingExtractionMixin._coerce_output_list(value.get("risks")),
            "open_questions": MeetingExtractionMixin._coerce_output_list(value.get("open_questions")),
            "durable_memories": MeetingExtractionMixin._coerce_output_list(
                value.get("durable_memories")
                if "durable_memories" in value
                else value.get("durableMemories"),
            ),
        }

    @staticmethod
    def _empty_extraction_output():
        return {
            "summary_short": "",
            "summary_long": "",
            "decisions": [],
            "action_items": [],
            "risks": [],
            "open_questions": [],
            "durable_memories": [],
        }

    async def handle_session_finished(self, state):
        active = self.active_sessions.get(state.session_id)
        await self.finish_visual_frame_analysis(active)
        try:
            await self.live_stt.stop(state.session_id)
        except Exception as error:
            await self._mark_capture_session_failed(
                active,
                "LIVE_STT_STOP_FAILED",
                "Live transcription cleanup failed.",
            )
            log(f"Live STT cleanup failed for Meet {state.meeting_code}: {error}", state.session_id, level="error")
        await self._classify_ending_audio_health(active, state)
        if not state.joined_at:
            await self._mark_capture_session_failed(
                active,
                "CAPTURE_NOT_ADMITTED",
                "Meeting capture ended before Orbit was admitted to Google Meet.",
            )
        await self._finalize_persistent_meeting(state)
        try:
            await self.memory.finalize_meeting(state)
        except Exception as error:
            log(f"Memory indexing failed for Meet {state.meeting_code}: {error}", state.session_id, level="error")

        if state.joined_at:
            if state.stop_requested:
                return
            live_stt_summary = ""
            if state.live_stt_requested and not state.live_stt_started:
                live_stt_summary = " Live audio transcription did not start because no audio chunk was received."
            leave_summary = f" {state.leave_reason}" if state.leave_reason else ""
            await self.send_whatsapp_message(
                f"Orbit finished Meet {state.meeting_code}. Captured {len(state.captured_messages)} chat message(s)."
                f"{live_stt_summary}"
                f"{leave_summary}"
            )
            return

        if state.status == "waiting_for_host":
            await self.send_whatsapp_message(
                f"Orbit stopped waiting for Meet {state.meeting_code} without being admitted."
            )

    async def _classify_ending_audio_health(self, active, state):
        if not active or not state.joined_at or not state.live_stt_requested:
            return
        audio = self._audio_health(active)
        deepgram = active.capture_health_metadata["deepgram"]
        if int(audio.get("chunk_count") or 0) == 0:
            await self._mark_capture_session_failed(
                active,
                "NO_AUDIO_CHUNKS_RECEIVED",
                "No audio chunks were received before the meeting capture ended.",
            )
            return
        if int(audio.get("speech_chunk_count") or 0) == 0:
            await self._mark_capture_session_failed(
                active,
                "AUDIO_ONLY_SILENCE",
                "Only silent audio was received before the meeting capture ended.",
            )
            return
        transcript_count = (
            int(deepgram.get("final_transcript_count") or 0)
            + int(deepgram.get("interim_transcript_count") or 0)
        )
        if transcript_count == 0:
            await self._mark_capture_session_failed(
                active,
                "NO_TRANSCRIPT_RECEIVED",
                "No Deepgram transcript results were received before the meeting capture ended.",
            )

    async def _finalize_persistent_meeting(self, state):
        active = self.active_sessions.get(state.session_id)
        if not active or not active.meeting_id:
            return

        summary_short, summary_long = self._build_meeting_summary(state)
        ended_at = state.finished_at or now_iso()
        final_summary_short = summary_short
        final_summary_long = summary_long
        track_capture_finalization = bool(
            active.capture_session_id
            and state.joined_at
            and not state.last_error
            and not active.capture_failure_recorded
        )
        try:
            if track_capture_finalization:
                await self._update_capture_session_status(active, "processing")
            await self.meeting_store.update_meeting_status(
                active.meeting_id,
                "processing",
                ended_at=ended_at,
                started_at=state.joined_at,
                summary_short=summary_short,
                summary_long=summary_long,
            )
            chunks = self._build_transcript_source_chunks(state)
            if chunks:
                await self.meeting_store.save_transcript_chunks(active.source_id, chunks)
            extraction = await self.run_meeting_extraction(
                active.meeting_id,
                active.source_id,
                summary_short=summary_short,
                summary_long=summary_long,
                started_at=state.joined_at,
                ended_at=ended_at,
                skip_status_updates=True,
            )
            extraction_output = extraction.get("output_json") if isinstance(extraction, dict) else None
            if isinstance(extraction_output, dict):
                extracted_summary_short = extraction_output.get("summary_short")
                extracted_summary_long = extraction_output.get("summary_long")
                if isinstance(extracted_summary_short, str) and extracted_summary_short.strip():
                    final_summary_short = extracted_summary_short.strip()
                if isinstance(extracted_summary_long, str) and extracted_summary_long.strip():
                    final_summary_long = extracted_summary_long.strip()

            if extraction.get("status") == "failed":
                if track_capture_finalization:
                    await self._mark_capture_session_failed(
                    active,
                    "MEETING_EXTRACTION_FAILED",
                    "Meeting capture extraction failed.",
                )
                await self.meeting_store.update_meeting_status(
                    active.meeting_id,
                    "failed",
                    ended_at=ended_at,
                    started_at=state.joined_at,
                    summary_short=final_summary_short,
                    summary_long=final_summary_long,
                    overwrite_summary=True,
                )
                return

            if final_summary_short != summary_short or final_summary_long != summary_long:
                await self.meeting_store.update_meeting_status(
                    active.meeting_id,
                    "processing",
                    ended_at=ended_at,
                    started_at=state.joined_at,
                    summary_short=final_summary_short,
                    summary_long=final_summary_long,
                    overwrite_summary=True,
                )

            await self.meeting_store.update_meeting_status(
                active.meeting_id,
                "processed",
                ended_at=ended_at,
                started_at=state.joined_at,
                summary_short=final_summary_short,
                summary_long=final_summary_long,
                overwrite_summary=True,
            )
            if track_capture_finalization:
                await self._mark_capture_session_finished(active)
        except Exception as error:
            log(
                f"Failed to mark meeting as processed for {active.meeting_id}: {error}",
                state.session_id,
            )
            if track_capture_finalization:
                await self._mark_capture_session_failed(
                    active,
                    "CAPTURE_FINALIZATION_FAILED",
                    "Meeting capture finalization failed.",
                )
            try:
                await self.meeting_store.update_meeting_status(
                    active.meeting_id,
                    "failed",
                    ended_at=ended_at,
                    started_at=state.joined_at,
                    summary_short=final_summary_short,
                    summary_long=final_summary_long,
                    overwrite_summary=True,
                )
            except Exception as failed_error:
                log(
                    f"Failed to mark meeting as failed for {active.meeting_id}: {failed_error}",
                    state.session_id,
                )

    def _build_transcript_source_chunks(self, state):
        chunks = []
        for segment in state.live_transcript_segments:
            text = (segment.clean_text or segment.raw_text or "").strip()
            if not text:
                continue

            chunks.append(
                {
                    "speakerLabel": segment.speaker_label or segment.speaker_name,
                    "startMs": segment.start_ms,
                    "endMs": segment.end_ms,
                    "text": text,
                    "metadata": {
                        "source_type": segment.source_type,
                        "speaker_name": segment.speaker_name,
                        "speaker_source": segment.speaker_source,
                        "memory_text": segment.memory_text,
                    },
                }
            )
        return chunks

    def _build_meeting_summary(self, state):
        parts = []
        if state.live_stt_requested:
            parts.append("live STT requested")
        if state.captured_messages:
            parts.append(f"{len(state.captured_messages)} chat messages captured")
        if state.live_transcript_segments:
            parts.append(f"{len(state.live_transcript_segments)} transcript segments captured")
        summary_short = "; ".join(parts) if parts else None
        summary_long = None
        if state.live_transcript_segments:
            summary_long = " | ".join(
                segment.clean_text.strip()
                for segment in state.live_transcript_segments
                if segment.clean_text
            )
            if summary_long and len(summary_long) > 4000:
                summary_long = summary_long[:4000]
        return summary_short, summary_long
