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


class AudioStreamMixin:
    @staticmethod
    def _get_ffmpeg_pid(handle):
        process = getattr(handle, "ffmpeg_process", None)
        return getattr(process, "pid", None)

    def _classify_server_audio_capture_error(self, error_message):
        normalized = (error_message or "").lower()
        if "pactl" in normalized or "load-module" in normalized or "sink" in normalized:
            return AUDIO_SINK_CREATE_ERROR_CODE
        return FFMPEG_START_ERROR_CODE

    async def _start_server_audio_sink_capture(self, active, config=None):
        if active.server_audio_sink_handle is not None:
            return
        if not active.capture_session_id:
            active.state.live_stt_available = False
            return
        from orbit import whatsapp_service as whatsapp_service_facade
        handle = await whatsapp_service_facade.start_server_audio_sink_capture(
            active.session_id,
            active.capture_session_id,
        )
        if not handle:
            active.state.live_stt_available = False
            return
        active.server_audio_sink_handle = handle
        if config is not None:
            setattr(config, "audio_capture_strategy", "server_audio_sink")
            setattr(config, "audio_sink_name", handle.sink_name)
        active.state.live_stt_available = True
        now = now_iso()
        metadata = {
            "audio_capture": {
                "strategy": "server_audio_sink",
                "sink_name": handle.sink_name,
                "ffmpeg_pid": self._get_ffmpeg_pid(handle),
                "routing_mode": active.state.audio_capture_routing_mode,
                "browser_audio_routed": active.state.browser_audio_routed,
                "browser_process_isolated": active.state.browser_process_isolated,
                "started_at": now,
                "stopped_at": None,
                "error": None,
            }
        }
        await self._update_capture_session_metadata(active, metadata)
        if getattr(handle, "ffmpeg_process", None) is None:
            return
        active.server_audio_reader_task = asyncio.create_task(
            self._run_server_audio_sink_reader(active),
        )

    async def _run_server_audio_sink_reader(self, active):
        handle = active.server_audio_sink_handle if active else None
        if not handle:
            return
        process = getattr(handle, "ffmpeg_process", None)
        if not process:
            return
        stdout = getattr(process, "stdout", None)
        if not stdout:
            return
        saw_forwarded_audio = False
        ffmpeg_audio_format = LiveAudioFormat()
        try:
            while True:
                chunk = await stdout.read(4096)
                if not chunk:
                    break
                was_forwarded = await self._forward_audio_chunk_for_session(
                    active,
                    chunk,
                    ffmpeg_audio_format,
                )
                saw_forwarded_audio = saw_forwarded_audio or was_forwarded
            return_code = process.returncode
            if return_code is None:
                return_code = await process.wait()
            if not saw_forwarded_audio and not active.capture_failure_recorded:
                await self._mark_capture_session_failed(
                    active,
                    NO_AUDIO_FROM_SINK_ERROR_CODE,
                    FFMPEG_STREAM_EXITED_WITHOUT_CHUNKS,
                    metadata={"audio_capture": {"ffmpeg_exit_code": return_code}},
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not active.capture_failure_recorded:
                await self._mark_capture_session_failed(
                    active,
                    FFMPEG_STREAM_ENDED_ERROR_CODE,
                    f"Server-side audio reader failed: {self._safe_capture_error(error)}",
                )

    async def _stop_server_audio_sink_capture(self, active):
        task = active.server_audio_reader_task if active else None
        active.server_audio_reader_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                log(
                    f"Server audio reader cleanup failed for {active.session_id}: {error}",
                    active.session_id,
                    level="error",
                )

        handle = active.server_audio_sink_handle if active else None
        if handle is None:
            return
        active.server_audio_sink_handle = None
        try:
            await handle.stop()
        except Exception as error:
            log(
                f"Server audio sink cleanup failed for {active.session_id}: {error}",
                active.session_id,
                level="error",
            )
        await self._update_capture_session_metadata(
            active,
            {"audio_capture": {"stopped_at": now_iso()}},
        )

    async def _update_capture_session_status(self, active, status, metadata=None):
        if not active or not active.capture_session_id:
            return None
        if active.capture_failure_recorded:
            return None
        if metadata:
            active.capture_health_metadata = merge_capture_session_metadata(
                active.capture_health_metadata,
                metadata,
            )
        try:
            return await self.meeting_store.update_capture_session_status(active.capture_session_id, status, metadata=metadata)
        except Exception as error:
            log(
                f"Failed to update capture session {active.capture_session_id} to {status}: {error}",
                active.session_id,
                level="error",
            )
            return None

    async def _mark_capture_session_failed(self, active, error_code, error_message, metadata=None):
        if not active or not active.capture_session_id:
            return None
        if active.capture_failure_recorded:
            return None
        active.capture_failure_recorded = True
        if metadata:
            active.capture_health_metadata = merge_capture_session_metadata(
                active.capture_health_metadata,
                metadata,
            )
        try:
            return await self.meeting_store.mark_capture_session_failed(
                active.capture_session_id,
                error_code,
                error_message,
                metadata=metadata,
            )
        except Exception as error:
            log(
                f"Failed to mark capture session {active.capture_session_id} as failed: {error}",
                active.session_id,
                level="error",
            )
            return None

    async def _update_capture_session_metadata(self, active, patch):
        if not active or not isinstance(patch, dict):
            return None
        active.capture_health_metadata = merge_capture_session_metadata(
            active.capture_health_metadata,
            patch,
        )
        if not active.capture_session_id:
            return None
        try:
            return await self.meeting_store.update_capture_session_metadata(active.capture_session_id, patch)
        except Exception as error:
            log(
                f"Failed to update capture session metadata {active.capture_session_id}: {error}",
                active.session_id,
                level="error",
            )
            return None

    async def _mark_capture_session_finished(self, active):
        if not active or not active.capture_session_id:
            return None
        if active.capture_failure_recorded:
            return None
        try:
            return await self.meeting_store.mark_capture_session_finished(active.capture_session_id)
        except Exception as error:
            log(
                f"Failed to mark capture session {active.capture_session_id} as processed: {error}",
                active.session_id,
                level="error",
            )
            return None

    async def _heartbeat_capture_session(self, active):
        if not active or not active.capture_session_id:
            return
        now = asyncio.get_running_loop().time()
        if (
            active.last_capture_heartbeat_at
            and now - active.last_capture_heartbeat_at < CAPTURE_HEARTBEAT_INTERVAL_SECONDS
        ):
            return
        try:
            await self.meeting_store.heartbeat_capture_session(active.capture_session_id)
            active.last_capture_heartbeat_at = now
        except Exception as error:
            log(
                f"Failed to heartbeat capture session {active.capture_session_id}: {error}",
                active.session_id,
                level="error",
            )

    async def _handle_live_stt_health_event(self, state, event, details):
        active = self.active_sessions.get(state.session_id)
        if not active:
            return

        timestamp = now_iso()
        deepgram = active.capture_health_metadata["deepgram"]
        patch = {"deepgram": {}}
        update = patch["deepgram"]
        failure = None

        if event == "connect_started":
            update["connect_started_at"] = timestamp
        elif event == "connected":
            update["connected_at"] = timestamp
        elif event == "connection_closed":
            update.update(
                {
                    "connection_closed_at": timestamp,
                    "close_code": details.get("close_code"),
                    "close_reason": self._safe_capture_error(details.get("close_reason")),
                }
            )
        elif event == "connect_failed":
            update["error"] = self._safe_capture_error(details.get("error"))
            failure = ("DEEPGRAM_CONNECT_FAILED", "Deepgram live transcription could not connect.")
        elif event in {"stream_closed", "stream_error"}:
            update.update(
                {
                    "connection_closed_at": timestamp,
                    "close_code": details.get("close_code"),
                    "close_reason": self._safe_capture_error(details.get("close_reason")),
                    "error": self._safe_capture_error(details.get("error")),
                }
            )
            failure = ("DEEPGRAM_STREAM_CLOSED", "Deepgram live transcription closed unexpectedly.")
        elif event == "transcript":
            update["last_transcript_at"] = timestamp
            if not deepgram.get("first_transcript_at"):
                update["first_transcript_at"] = timestamp
            counter = "final_transcript_count" if details.get("is_final") else "interim_transcript_count"
            update[counter] = int(deepgram.get(counter) or 0) + 1
        elif event == "keepalive":
            update["keepalive_count"] = int(deepgram.get("keepalive_count") or 0) + 1
            update["last_keepalive_at"] = timestamp
        elif event == "keepalive_failed":
            update["error"] = self._safe_capture_error(details.get("error"))
            failure = ("DEEPGRAM_KEEPALIVE_FAILED", "Deepgram live transcription KeepAlive failed.")
        else:
            return

        if failure:
            await self._mark_capture_session_failed(active, failure[0], failure[1], metadata=patch)
            return
        await self._update_capture_session_metadata(active, patch)

    @staticmethod
    def _safe_capture_error(value):
        text = str(value or "").strip()
        return text[:500] or None

    @staticmethod
    def _audio_health(active):
        return active.capture_health_metadata["audio"]

    def _record_audio_chunk_received(self, active, chunk_size):
        audio = self._audio_health(active)
        timestamp = now_iso()
        if not audio.get("first_chunk_at"):
            audio["first_chunk_at"] = timestamp
        audio["last_chunk_at"] = timestamp
        audio["chunk_count"] = int(audio.get("chunk_count") or 0) + 1
        audio["bytes_received"] = int(audio.get("bytes_received") or 0) + chunk_size
        audio["last_chunk_size_bytes"] = chunk_size
        audio["streaming_started"] = True
        active.audio_chunks_since_metadata_flush += 1

    def _record_audio_chunk_forwarded(self, active, chunk_size):
        audio = self._audio_health(active)
        audio["bytes_forwarded_to_stt"] = int(audio.get("bytes_forwarded_to_stt") or 0) + chunk_size

    def _record_audio_classification(self, active, result):
        audio = self._audio_health(active)
        timestamp = now_iso()
        audio["last_rms"] = round(result.rms, 2)
        audio["silence_gated"] = result.silence_gated
        if result.is_silent:
            audio["silent_chunk_count"] = int(audio.get("silent_chunk_count") or 0) + 1
            audio["silent_or_empty_chunk_count"] = int(audio.get("silent_or_empty_chunk_count") or 0) + 1
            audio["last_silence_at"] = timestamp
        else:
            audio["speech_chunk_count"] = int(audio.get("speech_chunk_count") or 0) + 1
            audio["last_speech_at"] = timestamp
        if result.dropped_silence_bytes:
            audio["bytes_dropped_silence"] = (
                int(audio.get("bytes_dropped_silence") or 0) + result.dropped_silence_bytes
            )

    def _record_empty_audio_chunk(self, active):
        audio = self._audio_health(active)
        audio["silent_or_empty_chunk_count"] = int(audio.get("silent_or_empty_chunk_count") or 0) + 1
        active.audio_chunks_since_metadata_flush += 1

    async def _forward_audio_chunk_for_session(
        self,
        active,
        chunk: bytes,
        audio_format: LiveAudioFormat | None = None,
    ) -> bool:
        if not active or not chunk:
            self._record_empty_audio_chunk(active)
            await self._flush_capture_audio_health(active)
            return False

        self._record_audio_chunk_received(active, len(chunk))
        gate = self._get_or_create_audio_silence_gate(active, audio_format)
        gate_result = gate.process(chunk)
        self._record_audio_classification(active, gate_result)

        session = await self._get_or_create_live_stt_session(active, audio_format)
        for forwarded_chunk in gate_result.chunks_to_forward:
            await session.send_audio(forwarded_chunk)
            self._record_audio_chunk_forwarded(active, len(forwarded_chunk))

        if gate_result.chunks_to_forward and not active.state.live_stt_started:
            active.state.live_stt_started = True
            active.state.live_stt_audio_confirmed_at = now_iso()
            active.state.live_stt_status_detail = (
                "Deepgram stream connected and first audio chunk forwarded."
            )
            await self.send_whatsapp_message(
                f"Orbit confirmed live audio transcription for Meet "
                f"{active.state.meeting_code}."
            )
            await self._update_capture_session_status(
                active,
                "streaming_audio",
                metadata={"audio": dict(self._audio_health(active))},
            )
            active.audio_chunks_since_metadata_flush = 0
            active.last_capture_metadata_flush_at = asyncio.get_running_loop().time()
            active.last_capture_heartbeat_at = asyncio.get_running_loop().time()
        else:
            await self._flush_capture_audio_health(active)
            await self._heartbeat_capture_session(active)

        if gate_result.silence_gated:
            await self._send_deepgram_keepalive_if_due(active, session)
        return bool(gate_result.chunks_to_forward)

    async def _get_or_create_live_stt_session(self, active, audio_format=None):
        if active.live_stt_session is None:
            active.live_stt_session = await self.live_stt.get_or_create(
                active.state,
                audio_format,
            )
        return active.live_stt_session

    def _get_or_create_audio_silence_gate(self, active, audio_format=None):
        if active.audio_silence_gate is None:
            sample_rate = audio_format.sample_rate if audio_format else 16000
            active.audio_silence_gate = PCM16SilenceGate(
                sample_rate=sample_rate,
                rms_threshold=env_int(
                    "ORBIT_AUDIO_SILENCE_RMS_THRESHOLD",
                    DEFAULT_SILENCE_RMS_THRESHOLD,
                ),
                pre_roll_ms=env_int("ORBIT_AUDIO_PRE_ROLL_MS", DEFAULT_PRE_ROLL_MS),
                post_roll_ms=env_int("ORBIT_AUDIO_POST_ROLL_MS", DEFAULT_POST_ROLL_MS),
                silence_drop_after_ms=env_int(
                    "ORBIT_AUDIO_SILENCE_DROP_AFTER_MS",
                    DEFAULT_SILENCE_DROP_AFTER_MS,
                ),
            )
            audio = self._audio_health(active)
            audio["silence_gate_enabled"] = True
            audio["silence_rms_threshold"] = active.audio_silence_gate.rms_threshold
        return active.audio_silence_gate

    async def _send_deepgram_keepalive_if_due(self, active, session):
        if session is None:
            return
        now = asyncio.get_running_loop().time()
        if (
            active.last_deepgram_keepalive_at
            and now - active.last_deepgram_keepalive_at < DEEPGRAM_KEEPALIVE_INTERVAL_SECONDS
        ):
            return
        send_keepalive = getattr(session, "send_keepalive", None)
        if not callable(send_keepalive):
            return
        if await send_keepalive():
            active.last_deepgram_keepalive_at = now

    def _finish_audio_silence_gate(self, active):
        gate = active.audio_silence_gate if active else None
        if gate is None:
            return
        dropped_bytes = gate.finish()
        if dropped_bytes:
            audio = self._audio_health(active)
            audio["bytes_dropped_silence"] = int(audio.get("bytes_dropped_silence") or 0) + dropped_bytes
            active.audio_chunks_since_metadata_flush += 1

    async def _flush_capture_audio_health(self, active, *, force=False):
        if not active or not active.audio_chunks_since_metadata_flush:
            return
        now = asyncio.get_running_loop().time()
        if (
            not force
            and active.audio_chunks_since_metadata_flush < CAPTURE_AUDIO_METADATA_FLUSH_CHUNKS
            and (
                active.last_capture_metadata_flush_at
                and now - active.last_capture_metadata_flush_at < CAPTURE_AUDIO_METADATA_FLUSH_INTERVAL_SECONDS
            )
        ):
            return
        await self._update_capture_session_metadata(
            active,
            {"audio": dict(self._audio_health(active))},
        )
        active.audio_chunks_since_metadata_flush = 0
        active.last_capture_metadata_flush_at = now

    async def _update_capture_session_for_meeting_status(self, state, status):
        active = self.active_sessions.get(state.session_id)
        if not active:
            return

        if status in {"starting_join", "waiting_for_host"}:
            await self._update_capture_session_status(active, "joining")
            return
        if status == "joined":
            await self._update_capture_session_status(active, "live")
            return

        failure_details = {
            "join_denied": ("JOIN_DENIED", "Google Meet denied Orbit's join request."),
            "join_blocked": ("JOIN_BLOCKED", "Google Meet blocked Orbit from joining."),
            "join_unconfirmed": ("JOIN_UNCONFIRMED", "Orbit could not confirm whether it joined Google Meet."),
            "no_active_page": ("NO_ACTIVE_PAGE", "Orbit lost the active browser page during capture."),
            "error": ("CAPTURE_SESSION_ERROR", "Meeting capture failed during the browser session."),
        }
        failure = failure_details.get(status)
        if failure:
            await self._mark_capture_session_failed(active, failure[0], failure[1])

    async def handle_audio_stream(self, websocket, session_id: str):
        active = self.active_sessions.get(session_id)
        if active is None:
            await websocket.close(code=4404, reason="Unknown Orbit meeting session.")
            return
        expected_token = active.state.live_stt_audio_token
        if expected_token and websocket.query_params.get("token") != expected_token:
            await websocket.close(code=4403, reason="Invalid Orbit audio stream token.")
            return
        if not self.live_stt.available:
            await websocket.close(code=4401, reason="Missing DEEPGRAM_API_KEY.")
            return

        await websocket.accept()
        try:
            disconnected_normally = False
            while True:
                message = await websocket.receive()
                message_type = message.get("type")
                if message_type == "websocket.disconnect":
                    disconnected_normally = True
                    break

                if message.get("bytes") is not None:
                    chunk = message["bytes"]
                    await self._forward_audio_chunk_for_session(
                        active,
                        chunk,
                    )
                    continue

                raw_text = message.get("text")
                if raw_text is None:
                    continue

                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    log(
                        f"Live audio WebSocket sent non-JSON text message; ignoring. "
                        f"Payload={raw_text[:120] if isinstance(raw_text, str) else str(raw_text)}",
                        session_id,
                        level="debug",
                    )
                    continue
                message_type = payload.get("type")
                if message_type in {"start", "config"}:
                    audio_format = LiveAudioFormat.from_payload(payload)
                    self._get_or_create_audio_silence_gate(active, audio_format)
                    active.live_stt_session = await self.live_stt.get_or_create(
                        active.state,
                        audio_format,
                    )
                    active.state.live_stt_status_detail = (
                        "Extension audio WebSocket connected. Waiting for the first audio chunk."
                    )
                    await websocket.send_json({"type": "ready"})
                elif message_type == "visual_frame":
                    await self.schedule_visual_frame_analysis(active, payload)
                elif message_type == "stop":
                    self._finish_audio_silence_gate(active)
                    break
        except Exception as error:
            self._finish_audio_silence_gate(active)
            if disconnected_normally or (
                isinstance(error, RuntimeError)
                and "Cannot call \"receive\" once a disconnect message has been received" in str(error)
            ):
                log(
                    f"Live audio WebSocket for Meet {active.state.meeting_code} closed cleanly.",
                    session_id,
                    level="debug",
                )
            else:
                await self._flush_capture_audio_health(active, force=True)
                await self._mark_capture_session_failed(
                    active,
                    "AUDIO_WEBSOCKET_CLOSED",
                    "Live audio WebSocket closed unexpectedly.",
                    metadata={"audio": dict(self._audio_health(active))},
                )
                log(
                    f"Live audio WebSocket failed for Meet {active.state.meeting_code}: {error}",
                    session_id,
                    level="error",
                )
        finally:
            self._finish_audio_silence_gate(active)
            await self._flush_capture_audio_health(active, force=True)
            try:
                await self.live_stt.stop(session_id)
            except Exception as error:
                await self._mark_capture_session_failed(
                    active,
                    "AUDIO_STREAM_CLEANUP_FAILED",
                    "Live audio streaming cleanup failed.",
                )
                log(
                    f"Live audio WebSocket cleanup failed for Meet {active.state.meeting_code}: {error}",
                    session_id,
                    level="error",
                )
