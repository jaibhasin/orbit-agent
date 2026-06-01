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


class RuntimeMixin:
    def __init__(self):
        load_dotenv()
        configure_dependency_logging()

        self.twilio_account_sid = self._require_env("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = self._require_env("TWILIO_AUTH_TOKEN")
        self.twilio_whatsapp_from = self._require_env("TWILIO_WHATSAPP_FROM")
        self.twilio_allowed_from = self._require_env("TWILIO_ALLOWED_FROM", self._read_env("TWILIO_WHATSAPP_TO"))
        self.openai_api_key = self._require_env("OPENAI_API_KEY")
        self.model_name = self._require_env("OPENAI_MODEL", "gpt-5.4-mini")
        self.max_parallel_meetings = env_int("ORBIT_MAX_PARALLEL_MEETINGS", 3)

        self.twilio_client = Client(self.twilio_account_sid, self.twilio_auth_token)
        self.openai_client = AsyncOpenAI(api_key=self.openai_api_key)
        database_url = self._read_env("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required for WhatsApp meeting persistence. "
                "Set DATABASE_URL in your environment before starting Orbit."
            )
        self.meeting_store = build_meeting_store(database_url)
        self.memory = build_memory_service(self.openai_client, self.model_name)
        self.live_stt = LiveSTTManager(
            memory=self.memory,
            api_key=self._read_env("DEEPGRAM_API_KEY"),
            model=self._read_env("DEEPGRAM_LIVE_MODEL", "nova-3"),
            health_event_handler=self._handle_live_stt_health_event,
        )
        self.active_sessions: dict[str, ActiveMeeting] = {}
        self.pending_meeting_starts: set[str] = set()
        # TODO: make dialogue history durable before running multiple workers or relying on restart continuity.
        self.dialogue_history: list[DialogueTurn] = []
        self.lock = asyncio.Lock()

    def _require_env(self, name, default=None):
        value = self._read_env(name, default)
        if not value:
            raise RuntimeError(
                f"Missing {name} in .env or environment. "
                "Copy .env.example to .env and set required values for Orbit WhatsApp."
            )
        return value

    @staticmethod
    def _read_env(name, default=None):
        import os

        return os.environ.get(name, default)

    def _ensure_runtime_fields(self):
        if not hasattr(self, "dialogue_history"):
            self.dialogue_history = []

    def _reply_without_history(self, reply):
        return format_twiml(reply)

    def _reply_and_record(self, inbound, reply):
        self.record_dialogue_turn(inbound, reply)
        return format_twiml(reply)

    def reset_dialogue_history(self):
        self.dialogue_history = []

    def record_dialogue_turn(self, inbound, reply):
        self._ensure_runtime_fields()
        self.dialogue_history.append(
            DialogueTurn(
                inbound=self.truncate_dialogue_message(inbound),
                reply=self.truncate_dialogue_message(reply),
            )
        )
        self.dialogue_history = self.dialogue_history[-MAX_DIALOGUE_TURNS:]

    def truncate_dialogue_message(self, text):
        text = text or ""
        if len(text) <= MAX_DIALOGUE_MESSAGE_CHARS:
            return text
        return text[:MAX_DIALOGUE_MESSAGE_CHARS]

    def format_dialogue_history(self):
        self._ensure_runtime_fields()
        if not self.dialogue_history:
            return ""
        lines = []
        for turn in self.dialogue_history:
            lines.append(f"User: {turn.inbound}")
            lines.append(f"Orbit: {turn.reply}")
        return "\n".join(lines)
