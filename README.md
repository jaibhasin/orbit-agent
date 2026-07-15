# Orbit

**Orbit is building the system of context for AI-native companies.**

AI-native companies will not run on static dashboards, scattered meeting notes, and a chat box bolted onto old workflows. They will run on continuously updated context: what changed, what was decided, who owns the next move, where the evidence came from, and what the company should look at now.

This repository implements Orbit's first wedge: source-backed meeting and decision memory. Orbit joins authorized Google Meets, captures chat and live transcript evidence, extracts structured company memory, stores provenance, and makes the result queryable through WhatsApp, API tools, and an early OpenUI command-center prototype.

## AI-Native Companies Need Context

The shift to AI-native work is bigger than adding an assistant to every product.

[Microsoft's 2025 Work Trend Index](https://www.microsoft.com/en-us/worklab/work-trend-index/2025-the-year-the-frontier-firm-is-born) describes the emergence of "Frontier Firms": organizations built around human-agent teams, with agents taking on more work across the business. [SAP's AI-Native North-Star Architecture](https://architecture.learning.sap.com/docs/ai-native-north-star-architecture/vision) makes the enterprise implication explicit: systems of record are not enough on their own. AI-native systems need a **system of context** that can assemble relevant business state at decision time.

The model is only one part of the system. [Anthropic's context-engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) argues that agent quality depends on curating the right context state: instructions, tools, retrieved evidence, history, and runtime signals. More context is not automatically better. The useful context must be authorized, current, source-backed, and relevant to the task.

That is the bet behind Orbit:

```text
company activity
      |
      v
captured evidence
      |
      v
structured, source-backed memory
      |
      v
AI-generated answers, tools, and operating views
```

Meetings are the starting point because they contain high-value context that often disappears immediately after the call: decisions, rationale, unresolved questions, commitments, risks, and changing priorities.

## From Prompt To Dashboard

Static dashboards force a company to predict every future question in advance. An AI-native dashboard should assemble the right interface when the question arrives.

Ask Orbit:

```text
What changed this week?
Which projects are blocked, and which meeting introduced each blocker?
Show decisions waiting for an owner.
Build a founder view of product momentum, open loops, and AI spend.
What should the team look at before the next launch review?
```

The target experience is a dynamic command center generated from prompts and grounded in company context:

```text
prompt
  -> retrieve authorized evidence
  -> call typed company tools
  -> select the right UI components
  -> render a purpose-built dashboard
  -> keep every claim linked to source context
```

Instead of one fixed BI screen, Orbit can generate the operating view needed for the moment: a project radar, a decision timeline, an action queue, a weekly executive pulse, a cost breakdown, or a focused investigation into one risk.

The frontend in [`frontend/openui-orbit-demo`](frontend/openui-orbit-demo) is the first design probe for that direction. It uses [`@openuidev/react-lang`](https://www.openui.com/docs/openui-lang) and the [OpenUI architecture](https://www.openui.com/docs/architecture) to render a constrained React component library from an OpenUI response.

**Current state:** the command-center frontend is a static synthetic demo. It proves the visual language and rendering boundary, but it is not yet connected to Orbit's backend data or an LLM prompt-to-dashboard pipeline.

## What Exists Today

| Layer | Status | What it does |
| --- | --- | --- |
| Google Meet agent | Implemented | Joins authorized Meets with mic and camera disabled, opens chat, posts an intro, and monitors the session |
| Meet chat capture | Implemented | Captures visible chat messages and detects `@orbit` mentions |
| Live transcript capture | Implemented | Captures Meet tab audio through a local Manifest V3 Chrome extension and streams PCM16 audio to Deepgram |
| Shared-screen visual capture | Implemented, opt-in | Samples tab video locally, waits for a stable meaningful change, and sends only changed frames to a low-detail VLM |
| Speaker enrichment | Best effort | Uses visible Google Meet captions as an optional speaker-attribution layer |
| Structured meeting memory | Implemented | Persists sources, meetings, capture sessions, transcript chunks, extraction runs, decisions, action items, and durable memories |
| Searchable memory | Implemented | Stores chat and transcript memory chunks with OpenAI embeddings for source-backed recall |
| WhatsApp control plane | Implemented | Accepts deterministic Twilio WhatsApp commands for capture, status, summaries, decisions, and actions |
| Meeting intelligence API | Implemented | Returns processed meeting summaries and structured artifacts over HTTP |
| Dynamic AI dashboard | Prototype | Ships a static OpenUI command-center demo with synthetic telemetry |

WhatsApp is the bootstrap shell, not the product boundary. Google Meet is the first context source, not the final surface area. The long-term product is a trusted operating layer for company context.

## System Flow

```text
WhatsApp / Twilio
      |
      v
FastAPI webhook
      |
      v
deterministic command handler
      |
      v
agent tool wrappers
      |
      +--> request_meeting_capture
      |       |
      |       v
      |   in-process capture dispatcher
      |       |
      |       v
      |   Google Meet session worker
      |       |
      |       +--> deterministic DOM join
      |       +--> Browser Use fallback
      |       +--> Meet chat capture
      |       +--> optional caption attribution
      |       +--> Chrome extension tab audio + optional visuals
      |                 |
      |                 +--> PCM16 -> Deepgram live STT
      |                 |
      |                 +--> stable changed frame -> low-detail VLM
      |
      +--> meeting intelligence reads
      |
      +--> Postgres
              |
              +--> structured artifacts
              +--> extraction outputs
              +--> searchable memory chunks + pgvector embeddings
```

At the end of a captured meeting, Orbit stores normalized transcript chunks, runs a structured extraction prompt, and persists:

- short and long summaries
- decisions and rationale
- action items and owners
- risks
- open questions
- durable company memories

## Quick Start

### Prerequisites

- Python `3.12` or `3.13`
- Docker with Compose
- Chrome or Chromium
- An OpenAI API key
- A Deepgram API key for live transcription
- Twilio WhatsApp credentials for the WhatsApp control plane

Browser Use is not reliable in this project under Python `3.14`.

### Install

```bash
python3.12 -m venv .venv-browser-use
source .venv-browser-use/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
cp .env.example .env
```

### Start Postgres

```bash
docker compose up -d orbit-postgres
python scripts/migrate_memory.py
```

The WhatsApp/FastAPI path requires `DATABASE_URL`. Orbit creates the structured meeting tables automatically on first use. `scripts/migrate_memory.py` applies the searchable-memory schema used for embeddings and recall.

### Configure `.env`

Fill in at least:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.4-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small

DEEPGRAM_API_KEY=...
DEEPGRAM_LIVE_MODEL=nova-3
ORBIT_LIVE_STT_ENABLED=true
ORBIT_AUDIO_WS_BASE_URL=ws://127.0.0.1:8000
ORBIT_CHROME_EXTENSION_PATH=extension/orbit-audio-capture
ORBIT_VISUAL_CAPTURE_ENABLED=false
ORBIT_VISUAL_MODEL=gpt-5.4-mini

TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_ALLOWED_FROM=whatsapp:+15551234567

ORBIT_WEBHOOK_HOST=0.0.0.0
ORBIT_WEBHOOK_PORT=8000
DATABASE_URL=postgresql://orbit:orbit@localhost:5432/orbit
```

The WhatsApp runtime intentionally supports one allowed control number today through `TWILIO_ALLOWED_FROM`.

### Load The Chrome Extension

For local development with `GMEET_USE_SYSTEM_CHROME=true` or an existing CDP browser:

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click **Load unpacked**.
4. Select [`extension/orbit-audio-capture`](extension/orbit-audio-capture).

The extension captures Meet tab audio locally and sends it to Orbit's local WebSocket. When visual capture is enabled, it also samples the tab locally, rejects moving or duplicate frames, and sends only stable meaningful changes to the backend VLM. Provider keys stay in the backend.

### Run The WhatsApp Agent

```bash
source .venv-browser-use/bin/activate
python scripts/whatsapp_bot.py
```

Expose the webhook for Twilio:

```bash
ngrok http 8000
```

Configure the Twilio WhatsApp webhook:

```text
POST https://your-ngrok-domain/twilio/whatsapp
```

FastAPI also exposes:

```text
GET  /
GET  /docs
POST /api/whatsapp/inbound
GET  /meetings/{meeting_id}/intelligence
WS   /internal/audio-stream/{session_id}?token={session_token}
```

### Run The Direct Meet Agent

For a direct local Meet smoke test, set `GMEET_URL` in `.env` and run:

```bash
source .venv-browser-use/bin/activate
ORBIT_LIVE_STT_ENABLED=false python scripts/join_meet.py
```

The direct runner does not start the FastAPI audio WebSocket. Keep live STT disabled unless the backend is already running.

## WhatsApp Commands

```text
join https://meet.google.com/abc-defg-hij
status <meeting-id>
summary <meeting-id>
decisions <meeting-id>
actions <meeting-id>
recent
open actions
help
```

The Twilio webhook uses deterministic command parsing. It does not invoke Chrome, Deepgram, or an LLM directly from the parser. Capture scheduling goes through agent tool wrappers and backend dispatch.

## Run The Command Center Demo

```bash
cd frontend/openui-orbit-demo
npm install
npm run dev
```

Build the frontend:

```bash
npm run build
```

The demo renders synthetic data for:

- company pulse
- project velocity and radar
- decision intelligence
- open loops
- team-flow signals
- AI cost and usage
- a self-improvement loop
- an `Ask Orbit` prompt surface

The next implementation step is to connect these view primitives to typed Orbit tools and generate OpenUI responses from prompts against real company context.

## Repository Map

```text
orbit/google_meet/            Meet browser automation, chat, captions, extension trigger
orbit/audio_pipeline/         Deepgram streaming, live STT sessions, PCM silence gating
orbit/transcripts/            Transcript segments, normalization, caption attribution
orbit/storage/meeting_store/  Structured meeting artifacts and Postgres persistence
orbit/storage/memory_index/   Chat/transcript embeddings and source-backed recall
orbit/whatsapp/               Runtime, meeting lifecycle, audio streams, extraction, recall
orbit/agent/                  Typed tools and deterministic WhatsApp command parser
orbit/api/                    FastAPI app, Twilio webhook, intelligence route, audio WebSocket
extension/orbit-audio-capture/ Local Manifest V3 Meet audio and changed-frame capture extension
frontend/openui-orbit-demo/   Static OpenUI command-center design probe
scripts/                      Local run, migration, audit, reindex, and extraction helpers
tests/                        Python and Chrome-extension tests
docs/                         Architecture notes and live-STT runbook
```

Compatibility modules remain at older import paths, including `orbit.meet`, `orbit.whatsapp_service`, `orbit.meeting_store`, `orbit.memory`, and `orbit.live_stt`.

## Storage Model

Orbit currently has two complementary persistence paths.

### Structured meeting artifacts

The meeting store creates:

```text
people
sources
meetings
capture_sessions
source_chunks
extraction_runs
decisions
action_items
memories
```

These tables support meeting lifecycle tracking, source provenance, structured extraction, and API responses. See [`orbit/storage/meeting_store/schema.py`](orbit/storage/meeting_store/schema.py).

### Searchable company memory

The memory index stores raw chat, normalized transcripts, searchable chunks, embedding state, and source metadata for recall. See [`orbit/storage/memory_index/schema.py`](orbit/storage/memory_index/schema.py).

Useful helpers:

```bash
python scripts/migrate_memory.py
python scripts/reindex_memory.py
python scripts/audit_memory.py --show-text
python scripts/test_meeting_extraction.py --meeting-id <MEETING_ID>
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key for extraction, recall, and embeddings |
| `OPENAI_MODEL` | Chat model used by Orbit |
| `OPENAI_EMBEDDING_MODEL` | Embedding model for searchable memory |
| `DEEPGRAM_API_KEY` | Backend-only key for live STT |
| `DEEPGRAM_LIVE_MODEL` | Deepgram live model, default `nova-3` |
| `ORBIT_LIVE_STT_ENABLED` | Enable Meet audio transcription |
| `ORBIT_AUDIO_WS_BASE_URL` | Local extension-audio WebSocket base URL |
| `ORBIT_CHROME_EXTENSION_PATH` | Unpacked extension path |
| `ORBIT_CHROME_CDP_URL` | Optional existing Chrome CDP URL |
| `ORBIT_VISUAL_CAPTURE_ENABLED` | Opt in to local visual sampling and changed-frame analysis |
| `ORBIT_VISUAL_MODEL` | Vision-capable model used only for accepted changed frames |
| `ORBIT_VISUAL_SAMPLE_INTERVAL_MS` | Local frame sampling interval, default 3000 ms |
| `ORBIT_VISUAL_COOLDOWN_MS` | Minimum interval between VLM frames, default 8000 ms |
| `ORBIT_VISUAL_CHANGE_THRESHOLD` | Minimum perceptual change from the last accepted frame |
| `ORBIT_VISUAL_STABILITY_THRESHOLD` | Maximum movement allowed before a changed frame is considered stable |
| `DATABASE_URL` | Required by the WhatsApp backend for persistence and memory |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token and inbound-signature validation secret |
| `TWILIO_WHATSAPP_FROM` | Twilio WhatsApp sender |
| `TWILIO_ALLOWED_FROM` | Single authorized WhatsApp control number |
| `ORBIT_WEBHOOK_HOST` | FastAPI bind host |
| `ORBIT_WEBHOOK_PORT` | FastAPI bind port |
| `ORBIT_MAX_PARALLEL_MEETINGS` | In-process meeting concurrency limit |
| `ORBIT_ORGANIZATION_ID` | Organization scope for searchable memory |
| `ORBIT_MEMORY_SEARCH_LIMIT` | Number of retrieved memory chunks |
| `ORBIT_MEMORY_SIMILARITY_THRESHOLD` | Minimum memory-search similarity |
| `ORBIT_LOG_LEVEL` | `important`, `info`, `debug`, `error`, or `quiet` |
| `GMEET_URL` | Meet URL for the direct runner |
| `GMEET_DISPLAY_NAME` | Display name used in Google Meet |
| `GMEET_USE_SYSTEM_CHROME` | Use an installed Chrome profile |
| `GMEET_FAST_JOIN_ENABLED` | Attempt deterministic DOM join before Browser Use fallback |
| `GMEET_FAST_JOIN_TIMEOUT_MS` | Deterministic join timeout |
| `GMEET_ADMISSION_WAIT_MS` | Host-admission wait timeout |
| `GMEET_WAIT_AFTER_JOIN_MS` | Maximum post-join monitoring duration |
| `HEADLESS` | Run browser automation headlessly |

See [`.env.example`](.env.example) for the full local template.

## Development

Run the backend checks:

```bash
source .venv-browser-use/bin/activate
python -m ruff check orbit scripts tests
python -m mypy
python -m unittest discover -s tests
python -m compileall -q orbit scripts
```

Run the extension checks:

```bash
node --check extension/orbit-audio-capture/content.js
node --check extension/orbit-audio-capture/service_worker.js
node --check extension/orbit-audio-capture/offscreen.js
node tests/orbit_audio_capture_extension.test.js
python -m json.tool extension/orbit-audio-capture/manifest.json >/dev/null
```

See [`TESTING.md`](TESTING.md) for the complete local CI checklist.

## Current Boundaries

- Orbit is an early prototype, not a production-ready multi-tenant service.
- The active live-audio path is the local Chrome extension. Chrome may require manual extension activation before `tabCapture` starts.
- Google Meet DOM selectors can change without notice.
- Speaker names are best effort. Deepgram transcript text is the core path; visible Meet captions only enrich attribution.
- The command-center frontend is synthetic and static today.
- Capture scheduling uses in-process tasks. A durable queue and workers are future infrastructure.
- The WhatsApp runtime is intentionally single-controller today.
- Orbit does not bypass Google Meet admission, Twilio verification, or company access controls.

## Further Reading

- [`docs/architecture.md`](docs/architecture.md) - package map and runtime data flow
- [`docs/live-stt.md`](docs/live-stt.md) - live transcription architecture and local extension details
- [`TESTING.md`](TESTING.md) - checks, test layers, and conventions
- [Microsoft: 2025 Work Trend Index](https://www.microsoft.com/en-us/worklab/work-trend-index/2025-the-year-the-frontier-firm-is-born) - human-agent teams and Frontier Firms
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) - context as a constrained, curated runtime resource
- [SAP: AI-Native North-Star Architecture](https://architecture.learning.sap.com/docs/ai-native-north-star-architecture/vision) - the enterprise system-of-context framing
- [OpenUI: OpenUI Lang](https://www.openui.com/docs/openui-lang) - constrained generative UI language used by the frontend prototype
