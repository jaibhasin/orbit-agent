from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import logging


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEBUG_DIR = Path("debug")
CONVERSATION_DIR = DEBUG_DIR / "browser-use"
BROWSER_USE_VENV_DIR = Path(".venv-browser-use")
BROWSER_USE_SENTINEL = "BROWSER_USE_PYTHON_BOOTSTRAPPED"
MEET_CODE_PATTERN = re.compile(r"meet\.google\.com/([a-z0-9-]+)", re.IGNORECASE)
LOG_LEVELS = {
    "quiet": 0,
    "error": 10,
    "important": 20,
    "info": 30,
    "debug": 40,
}


def _normalize_log_level(value):
    if value is None:
        return "important"
    normalized = str(value).strip().lower()
    return normalized if normalized in LOG_LEVELS else "important"


def _current_log_level():
    return LOG_LEVELS[_normalize_log_level(os.environ.get("ORBIT_LOG_LEVEL", "important"))]


def _log_level_value(level):
    return LOG_LEVELS[_normalize_log_level(level)]


def _third_party_logger_names():
    return (
        "Agent",
        "requests",
        "browser_use",
        "service",
        "tools",
        "twilio",
        "twilio.http_client",
        "openai",
        "httpx",
        "urllib3",
        "playwright",
    )


def _third_party_level_from_orbit():
    orbit_level = _current_log_level()
    if orbit_level <= LOG_LEVELS["error"]:
        return logging.ERROR
    if orbit_level == LOG_LEVELS["debug"]:
        return logging.DEBUG
    return logging.WARNING


def configure_dependency_logging():
    target = _third_party_level_from_orbit()
    noisy_names = _third_party_logger_names()
    logger_dict = logging.root.manager.loggerDict

    root_logger = logging.getLogger()
    if root_logger.level > target:
        root_logger.setLevel(target)

    for logger_name in list(logger_dict):
        if any(
            logger_name == prefix or logger_name.startswith(f"{prefix}.")
            for prefix in noisy_names
        ):
            logger = logging.getLogger(logger_name)
            logger.setLevel(target)
            logger.propagate = True
            for handler in list(logger.handlers):
                logger.removeHandler(handler)

    for logger_name in noisy_names:
        logger = logging.getLogger(logger_name)
        logger.setLevel(target)
        logger.propagate = True
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


def load_dotenv():
    env_paths = [
        ENV_PATH,
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parents[1] / "scripts" / ".env",
        Path(__file__).resolve().parents[2] / ".env" if len(Path(__file__).resolve().parts) > 2 else None,
    ]

    candidate_paths = [path for path in env_paths if path is not None]
    normalized_paths = []
    for candidate in candidate_paths:
        normalized = candidate.expanduser().resolve()
        if normalized not in normalized_paths:
            normalized_paths.append(normalized)

    source_path = None
    for candidate in normalized_paths:
        if candidate.exists():
            source_path = candidate
            break

    if source_path is None:
        return

    if source_path != ENV_PATH.resolve():
        log(f"Loaded environment from {source_path}", level="debug")

    for raw_line in source_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')

        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def env_float(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def log(message, session_id=None, level="info"):
    if level != "error" and _log_level_value(level) > _current_log_level():
        return

    prefix = "[browser-use-meet]" if not session_id else f"[browser-use-meet:{session_id}]"
    print(f"{prefix} {message}")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def normalize_message_text(text):
    return re.sub(r"\s+", " ", text).strip()


def extract_meeting_code(meet_url):
    match = MEET_CODE_PATTERN.search(meet_url or "")
    if match:
        return match.group(1).lower()
    return "unknown-meet"


def find_supported_python():
    candidates = [
        "python3.13",
        "python3.12",
        "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3",
        "/usr/local/bin/python3.13",
        "/usr/local/bin/python3.12",
        "/opt/homebrew/bin/python3.13",
        "/opt/homebrew/bin/python3.12",
    ]

    for candidate in candidates:
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if not resolved or not Path(resolved).exists():
            continue

        try:
            version = subprocess.check_output(
                [resolved, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                text=True,
            ).strip()
        except Exception:
            continue

        if version in {"3.12", "3.13"}:
            return resolved

    return None


def venv_python_path():
    return BROWSER_USE_VENV_DIR / "bin" / "python"


def ensure_browser_use_venv(argv=None, extra_imports=None):
    if sys.version_info < (3, 14):
        return

    if os.environ.get(BROWSER_USE_SENTINEL) == "1":
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            "Browser Use re-launch was attempted, but the interpreter is still "
            f"Python {version}. Check the dedicated venv at "
            f"{BROWSER_USE_VENV_DIR}."
        )

    supported_python = find_supported_python()
    if not supported_python:
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            "browser-use currently fails in this setup on Python "
            f"{version}. Install Python 3.12 or 3.13, then re-run this script."
        )

    target_python = venv_python_path()
    if not target_python.exists():
        log(f"Creating Browser Use venv with {supported_python}", level="debug")
        subprocess.run(
            [supported_python, "-m", "venv", str(BROWSER_USE_VENV_DIR)],
            check=True,
        )

    import_check = "import browser_use, playwright"
    if extra_imports:
        import_check = f"{import_check}, {', '.join(extra_imports)}"

    try:
        subprocess.run(
            [
                str(target_python),
                "-c",
                import_check,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        requirements_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        if not requirements_path.exists():
            raise RuntimeError(
                "The Browser Use venv exists but dependencies are missing, and "
                f"`{requirements_path}` could not be found to auto-install them."
            )
        log(
            "Browser-use virtualenv appears missing dependencies; installing from requirements.txt.",
            level="important",
        )
        try:
            subprocess.run(
                [
                    str(target_python),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_path),
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            raise RuntimeError(
                "The Browser Use venv exists but dependencies could not be installed. "
                f"Run `{target_python} -m pip install -r requirements.txt` and retry."
            )

        try:
            subprocess.run(
                [
                    str(target_python),
                    "-c",
                    import_check,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            raise RuntimeError(
                "The Browser Use venv exists but dependencies are still missing or incompatible. "
                f"Check `{requirements_path}` and run `{target_python} -m pip install -r requirements.txt`."
            )

    log(f"Re-launching with {target_python}", level="debug")
    relaunched_env = os.environ.copy()
    relaunched_env[BROWSER_USE_SENTINEL] = "1"
    argv_to_run = list(argv or sys.argv)
    os.execve(
        str(target_python),
        [str(target_python), *argv_to_run],
        relaunched_env,
    )


def assert_supported_python(script_name="scripts/join_meet.py"):
    if sys.version_info >= (3, 14):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(
            "browser-use currently fails in this setup on Python "
            f"{version}. Create a Python 3.12 or 3.13 virtualenv for "
            f"{script_name}."
        )


def ensure_browser_use_runtime(script_name="scripts/join_meet.py", extra_imports=None):
    load_dotenv()
    ensure_browser_use_venv(extra_imports=extra_imports)
    assert_supported_python(script_name)
