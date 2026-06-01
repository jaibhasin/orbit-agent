# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .browser import build_browser
from .captions import enable_captions
from .chat import monitor_chat
from .common import *
from .extension_audio import trigger_extension_audio_capture
from .join_flow import classify_join_failure, ensure_joined, get_meeting_status
from .session_config import build_default_session_config, build_task
from .session_events import emit_finished, emit_status, finalize_meeting_status


async def run_meeting_session(config, callbacks=None, state=None):
    configure_dependency_logging()
    load_dotenv()

    if state is None:
        state = build_meeting_state(config)

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in .env or environment.")

    DEBUG_DIR.mkdir(exist_ok=True)
    session_conversation_dir = CONVERSATION_DIR / config.session_id
    session_conversation_dir.mkdir(parents=True, exist_ok=True)
    session_gif_path = DEBUG_DIR / f"browser-use-meet-{config.session_id}.gif"

    from browser_use import Agent, Browser, ChatOpenAI
    configure_dependency_logging()

    browser = None
    history = None

    await emit_status(callbacks, state, "starting_join", f"Opening Meet URL: {config.meet_url}")
    log(f"Opening Meet URL: {config.meet_url}", state.session_id, level="important")
    log(f"Model: {config.model_name}", state.session_id, level="debug")
    log(f"Agent max steps: {config.max_steps}", state.session_id, level="debug")

    try:
        browser = build_browser(Browser, state=state, session_config=config)
        agent_model = config.model_name
        fallback_agent_model = "gpt-4o-mini"
        log(f"Agent model: {agent_model}", state.session_id, level="debug")
        if fallback_agent_model:
            log(f"Fallback agent model: {fallback_agent_model}", state.session_id, level="debug")
        llm = ChatOpenAI(model=agent_model)
        fallback_llm = None
        if fallback_agent_model and fallback_agent_model != agent_model:
            fallback_llm = ChatOpenAI(model=fallback_agent_model)

        agent: Any = Agent(
            task=build_task(config.meet_url, config.display_name),
            llm=llm,
            browser=browser,
            use_vision=True,
            max_failures=3,
            fallback_llm=fallback_llm,
            use_thinking=False,
            save_conversation_path=str(session_conversation_dir),
            generate_gif=str(session_gif_path),
        )
        history = await agent.run(max_steps=config.max_steps)
        log(f"Agent finished after {history.number_of_steps()} steps.", state.session_id, level="debug")

        final_result = history.final_result()
        if final_result:
            state.browser_use_final_result = final_result
            log(f"Final result: {final_result}", state.session_id, level="debug")

        if history.has_errors():
            state.browser_use_had_errors = True
            log(
                "Agent reported one or more step errors. Check debug/browser-use.",
                state.session_id,
                level="debug",
            )

        state.browser_use_success = history.is_successful()
        if state.browser_use_success:
            log("Browser Use marked the run as successful.", state.session_id, level="info")
        else:
            log("Browser Use did not mark the run as successful.", state.session_id, level="important")

        page = await browser.get_current_page()
        if not page:
            detail = "Browser Use did not leave an active page handle."
            await emit_status(callbacks, state, "no_active_page", detail)
            log(
                f"{detail} Keeping browser open for {config.wait_after_join_ms // 1000} seconds.",
                state.session_id,
                level="important",
            )
            await asyncio.sleep(config.wait_after_join_ms / 1000)
            return state

        async def notify_waiting_for_host(_status):
            detail = "Orbit submitted its join request and is waiting for a meeting host to admit it."
            await emit_status(callbacks, state, "waiting_for_host", detail)
            log(detail, state.session_id, level="important")

        joined, final_join_status = await ensure_joined(
            page,
            timeout_ms=env_int("GMEET_ADMISSION_WAIT_MS", 120000),
            on_waiting=notify_waiting_for_host,
        )
        if joined:
            state.joined_at = now_iso()
            detail = f"Orbit joined the meeting successfully. Monitoring chat for {config.wait_after_join_ms // 1000} seconds."
            await emit_status(callbacks, state, "joined", detail)
            log(detail, state.session_id, level="important")
            if config.live_stt_enabled:
                state.live_stt_requested = True
                await enable_captions(page, state.session_id)
                capture_strategy = (
                    getattr(config, "audio_capture_strategy", None)
                    or getattr(state, "audio_capture_strategy", None)
                    or get_audio_capture_strategy()
                )
                state.audio_capture_strategy = capture_strategy
                if capture_strategy == "server_audio_sink":
                    state.live_stt_available = bool(getattr(state, "live_stt_available", False))
                    if not state.live_stt_available:
                        await emit_status(
                            callbacks,
                            state,
                            "live_stt_unavailable",
                            "Server-side audio sink capture failed to initialize.",
                        )
                    else:
                        routing_mode = state.audio_capture_routing_mode or AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
                        routing_text = (
                            "Router configured for per-session browser process env."
                            if state.browser_audio_routed
                            else "Server browser-to-sink routing is not active in this runtime."
                        )
                        if routing_mode == AUDIO_ROUTING_MODE_PROCESS_ENV:
                            state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_PROCESS_ENV
                        elif routing_mode == AUDIO_ROUTING_MODE_LAUNCH_WRAPPER:
                            state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_LAUNCH_WRAPPER
                        else:
                            state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
                        state.live_stt_status_detail = (
                            "Orbit requested server-side audio capture. "
                            f"{routing_text}"
                        )
                        if state.audio_capture_routing_mode == AUDIO_ROUTING_MODE_PROCESS_ENV:
                            await emit_status(
                                callbacks,
                                state,
                                "live_stt_capture_requested",
                                "Orbit requested server-side audio capture. "
                                f"Browser audio is being routed to sink {state.audio_sink_name}.",
                            )
                        else:
                            await emit_status(
                                callbacks,
                                state,
                                "live_stt_unavailable",
                                "Server-side audio capture requested, but browser audio routing is not active for this session.",
                            )
                else:
                    state.live_stt_available = await trigger_extension_audio_capture(
                        page,
                        state,
                        config.audio_stream_ws_url,
                    )
                    if state.live_stt_available:
                        await emit_status(
                            callbacks,
                            state,
                            "live_stt_capture_requested",
                            "Orbit requested tab audio capture through the Chrome extension. Click the in-page Orbit audio button if Chrome requires manual activation.",
                        )
                    else:
                        await emit_status(
                            callbacks,
                            state,
                            "live_stt_unavailable",
                            state.live_stt_status_detail or "Orbit could not trigger tab audio capture.",
                        )
            await monitor_chat(page, state, config.wait_after_join_ms, callbacks)
        else:
            status = final_join_status or await get_meeting_status(page)
            join_status, detail = classify_join_failure(status)
            await emit_status(callbacks, state, join_status, detail)
            log(
                f"{detail} Keeping browser open for {config.wait_after_join_ms // 1000} seconds.",
                state.session_id,
                level="important",
            )
            await asyncio.sleep(config.wait_after_join_ms / 1000)
    except Exception as error:
        state.last_error = str(error)
        await emit_status(callbacks, state, "error", str(error))
        log(f"Meeting session failed: {error}", state.session_id, level="error")
    finally:
        state.finished_at = now_iso()
        finalize_meeting_status(state)
        if state.permission_events:
            log(
                f"Recorded {len(state.permission_events)} permission event(s).",
                state.session_id,
                level="debug",
            )
        if browser is not None:
            log("Closing browser.", state.session_id, level="debug")
            try:
                await browser.kill()
            except Exception as error:
                log(f"Browser shutdown failed: {error}", state.session_id, level="error")
        await emit_finished(callbacks, state)

    return state


async def main():
    ensure_browser_use_runtime("scripts/join_meet.py")

    meet_url = os.environ.get("GMEET_URL")
    if not meet_url:
        raise RuntimeError("Missing GMEET_URL in .env or environment.")

    config = build_default_session_config(meet_url)
    state = await run_meeting_session(config)
    if state.last_error:
        raise RuntimeError(state.last_error)
