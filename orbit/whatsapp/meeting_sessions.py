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


class MeetingSessionMixin:
    async def start_meeting_sessions(self, meet_links, from_number=None, profile_name=None):
        started = []
        duplicates = []
        rejected = []
        failed = []

        for meet_url in meet_links:
            start_result = await self.start_single_meeting_session(
                meet_url,
                from_number=from_number,
                profile_name=profile_name,
            )
            if start_result["status"] == "started":
                started.append(start_result["meeting_code"])
            elif start_result["status"] == "duplicate":
                duplicates.append(start_result["meeting_code"])
            elif start_result["status"] == "failed":
                reason = start_result.get("reason")
                failed.append(f"{start_result['meeting_code']}{f' ({reason})' if reason else ''}")
            else:
                rejected.append(start_result["meeting_code"])

        if started and not duplicates and not rejected:
            codes = ", ".join(started)
            return f"Starting Orbit for Google Meet: {codes}. I will send status updates here."

        parts = []
        if started:
            parts.append(f"Started: {', '.join(started)}.")
        if duplicates:
            parts.append(f"Already active: {', '.join(duplicates)}.")
        if rejected:
            parts.append(
                f"At capacity ({self.max_parallel_meetings} meetings), so I skipped: {', '.join(rejected)}."
            )
        if failed:
            parts.append(f"Could not start: {', '.join(failed)}.")
        return " ".join(parts)

    async def start_single_meeting_session(self, meet_url, from_number=None, profile_name=None):
        meeting_code = extract_meeting_code(meet_url)
        normalized_meeting_code = meeting_code.lower()

        async with self.lock: # prevents race conditions when multiple users start same meeting
            if any(active.state.meeting_code == meeting_code for active in self.active_sessions.values()):
                return {"status": "duplicate", "meeting_code": meeting_code}

            if normalized_meeting_code in self.pending_meeting_starts:
                return {"status": "duplicate", "meeting_code": meeting_code}

            if len(self.active_sessions) + len(self.pending_meeting_starts) >= self.max_parallel_meetings:
                return {"status": "capacity", "meeting_code": meeting_code}

            self.pending_meeting_starts.add(normalized_meeting_code)
            session_id = self.build_session_id(meeting_code)
        try:
            meeting_id, source_id = await self._create_meeting_record(meet_url, from_number, profile_name)
            from orbit import whatsapp_service as whatsapp_service_facade
            try:
                capture_session = await self.meeting_store.create_capture_session(
                    meeting_id,
                    source_id,
                    capture_strategy=whatsapp_service_facade.get_audio_capture_strategy(),
                    stt_provider="deepgram",
                )
                capture_session_id = capture_session.get("id") if isinstance(capture_session, dict) else None
                if not capture_session_id:
                    raise RuntimeError("Capture session create returned no id.")
            except Exception as error:
                log(f"Failed to create capture session for {meeting_id}: {error}", session_id, level="error")
                return {
                    "status": "failed",
                    "meeting_code": meeting_code,
                    "reason": "capture_session_create_failed",
                }
            config = self.build_session_config(meet_url, session_id, capture_session_id=capture_session_id)
            state = build_meeting_state(config)
            active = ActiveMeeting(
                session_id=session_id,
                meet_url=meet_url,
                state=state,
                meeting_id=meeting_id,
                source_id=source_id,
                capture_session_id=capture_session_id,
                created_at=now_iso(),
            )
            async with self.lock:
                self.pending_meeting_starts.discard(normalized_meeting_code)
                if any(active.state.meeting_code == meeting_code for active in self.active_sessions.values()):
                    return {"status": "duplicate", "meeting_code": meeting_code}
                if len(self.active_sessions) >= self.max_parallel_meetings:
                    return {"status": "capacity", "meeting_code": meeting_code}

                self.active_sessions[session_id] = active
                active.task = asyncio.create_task(self._run_session(active, config))

            return {"status": "started", "meeting_code": meeting_code}
        except Exception as error:
            log(
                f"Failed to create meeting persistence for {meeting_code}: {error}",
                session_id,
                level="error",
            )
            return {
                "status": "failed",
                "meeting_code": meeting_code,
                "reason": "meeting_record_create_failed",
            }
        finally:
            async with self.lock:
                self.pending_meeting_starts.discard(normalized_meeting_code)

    async def start_meeting_capture_session(
        self,
        meeting_id,
        meet_url,
        source_id=None,
        capture_session_id=None,
    ):
        if not meeting_id:
            return {"status": "invalid_input"}

        meeting_code = extract_meeting_code(meet_url)

        async with self.lock:
            if any(
                active.state.meeting_code == meeting_code or active.meeting_id == meeting_id
                for active in self.active_sessions.values()
            ):
                return {"status": "duplicate", "meeting_code": meeting_code}

            if len(self.active_sessions) >= self.max_parallel_meetings:
                return {"status": "capacity", "meeting_code": meeting_code}

            session_id = self.build_session_id(meeting_code)
            config = self.build_session_config(meet_url, session_id, capture_session_id=capture_session_id)
            state = build_meeting_state(config)
            active = ActiveMeeting(
                session_id=session_id,
                meet_url=meet_url,
                state=state,
                meeting_id=meeting_id,
                source_id=source_id,
                capture_session_id=capture_session_id,
                created_at=now_iso(),
            )
            # TODO: Replace this in-process task spawn with a durable queue/worker dispatch.
            self.active_sessions[session_id] = active
            active.task = asyncio.create_task(self._run_session(active, config))

            return {"status": "started", "meeting_code": meeting_code, "session_id": session_id}

    async def _create_meeting_record(self, meet_url, from_number, profile_name=None):
        if not from_number:
            raise ValueError("from_number is required to create meeting records.")

        store = self.meeting_store
        person_id = await store.find_or_create_person_by_phone(
            normalize_whatsapp_phone(from_number),
            name=profile_name,
        )
        if not person_id:
            raise RuntimeError("Failed to create or load person row for WhatsApp sender.")

        source_id = await store.create_source(
            "gmeet",
            url=meet_url,
        )
        if not source_id:
            raise RuntimeError("Failed to create source row.")

        meeting_id = await store.create_meeting(
            gmeet_url=meet_url,
            source_id=source_id,
            status="joining",
            requested_by_person_id=person_id,
        )
        if not meeting_id:
            raise RuntimeError("Failed to create meeting row.")
        return meeting_id, source_id

    async def _run_session(self, active, config):
        callbacks = MeetingSessionCallbacks(
            on_status=self.handle_session_status,
            on_chat_message=self.handle_chat_message,
            on_captions=self.handle_captions,
            on_orbit_mention=self.handle_orbit_mention,
            on_finished=self.handle_session_finished,
        )
        from orbit import whatsapp_service as whatsapp_service_facade

        active.state.audio_capture_strategy = (
            getattr(config, "audio_capture_strategy", None) or whatsapp_service_facade.get_audio_capture_strategy()
        )
        active.state.capture_session_id = active.capture_session_id
        if active.state.audio_capture_strategy == "server_audio_sink":
            active.state.audio_capture_routing_mode = "not_implemented"
            active.state.browser_audio_routed = False
            active.state.browser_process_isolated = True
            active.state.audio_sink_name = getattr(config, "audio_sink_name", None)
            config.capture_session_id = active.capture_session_id
        await self._update_capture_session_status(active, "starting")
        try:
            if (
                config.live_stt_enabled
                and active.state.audio_capture_strategy == "server_audio_sink"
            ):
                try:
                    await self._start_server_audio_sink_capture(active, config=config)
                except Exception as error:
                    error_message = self._safe_capture_error(error)
                    await self._mark_capture_session_failed(
                        active,
                        self._classify_server_audio_capture_error(error_message),
                        f"Could not start server-side audio sink capture. {error_message or 'See logs for details.'}",
                    )
                    active.state.live_stt_available = False
            from orbit import whatsapp_service as whatsapp_service_facade
            await whatsapp_service_facade.run_meeting_session(config, callbacks=callbacks, state=active.state)
        except asyncio.CancelledError:
            await self._mark_capture_session_failed(
                active,
                "CAPTURE_SESSION_CANCELLED",
                "Meeting capture session was cancelled before cleanup completed.",
            )
            raise
        except Exception:
            await self._mark_capture_session_failed(
                active,
                "CAPTURE_SESSION_FAILED",
                "Meeting capture session failed unexpectedly.",
            )
            raise
        finally:
            if active.state.audio_capture_strategy == "server_audio_sink":
                await self._update_capture_session_metadata(
                    active,
                    {
                        "audio_capture": {
                            "routing_mode": active.state.audio_capture_routing_mode,
                            "browser_audio_routed": active.state.browser_audio_routed,
                            "browser_process_isolated": active.state.browser_process_isolated,
                        }
                    },
                )
            await self._stop_server_audio_sink_capture(active)
            async with self.lock:
                self.active_sessions.pop(active.session_id, None)

    def build_session_id(self, meeting_code):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        return f"{meeting_code}-{timestamp}"

    def build_session_config(self, meet_url, session_id, capture_session_id=None):
        default_config = build_default_session_config(meet_url, session_id=session_id)
        return MeetingSessionConfig(
            session_id=session_id,
            meet_url=meet_url,
            display_name=default_config.display_name,
            wait_after_join_ms=default_config.wait_after_join_ms,
            max_steps=default_config.max_steps,
            model_name=default_config.model_name,
            capture_session_id=capture_session_id,
            audio_capture_strategy=default_config.audio_capture_strategy,
            live_stt_enabled=default_config.live_stt_enabled,
            audio_sink_name=default_config.audio_sink_name,
            audio_stream_ws_url=default_config.audio_stream_ws_url,
            audio_stream_token=default_config.audio_stream_token,
        )

    async def snapshot_active_meetings(self):
        async with self.lock:
            return list(self.active_sessions.values())

    async def resolve_active_meeting(self, meeting_code=None):
        active_meetings = await self.snapshot_active_meetings()
        if not active_meetings:
            return None, "Orbit is not monitoring an active meeting."

        if meeting_code:
            for active in active_meetings:
                if active.state.meeting_code.lower() == meeting_code.lower():
                    return active, None
            codes = ", ".join(active.state.meeting_code for active in active_meetings)
            return None, f"Meet {meeting_code} is not active. Active meeting(s): {codes}."

        if len(active_meetings) == 1:
            return active_meetings[0], None

        codes = ", ".join(active.state.meeting_code for active in active_meetings)
        return None, f"Multiple meetings are active. Send the meeting code to choose one: {codes}."

    async def format_active_meeting_status(self, meeting_code=None):
        active, error = await self.resolve_active_meeting(meeting_code)
        if error and (meeting_code or "Multiple" in error or "not monitoring" in error):
            if not meeting_code and "Multiple" in error:
                active_meetings = await self.snapshot_active_meetings()
            else:
                active_meetings = []
            if not active_meetings:
                return error
        else:
            active_meetings = [active] if active is not None else await self.snapshot_active_meetings()

        if not active_meetings:
            return "Orbit is not monitoring an active meeting."

        lines = ["Active Orbit meeting(s):"]
        for active_meeting in active_meetings:
            state = active_meeting.state
            stt_state = "started" if state.live_stt_started else "not started"
            if state.live_stt_requested and not state.live_stt_available:
                stt_state = "unavailable"
            elif not state.live_stt_requested:
                stt_state = "not requested"
            joined = state.joined_at or "not joined yet"
            lines.append(
                f"- {state.meeting_code}: {state.status}; joined: {joined}; "
                f"chat messages: {len(state.captured_messages)}; "
                f"STT: {stt_state}; transcript segments: {len(state.live_transcript_segments)}"
            )
        return "\n".join(lines)

    async def stop_active_meeting(self, meeting_code=None):
        active, error = await self.resolve_active_meeting(meeting_code)
        if error:
            return error

        state = active.state
        state.stop_requested = True
        state.stop_reason = "Orbit was asked from WhatsApp to stop monitoring this meeting."

        if active.task is None:
            async with self.lock:
                self.active_sessions.pop(active.session_id, None)
            return f"Orbit marked Meet {state.meeting_code} as stopped."

        try:
            await asyncio.wait_for(asyncio.shield(active.task), timeout=STOP_TIMEOUT_SECONDS)
            return f"Orbit stopped monitoring Meet {state.meeting_code} and completed cleanup."
        except asyncio.TimeoutError:
            active.task.cancel()
            try:
                await active.task
            except asyncio.CancelledError:
                pass
            return f"Orbit forced cleanup for Meet {state.meeting_code} after waiting {STOP_TIMEOUT_SECONDS} seconds."
        except Exception as error:
            return f"Orbit tried to stop Meet {state.meeting_code}, but cleanup failed: {error}"

    async def handle_session_status(self, state, status, detail):
        await self._update_capture_session_for_meeting_status(state, status)
        await self._update_persistent_meeting_status(state, status)

        if status == "starting_join":
            await self.send_whatsapp_message(
                f"Orbit is starting the join flow for Meet {state.meeting_code}."
            )
            return

        if status == "waiting_for_host":
            await self.send_whatsapp_message(
                f"Orbit is waiting for host approval for Meet {state.meeting_code}."
            )
            return

        if status == "joined":
            await self.send_whatsapp_message(
                f"Orbit joined Meet {state.meeting_code} and is monitoring the meeting chat."
            )
            return

        if status == "live_stt_capture_requested":
            await self.send_whatsapp_message(
                f"Orbit requested live audio transcription for Meet {state.meeting_code}. "
                "Waiting for the first audio chunk."
            )
            return

        if status == "live_stt_unavailable":
            await self.send_whatsapp_message(
                f"Orbit could not start live audio transcription for Meet {state.meeting_code}: {detail}"
            )
            return

        if status == "chat_monitor_unavailable":
            await self.send_whatsapp_message(
                f"Orbit joined Meet {state.meeting_code}, but it could not open the Meet chat panel."
            )
            return

        if status == "join_denied":
            await self.send_whatsapp_message(
                f"Google Meet denied Orbit's join request for {state.meeting_code}."
            )
            return

        if status == "join_blocked":
            await self.send_whatsapp_message(
                f"Google Meet blocked Orbit from joining {state.meeting_code}."
            )
            return

        if status == "join_unconfirmed":
            await self.send_whatsapp_message(
                f"Orbit could not confirm whether it joined Meet {state.meeting_code}."
            )
            return

        if status == "no_active_page":
            await self.send_whatsapp_message(
                f"Orbit lost the browser page while handling Meet {state.meeting_code}."
            )
            return

        if status == "error":
            await self.send_whatsapp_message(
                f"Orbit hit an error while handling Meet {state.meeting_code}: {detail}"
            )

    def _persistent_meeting_status(self, status, state):
        if state.joined_at and status == "error":
            return "live"
        if status in {"joined", "live_stt_capture_requested", "chat_monitor_unavailable", "live_stt_unavailable"}:
            return "live"
        if status in {
            "starting_join",
            "waiting_for_host",
            "join_denied",
            "join_blocked",
            "join_unconfirmed",
            "no_active_page",
        }:
            return "joining"
        if status == "error":
            return "failed"
        if state.joined_at:
            return "live"
        return None

    async def _update_persistent_meeting_status(self, state, status):
        active = self.active_sessions.get(state.session_id)
        if not active or not active.meeting_id:
            return
        meeting_status = self._persistent_meeting_status(status, state)
        if not meeting_status:
            return

        started_at = state.joined_at if meeting_status == "live" else None
        try:
            await self.meeting_store.update_meeting_status(
                active.meeting_id,
                meeting_status,
                started_at=started_at,
            )
        except Exception as error:
            log(
                f"Failed to update persistent meeting status for {active.meeting_id}: {error}",
                state.session_id,
                level="error",
            )

    async def handle_chat_message(self, state: MeetingState, message: ChatMessage, source: str):
        try:
            await self.memory.record_meeting_chat(state, message)
        except Exception as error:
            log(f"Memory write failed for Meet {state.meeting_code}: {error}", state.session_id, level="error")

    async def handle_captions(self, state: MeetingState, captions):
        try:
            await self.live_stt.add_captions(state, captions)
        except Exception as error:
            log(f"Caption attribution buffer failed for Meet {state.meeting_code}: {error}", state.session_id, level="error")

    async def handle_orbit_mention(self, state: MeetingState, message: ChatMessage):
        question = strip_qna_trigger(message.normalized_text)
        if not question:
            return "I’m here. Ask me a question after @orbit."

        recent_messages = [
            chat_message
            for chat_message in state.captured_messages[-15:]
            if chat_message.fingerprint != message.fingerprint
        ]
        context = "\n".join(
            f"{chat_message.author or 'unknown'}"
            f"{f' [{chat_message.timestamp_text}]' if chat_message.timestamp_text else ''}: "
            f"{chat_message.normalized_text}"
            for chat_message in recent_messages
        )

        prompt = (
            "Answer the in-meeting chat question briefly. Use the meeting chat context when relevant. "
            "If the chat context is not needed or is insufficient, answer as a general assistant. "
            "Keep the reply short enough for Google Meet chat.\n\n"
            f"Question:\n{question}\n\n"
            f"Recent meeting chat:\n{context or '(no prior chat captured)'}"
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Orbit inside a Google Meet chat. Reply concisely, helpfully, "
                            "and do not claim access to audio or transcript content."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as error:
            log(f"Meet chat mention answer failed: {error}", state.session_id, level="error")
            return "I’m here, but I could not generate an answer right now."

        content = response.choices[0].message.content if response.choices else ""
        return (content or "").strip() or "I’m here."
