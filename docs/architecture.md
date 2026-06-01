# Orbit Architecture

Orbit captures Google Meet context, turns speech and chat into meeting artifacts, stores durable memory, and exposes that memory through WhatsApp and API routes.

## Main packages

```text
orbit/google_meet/          Google Meet browser automation
orbit/audio_pipeline/       Deepgram live STT, live audio sessions, PCM silence gating
orbit/transcripts/          Transcript segment models, normalization, caption speaker attribution
orbit/storage/meeting_store/ Meeting source, capture-session, transcript chunk, extraction, decision, action, memory persistence
orbit/storage/memory_index/  Legacy chat/transcript embedding memory index
orbit/whatsapp/             WhatsApp orchestration, meeting lifecycle, live recall, extraction, audio stream handling
orbit/agent/                Deterministic tool wrappers used by the WhatsApp agent path
orbit/api/                  FastAPI application and HTTP/WebSocket routes
orbit/config/               Environment and logging adapters around core runtime helpers
extension/orbit-audio-capture/ Chrome extension for Meet tab audio capture
tests/whatsapp/             WhatsApp service tests split by responsibility
tests/support/              Shared test fakes and fixtures
```

Compatibility modules such as `orbit.meet`, `orbit.whatsapp_service`, `orbit.meeting_store`, `orbit.memory`, and `orbit.live_stt` still exist. They re-export the new package implementations so existing scripts and tests can migrate incrementally.

## Data flow

```text
WhatsApp command or API request
  -> OrbitWhatsAppService
  -> capture dispatcher / active meeting session
  -> orbit.google_meet runner joins Google Meet
  -> Meet chat and captions are polled from the browser
  -> Chrome extension or server sink streams audio to Orbit
  -> orbit.audio_pipeline forwards audio to Deepgram live STT
  -> final transcript segments are normalized in orbit.transcripts
  -> transcript chunks and extraction outputs are saved in orbit.storage.meeting_store
  -> decisions, action items, and durable memories become queryable
  -> WhatsApp/API responses read meeting intelligence from storage
```

## Setup

Use Python 3.12 or 3.13. Browser Use is not reliable in this project on Python 3.14.

```bash
python3.12 -m venv .venv-browser-use
source .venv-browser-use/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

Required integrations are configured through `.env`: OpenAI, Deepgram, Twilio, Google Meet browser settings, and optional `DATABASE_URL` for Postgres persistence.

## Checks

```bash
python -m compileall -q orbit scripts
python -m ruff check orbit scripts tests
python -m mypy
python -m unittest discover -s tests
node --check extension/orbit-audio-capture/content.js
node --check extension/orbit-audio-capture/service_worker.js
node --check extension/orbit-audio-capture/offscreen.js
node tests/orbit_audio_capture_extension.test.js
```
