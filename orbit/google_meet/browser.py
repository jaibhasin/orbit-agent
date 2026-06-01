# ruff: noqa: F401,F403,F405
from __future__ import annotations

from .common import *
from .common import _build_server_audio_env, _build_supported_kwargs


def build_browser(Browser, state=None, session_config=None):
    session_id = getattr(state, "session_id", None)
    headless = env_bool("HEADLESS", False)
    use_system_chrome = env_bool("GMEET_USE_SYSTEM_CHROME", False)
    profile_directory = os.environ.get("GMEET_CHROME_PROFILE_DIRECTORY")
    cdp_url = os.environ.get("ORBIT_CHROME_CDP_URL")
    extension_path = os.environ.get("ORBIT_CHROME_EXTENSION_PATH", "extension/orbit-audio-capture")
    extension_path_obj = Path(extension_path).expanduser()
    if not extension_path_obj.is_absolute():
        extension_path_obj = (Path(__file__).resolve().parents[1] / extension_path_obj).resolve()
    audio_capture_strategy = (
        getattr(session_config, "audio_capture_strategy", None)
        or get_audio_capture_strategy()
    )
    sink_name = getattr(session_config, "audio_sink_name", None)
    capture_session_id = getattr(session_config, "capture_session_id", None)
    route_audio_to_sink = audio_capture_strategy == "server_audio_sink" and bool(sink_name)

    if cdp_url:
        log(f"Connecting Browser Use to existing Chrome over CDP: {cdp_url}", session_id, level="debug")
        if route_audio_to_sink and state is not None:
            log(
                "Cannot apply per-session audio routing with ORBIT_CHROME_CDP_URL; CDP path is shared.",
                session_id,
                level="important",
            )
            state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
            state.browser_audio_routed = False
            state.browser_process_isolated = False
            state.audio_sink_name = sink_name
        return Browser(
            cdp_url=cdp_url,
            keep_alive=True,
        )

    browser_args = []
    if extension_path_obj.exists():
        resolved_extension_path = str(extension_path_obj)
        log(f"Orbit extension path resolved to: {resolved_extension_path}", session_id, level="debug")
        browser_args.extend(
            [
                f"--disable-extensions-except={resolved_extension_path}",
                f"--load-extension={resolved_extension_path}",
            ]
        )
    else:
        log(
            f"Orbit extension path not found; live tab audio capture via extension will be disabled: {extension_path_obj}",
            session_id,
            level="important",
        )

    if use_system_chrome:
        if route_audio_to_sink:
            log(
                f"server_audio_sink requested for session {session_id} capture_session_id={capture_session_id}; "
                "using managed browser for per-session isolation.",
                session_id,
                level="debug",
            )
            use_system_chrome = False
        elif extension_path_obj.exists():
            log(
                "GMEET_USE_SYSTEM_CHROME is enabled while extension-based STT is configured. "
                "Switching to managed browser so --load-extension can be applied.",
                session_id,
                level="important",
            )
            use_system_chrome = False

        log(
            "Using Browser Use with your installed Chrome profile."
            if use_system_chrome
            else "Using managed Browser Use session.",
            session_id,
            level="debug",
        )
        if browser_args:
            log(
                "Official Chrome 137+ ignores command-line unpacked-extension loading. "
                "Load the Orbit extension manually from chrome://extensions before joining.",
                session_id,
                level="important",
            )
        if profile_directory:
            log(f"Requested Chrome profile: {profile_directory}", session_id, level="debug")
            return Browser.from_system_chrome(
                profile_directory=profile_directory,
                keep_alive=True,
                args=browser_args or None,
            )
        return Browser.from_system_chrome(keep_alive=True, args=browser_args or None)

    if route_audio_to_sink and state is not None:
        state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
        state.browser_audio_routed = False
        state.browser_process_isolated = True
        state.audio_sink_name = sink_name

    browser_kwargs = {
        "headless": headless,
        "keep_alive": True,
        "window_size": {"width": 1440, "height": 960},
        "args": browser_args or None,
    }

    if route_audio_to_sink:
        server_env = _build_server_audio_env(sink_name)
        if server_env is not None:
            browser_kwargs_with_env = _build_supported_kwargs(
                Browser.__init__,
                {"env": server_env},
            )
            try:
                browser = Browser(
                    **browser_kwargs,
                    **browser_kwargs_with_env,
                )
            except TypeError:
                # Browser __init__ does not support the env kwarg in this runtime.
                # Preserve safe parallel behavior by still creating a per-session process.
                browser = Browser(**browser_kwargs)
                if state is not None:
                    state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
                    state.browser_audio_routed = False
            else:
                if "env" in browser_kwargs_with_env:
                    routing_mode = AUDIO_ROUTING_MODE_PROCESS_ENV
                    if state is not None:
                        state.audio_capture_routing_mode = routing_mode
                        state.browser_audio_routed = True
                        log(
                            f"Routed browser audio for session {session_id} capture_session_id={capture_session_id} "
                            f"through sink={sink_name} using process env.",
                            session_id,
                            level="debug",
                        )
                elif state is not None:
                    state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
        else:
            browser = Browser(**browser_kwargs)
    else:
        log("Using Browser Use managed browser session for guest join flow.", session_id, level="debug")
        browser = Browser(
            **browser_kwargs,
        )
    if not route_audio_to_sink and browser_args:
        log(f"Loading Orbit audio capture extension: {resolved_extension_path}", session_id, level="debug")
    if route_audio_to_sink and browser_args:
        log(
            f"Managed browser launched for server_audio_sink with target sink: {sink_name}",
            session_id,
            level="debug",
        )

    return browser
