# ruff: noqa: F401,F403,F405
from __future__ import annotations

import tempfile

from .common import *
from .common import _build_server_audio_env, _build_supported_kwargs


def _find_chrome_for_testing_executable():
    candidates = [
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        *Path.home().glob(
            "Library/Caches/ms-playwright/chromium-*/chrome-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ),
        *Path.home().glob(
            "Library/Caches/ms-playwright/chromium-*/chrome-*-*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ),
    ]
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    return str(sorted(existing, key=lambda path: path.stat().st_mtime, reverse=True)[0])


def _find_chrome_executable(prefer_chrome_for_testing=True):
    if prefer_chrome_for_testing:
        chrome_for_testing = _find_chrome_for_testing_executable()
        if chrome_for_testing:
            return chrome_for_testing

    from browser_use.skill_cli.utils import find_chrome_executable

    return find_chrome_executable()


def build_browser(Browser, state=None, session_config=None):
    session_id = getattr(state, "session_id", None)
    headless = env_bool("HEADLESS", False)
    use_system_chrome = env_bool("GMEET_USE_SYSTEM_CHROME", True)
    profile_directory = os.environ.get("GMEET_CHROME_PROFILE_DIRECTORY")
    force_new_profile = env_bool("GMEET_CHROME_NEW_PROFILE", True)
    chrome_executable_path = os.environ.get("GMEET_CHROME_EXECUTABLE_PATH")
    prefer_chrome_for_testing = env_bool("GMEET_PREFER_CHROME_FOR_TESTING", True)
    cdp_url = os.environ.get("ORBIT_CHROME_CDP_URL")
    extension_path = os.environ.get("ORBIT_CHROME_EXTENSION_PATH", "extension/orbit-audio-capture")
    extension_path_obj = Path(extension_path).expanduser()
    if not extension_path_obj.is_absolute():
        extension_path_obj = (Path(__file__).resolve().parents[2] / extension_path_obj).resolve()
    audio_capture_strategy = (
        getattr(session_config, "audio_capture_strategy", None)
        or get_audio_capture_strategy()
    )
    sink_name = getattr(session_config, "audio_sink_name", None)
    capture_session_id = getattr(session_config, "capture_session_id", None)
    route_audio_to_sink = audio_capture_strategy == "server_audio_sink" and bool(sink_name)

    if cdp_url:
        log(
            f"stage=browser.use_browser mode=cdp cdp_url={cdp_url}",
            session_id,
            level="important",
        )
        if route_audio_to_sink and state is not None:
            log(
                "stage=browser.audio_routing unavailable reason=cdp_shared",
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

    browser_args = [
        "--password-store=basic",
        "--use-mock-keychain",
    ]
    if extension_path_obj.exists():
        resolved_extension_path = str(extension_path_obj)
        log(f"stage=browser.extension_path resolved={resolved_extension_path}", session_id, level="important")
        browser_args.extend(
            [
                "--enable-extensions",
                "--disable-extensions-file-access-check",
                f"--disable-extensions-except={resolved_extension_path}",
                f"--load-extension={resolved_extension_path}",
            ]
        )
    else:
        log(
            f"stage=browser.extension_path_missing path={extension_path_obj}",
            session_id,
            level="important",
        )

    if use_system_chrome and route_audio_to_sink:
        log(
            f"stage=browser.audio_route request=server_audio_sink session={session_id} "
            f"capture_session={capture_session_id}; using managed browser",
            session_id,
            level="debug",
        )
        use_system_chrome = False

    if use_system_chrome:
        log(
            f"stage=browser.launch mode={'system_chrome_profile' if profile_directory else 'system_chrome_isolated' if force_new_profile else 'system_chrome'}"
            f"{' profile_dir_set=1' if profile_directory else ''}",
            session_id,
            level="important",
        )
        if browser_args:
            log(
                f"stage=browser.extension_args loaded={bool(browser_args)}",
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
        if force_new_profile:
            if not chrome_executable_path:
                chrome_executable_path = _find_chrome_executable(
                    prefer_chrome_for_testing=prefer_chrome_for_testing,
                )
            if not chrome_executable_path:
                raise RuntimeError("System Chrome executable was not found.")
            temporary_profile_dir = tempfile.mkdtemp(prefix=f"browser-use-user-data-dir-orbit-{session_id or 'session'}-")
            log(
                f"stage=browser.launch mode=system_chrome_isolated executable={chrome_executable_path} fresh_profile_dir={temporary_profile_dir}",
                session_id,
                level="important",
            )
            return Browser(
                executable_path=chrome_executable_path,
                user_data_dir=temporary_profile_dir,
                profile_directory="Default",
                headless=headless,
                keep_alive=True,
                window_size={"width": 1440, "height": 960},
                enable_default_extensions=False,
                args=browser_args or None,
            )
        return Browser.from_system_chrome(keep_alive=True, args=browser_args or None)

    if route_audio_to_sink and state is not None:
        state.audio_capture_routing_mode = AUDIO_ROUTING_MODE_NOT_IMPLEMENTED
        state.browser_audio_routed = False
        state.browser_process_isolated = True
        state.audio_sink_name = sink_name
        log(
            f"stage=browser.launch mode=managed route=server_audio_sink session={session_id}",
            session_id,
            level="important",
        )

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
        log("stage=browser.launch mode=managed", session_id, level="important")
        browser = Browser(
            **browser_kwargs,
        )
    if not route_audio_to_sink and browser_args:
        log(f"stage=browser.extension_enabled path={resolved_extension_path}", session_id, level="important")
    if route_audio_to_sink and browser_args:
        log(
            f"Managed browser launched for server_audio_sink with target sink: {sink_name}",
            session_id,
            level="important",
        )

    return browser
