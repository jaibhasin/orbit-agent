# Fix Me

Numbered bugs and issues to address.

---

(FIXED)**1.** `_persistent_meeting_status` (`meeting_sessions.py`) — After join, a later `"error"` status maps to `"joining"` instead of staying `live`/`failed`. Check `state.joined_at` before pre-join status mapping.

(FIXED)**2.** Duplicate WhatsApp on stop (`stop_active_meeting` + `handle_session_finished`) — User gets both “stopped monitoring” and “finished Meet” messages. Skip finish message when `stop_requested`.

(FIXED)**3.** Lock held during DB I/O in `start_single_meeting_session` — Blocks other session ops while creating meeting/capture rows. Reserve slot under lock; persist outside.

**4.** Remove optional DB persistence — Meeting/capture rows should be required, not best-effort. Today `_create_meeting_record` returns `(None, None)` when `from_number` or `meeting_store` is missing, DB errors are swallowed, and lines 65–81 skip capture-session creation when IDs are absent. Remove `DisabledMeetingStore` fallback for production paths, drop defensive `getattr` guards where the store must exist, and fail fast (or reject the WhatsApp request) if person/meeting/capture rows cannot be created.

**5.** Archive `server_audio_sink` capture strategy — Only `chrome_extension` should remain active. Move archived code under `archive/server_audio_sink/` (or similar) and remove live wiring:

- `orbit/audio_capture/server_audio_sink.py`
- `orbit/server_audio_sink_check.py`, `scripts/check_server_audio_sink.py`
- `orbit/whatsapp/audio_streams.py` — `_start/_run/_stop_server_audio_sink_capture` and related `ActiveMeeting` fields
- `orbit/whatsapp/meeting_sessions.py` — `_run_session` branches for `server_audio_sink`
- `orbit/google_meet/browser.py`, `runner.py` — sink routing / managed-browser launch paths
- Tests: `tests/test_meet_audio_routing.py`, `tests/test_server_audio_sink_check.py`, `tests/whatsapp/test_audio_streams.py` (sink-specific cases)

Keep `get_audio_capture_strategy()` pinned to `chrome_extension` until archival is complete. Update README env docs (`ORBIT_AUDIO_CAPTURE_STRATEGY`) and demo copy that still references `server_audio_sink`.

**6.** Loose WhatsApp intent parsing (`message_flow.py` `parse_whatsapp_intent`) — `status` and `live_recall` use substring checks (`pattern in lowered`), so normal questions get misrouted. Examples: “What’s the status of our Q3 plan?” → meeting status command; “What happened to the project last week?” → live recall (then fails with no active meet). Prefer exact/anchored commands or stricter phrase matching before falling back to general Q&A.

**7.** Prompt / continuity gaps — (a) `dialogue_history` in `RuntimeMixin` is in-process only (`runtime.py` TODO): lost on restart and unsafe with multiple workers; make durable or document single-worker constraint. (b) `handle_orbit_mention` system prompt tells the model it has no audio/transcript access even though Orbit has live STT and captured chat — update prompt so in-meeting answers can use chat context honestly without overclaiming.
