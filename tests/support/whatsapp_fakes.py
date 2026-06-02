# ruff: noqa: F401,F811
from __future__ import annotations

import asyncio
import struct
import unittest
import sys
import types
from unittest.mock import AsyncMock, patch


if "twilio" not in sys.modules:
    twilio_module = types.ModuleType("twilio")
    twilio_rest_module = types.ModuleType("twilio.rest")
    twilio_twiml_module = types.ModuleType("twilio.twiml")
    twilio_messaging_module = types.ModuleType("twilio.twiml.messaging_response")

    class MessagingResponse:
        def __init__(self, *args, **kwargs):
            self._value = ""

        def message(self, body=None):
            if body is not None:
                self._value = body
            return self._value

        def __str__(self):
            return str(self._value)

    twilio_rest_module.Client = object
    twilio_messaging_module.MessagingResponse = MessagingResponse
    twilio_module.rest = twilio_rest_module
    twilio_module.twiml = twilio_twiml_module
    twilio_twiml_module.messaging_response = twilio_messaging_module

    sys.modules["twilio"] = twilio_module
    sys.modules["twilio.rest"] = twilio_rest_module
    sys.modules["twilio.twiml"] = twilio_twiml_module
    sys.modules["twilio.twiml.messaging_response"] = twilio_messaging_module

from orbit.meet_types import ChatMessage, MeetingState
from orbit.meeting_store import merge_capture_session_metadata
from orbit.memory import MemoryAnswer, MemorySource
from orbit.transcript import TranscriptSegment
from orbit.whatsapp_service import (
    CAPTURE_AUDIO_METADATA_FLUSH_CHUNKS,
    ActiveMeeting,
    OrbitWhatsAppService,
)


class FakeMemory:
    def __init__(self, answer=None):
        self.recorded = []
        self.transcripts = []
        self.finalized = []
        self.questions = []
        self.answer = answer or MemoryAnswer(
            answer="The launch date discussed was Friday.",
            sources=[
                MemorySource(
                    label="Meet abc-defg-hij / Priya / 10:05",
                    source_type="meet_chat",
                    meeting_code="abc-defg-hij",
                    author="Priya",
                    timestamp_text="10:05",
                )
            ],
        )

    async def record_meeting_chat(self, state, message):
        self.recorded.append((state, message))

    async def record_transcript_segments(self, state, segments):
        self.transcripts.append((state, segments))

    async def finalize_meeting(self, state):
        self.finalized.append(state)

    async def search_memory(self, query):
        return []

    async def answer_from_memory(self, question):
        self.questions.append(question)
        return self.answer


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeMeetingStore:
    def __init__(self):
        self.people = []
        self.sources = []
        self.meetings = []
        self.updates = []
        self.saved_chunks = []
        self.transcript_save_calls = []
        self.fail_save_chunks = False
        self.extraction_runs = []
        self.decisions = []
        self.action_items = []
        self.memories = []
        self.source_chunks_for_id = {}
        self.meetings_lookup = {}
        self.capture_sessions = []
        self.capture_session_updates = []
        self.capture_session_metadata_updates = []
        self.capture_session_metadata = {}
        self.capture_session_heartbeats = []
        self.failed_capture_sessions = []
        self.finished_capture_sessions = []

    async def find_or_create_person_by_phone(self, phone, name=None):
        self.people.append((phone, name))
        return "person-1"

    async def create_source(
        self,
        source_type,
        *,
        url=None,
        title=None,
        raw_text=None,
        raw_payload=None,
    ):
        self.sources.append(
            {
                "source_type": source_type,
                "url": url,
                "title": title,
                "raw_text": raw_text,
                "raw_payload": raw_payload,
            }
        )
        return "source-1"

    async def create_meeting(
        self,
        gmeet_url,
        *,
        source_id,
        status,
        requested_by_person_id=None,
        summary_short=None,
        summary_long=None,
        started_at=None,
        ended_at=None,
    ):
        self.meetings.append(
            {
                "id": "meeting-1",
                "gmeet_url": gmeet_url,
                "source_id": source_id,
                "status": status,
                "requested_by_person_id": requested_by_person_id,
                "summary_short": summary_short,
                "summary_long": summary_long,
                "started_at": started_at,
                "ended_at": ended_at,
            }
        )
        self.meetings_lookup["meeting-1"] = self.meetings[-1]
        return "meeting-1"

    async def update_meeting_status(self, meeting_id, status, **kwargs):
        self.updates.append({"meeting_id": meeting_id, "status": status, "fields": kwargs})

    async def create_capture_session(
        self,
        meeting_id,
        source_id,
        capture_strategy="chrome_extension",
        stt_provider="deepgram",
    ):
        capture_session = {
            "id": f"capture-{len(self.capture_sessions) + 1}",
            "meeting_id": meeting_id,
            "source_id": source_id,
            "capture_strategy": capture_strategy,
            "stt_provider": stt_provider,
            "status": "scheduled",
        }
        self.capture_sessions.append(capture_session)
        return capture_session

    async def update_capture_session_status(self, capture_session_id, status, metadata=None):
        self.capture_session_updates.append(
            {
                "capture_session_id": capture_session_id,
                "status": status,
                "metadata": metadata,
            }
        )
        return self.capture_session_updates[-1]

    async def heartbeat_capture_session(self, capture_session_id):
        self.capture_session_heartbeats.append(capture_session_id)

    async def update_capture_session_metadata(self, capture_session_id, patch, merge=True):
        self.capture_session_metadata_updates.append(
            {
                "capture_session_id": capture_session_id,
                "patch": patch,
                "merge": merge,
            }
        )
        self.capture_session_metadata = merge_capture_session_metadata(
            self.capture_session_metadata if merge else {},
            patch,
        )
        return {
            "capture_session_id": capture_session_id,
            "metadata": self.capture_session_metadata,
        }

    async def mark_capture_session_failed(
        self,
        capture_session_id,
        error_code,
        error_message,
        metadata=None,
    ):
        self.failed_capture_sessions.append(
            {
                "capture_session_id": capture_session_id,
                "status": "failed",
                "error_code": error_code,
                "error_message": error_message,
                "metadata": metadata,
            }
        )
        return self.failed_capture_sessions[-1]

    async def mark_capture_session_finished(self, capture_session_id):
        self.finished_capture_sessions.append(capture_session_id)
        return {"capture_session_id": capture_session_id, "status": "processed"}

    async def save_transcript_chunks(self, source_id, chunks):
        self.transcript_save_calls.append((source_id, chunks))
        if self.fail_save_chunks:
            raise RuntimeError("transcript persistence failure")
        self.saved_chunks.append((source_id, chunks))
        return len(chunks)

    async def saveTranscriptChunks(self, payload):
        source_id = payload["sourceId"]
        chunks = payload["chunks"]
        return await self.save_transcript_chunks(source_id, chunks)

    async def get_source_chunks_by_source_id(self, source_id):
        return list(self.source_chunks_for_id.get(source_id, []))

    async def getSourceChunksBySourceId(self, source_id):
        return await self.get_source_chunks_by_source_id(source_id)

    async def create_extraction_run(
        self,
        *,
        source_id=None,
        meeting_id=None,
        run_type=None,
        model=None,
        prompt_version=None,
        output_json=None,
        status=None,
        error=None,
    ):
        run_id = f"extract-{len(self.extraction_runs) + 1}"
        self.extraction_runs.append(
            {
                "source_id": source_id,
                "meeting_id": meeting_id,
                "run_type": run_type,
                "model": model,
                "prompt_version": prompt_version,
                "output_json": output_json,
                "status": status,
                "error": error,
            }
        )
        return run_id

    async def createExtractionRun(self, payload):
        return await self.create_extraction_run(
            source_id=payload.get("sourceId") or payload.get("source_id"),
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            run_type=payload.get("runType") or payload.get("run_type"),
            model=payload.get("model"),
            prompt_version=payload.get("promptVersion") or payload.get("prompt_version"),
            output_json=payload.get("outputJson") if "outputJson" in payload else payload.get("output_json"),
            status=payload.get("status"),
            error=payload.get("error"),
        )

    async def create_decision(
        self,
        *,
        meeting_id=None,
        source_id=None,
        title=None,
        decision_text=None,
        rationale=None,
        owner_text=None,
        confidence=None,
    ):
        if not meeting_id or not source_id:
            return None

        if not decision_text:
            return None

        decision_id = f"decision-{len(self.decisions) + 1}"
        self.decisions.append(
            {
                "id": decision_id,
                "meeting_id": meeting_id,
                "source_id": source_id,
                "title": title,
                "decision_text": decision_text,
                "rationale": rationale,
                "owner_text": owner_text,
                "confidence": confidence,
            }
        )
        return decision_id

    async def createDecision(self, payload):
        return await self.create_decision(
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            source_id=payload.get("sourceId") or payload.get("source_id"),
            title=payload.get("title"),
            decision_text=payload.get("decisionText") or payload.get("decision_text"),
            rationale=payload.get("rationale"),
            owner_text=payload.get("ownerText") or payload.get("owner_text"),
            confidence=payload.get("confidence"),
        )

    async def createDecisionsFromExtraction(
        self,
        *,
        meeting_id=None,
        source_id=None,
        decisions=None,
    ):
        # Idempotent behavior expected by extraction flow.
        self.decisions = [
            decision
            for decision in self.decisions
            if decision.get("meeting_id") != meeting_id
        ]

        if not isinstance(decisions, list):
            return 0

        inserted = 0
        for decision in decisions:
            decision_text = (
                (decision.get("decisionText") or "").strip()
                if isinstance(decision, dict)
                else ""
            )
            if not decision_text:
                decision_text = (
                    (decision.get("decision_text") or "").strip()
                    if isinstance(decision, dict)
                    else ""
                )
            if not decision_text:
                decision_text = (
                    (decision.get("decision") or "").strip()
                    if isinstance(decision, dict)
                    else ""
                )
            if not decision_text:
                decision_text = (
                    (decision.get("text") or "").strip()
                    if isinstance(decision, dict)
                    else ""
                )
            if not decision_text:
                continue

            await self.create_decision(
                meeting_id=meeting_id,
                source_id=source_id,
                title=(decision.get("title") or "").strip() if isinstance(decision, dict) else None,
                decision_text=decision_text,
                rationale=(decision.get("rationale") or "").strip()
                if isinstance(decision, dict) and decision.get("rationale") is not None
                else None,
                owner_text=(decision.get("ownerText") or decision.get("owner_text") or "").strip()
                if isinstance(decision, dict)
                and (decision.get("ownerText") or decision.get("owner_text") or decision.get("owner")) is not None
                else None,
                confidence=decision.get("confidence") if isinstance(decision, dict) else None,
            )
            inserted += 1

        return inserted

    async def create_action_item(
        self,
        *,
        meeting_id=None,
        source_id=None,
        task=None,
        owner_text=None,
        due_date=None,
        status=None,
        confidence=None,
    ):
        if not meeting_id or not source_id:
            return None

        if not task:
            return None

        action_id = f"action-{len(self.action_items) + 1}"
        self.action_items.append(
            {
                "id": action_id,
                "meeting_id": meeting_id,
                "source_id": source_id,
                "task": task,
                "owner_text": owner_text,
                "due_date": due_date,
                "status": status,
                "confidence": confidence,
            }
        )
        return action_id

    async def createActionItem(self, payload):
        return await self.create_action_item(
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            source_id=payload.get("sourceId") or payload.get("source_id"),
            task=payload.get("task") or payload.get("task_text") or payload.get("text"),
            owner_text=payload.get("ownerText") or payload.get("owner_text") or payload.get("owner"),
            due_date=payload.get("dueDate") or payload.get("due_date"),
            status=payload.get("status", "open"),
            confidence=payload.get("confidence"),
        )

    async def createActionItemsFromExtraction(
        self,
        *,
        meeting_id=None,
        source_id=None,
        action_items=None,
    ):
        self.action_items = [
            item
            for item in self.action_items
            if item.get("meeting_id") != meeting_id
        ]

        if not isinstance(action_items, list):
            return 0

        inserted = 0
        for item in action_items:
            task = (
                (item.get("task") or item.get("task_text") or item.get("taskText") or "").strip()
                if isinstance(item, dict)
                else ""
            )
            if not task:
                continue

            await self.create_action_item(
                meeting_id=meeting_id,
                source_id=source_id,
                task=task,
                owner_text=(item.get("ownerText") or item.get("owner_text") or item.get("owner") or "").strip()
                if isinstance(item, dict)
                and (item.get("ownerText") or item.get("owner_text") or item.get("owner")) is not None
                else None,
                due_date=(item.get("dueDate") or item.get("due_date") or "").strip()
                if isinstance(item, dict)
                and (item.get("dueDate") or item.get("due_date")) is not None
                else None,
                status=(item.get("status") or "open") if isinstance(item, dict) else "open",
                confidence=item.get("confidence") if isinstance(item, dict) else None,
            )
            inserted += 1

        return inserted

    async def create_memory(
        self,
        *,
        meeting_id=None,
        source_id=None,
        memory_type=None,
        content=None,
        importance=None,
        confidence=None,
    ):
        if not meeting_id or not source_id:
            return None

        if not content:
            return None

        memory_id = f"memory-{len(self.memories) + 1}"
        self.memories.append(
            {
                "id": memory_id,
                "meeting_id": meeting_id,
                "source_id": source_id,
                "memory_type": memory_type,
                "content": content,
                "importance": importance,
                "confidence": confidence,
            }
        )
        return memory_id

    async def createMemory(self, payload):
        return await self.create_memory(
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            source_id=payload.get("sourceId") or payload.get("source_id"),
            memory_type=payload.get("memoryType") or payload.get("memory_type"),
            content=payload.get("content"),
            importance=payload.get("importance"),
            confidence=payload.get("confidence"),
        )

    async def createMemoriesFromExtraction(
        self,
        *,
        meeting_id=None,
        source_id=None,
        memories=None,
    ):
        self.memories = [
            memory
            for memory in self.memories
            if memory.get("meeting_id") != meeting_id
        ]

        if not isinstance(memories, list):
            return 0

        inserted = 0
        for memory in memories:
            memory_content = (
                memory.get("content") if isinstance(memory, dict) else None
            )
            if not memory_content or not str(memory_content).strip():
                # Legacy payloads may use different keys; keep this simple and
                # strict for tests.
                continue

            memory_type = (
                memory.get("memoryType") or memory.get("memory_type") or "important_fact"
            )
            importance = memory.get("importance") or "medium"
            confidence = memory.get("confidence")

            if isinstance(importance, str):
                importance = importance.lower()
                if importance not in {"low", "medium", "high"}:
                    importance = "medium"
            else:
                importance = str(importance)
                if importance not in {"low", "medium", "high"}:
                    importance = "medium"

            await self.create_memory(
                meeting_id=meeting_id,
                source_id=source_id,
                memory_type=memory_type,
                content=(str(memory_content).strip()),
                importance=importance,
                confidence=confidence,
            )
            inserted += 1

        return inserted

    async def get_memories_by_meeting_id(self, meeting_id):
        return [memory for memory in self.memories if memory.get("meeting_id") == meeting_id]

    async def getMemoriesByMeetingId(self, meeting_id):
        return await self.get_memories_by_meeting_id(meeting_id)

    async def get_recent_memories(self, limit=20):
        return list(reversed(self.memories))[:limit]

    async def getRecentMemories(self, limit=20):
        return await self.get_recent_memories(limit=limit)

    async def get_memories_by_type(self, memory_type, limit=20):
        if not memory_type:
            return []
        filtered = [
            memory
            for memory in self.memories
            if memory.get("memory_type") == memory_type
        ]
        return list(reversed(filtered))[:limit]

    async def getMemoriesByType(self, memory_type, limit=20):
        return await self.get_memories_by_type(memory_type, limit=limit)

    async def get_action_items_by_meeting_id(self, meeting_id):
        return [item for item in self.action_items if item.get("meeting_id") == meeting_id]

    async def getActionItemsByMeetingId(self, meeting_id):
        return await self.get_action_items_by_meeting_id(meeting_id)

    async def get_recent_action_items(self, limit=20):
        return list(reversed(self.action_items))[:limit]

    async def getRecentActionItems(self, limit=20):
        return await self.get_recent_action_items(limit=limit)

    async def get_decisions_by_meeting_id(self, meeting_id):
        return [decision for decision in self.decisions if decision.get("meeting_id") == meeting_id]

    async def getDecisionsByMeetingId(self, meeting_id):
        return await self.get_decisions_by_meeting_id(meeting_id)

    async def get_recent_decisions(self, limit=20):
        return list(reversed(self.decisions))[:limit]

    async def getRecentDecisions(self, limit=20):
        return await self.get_recent_decisions(limit=limit)

    async def get_meeting_by_id(self, meeting_id):
        meeting = self.meetings_lookup.get(meeting_id)
        if meeting:
            return meeting
        if self.meetings:
            for created in self.meetings:
                if created.get("id") == meeting_id:
                    return created
        return None


class FakeCompletions:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.responses:
            return FakeResponse(self.responses.pop(0))
        return FakeResponse("General answer from Orbit.")


class FakeChat:
    def __init__(self, responses=None):
        self.completions = FakeCompletions(responses=responses)


class FakeOpenAIClient:
    def __init__(self, responses=None):
        self.chat = FakeChat(responses=responses)


class FakeLiveSTT:
    def __init__(self):
        self.available = True
        self.sessions = []
        self.stopped = []

    async def add_captions(self, state, captions):
        return None

    async def get_or_create(self, state, audio_format=None):
        session = FakeLiveSTTSession()
        self.sessions.append((state, audio_format, session))
        return session

    async def stop(self, session_id):
        self.stopped.append(session_id)
        return None


class FakeLiveSTTSession:
    def __init__(self):
        self.audio_chunks = []
        self.keepalives = 0

    async def send_audio(self, chunk):
        self.audio_chunks.append(chunk)

    async def send_keepalive(self):
        self.keepalives += 1
        return True


class FakeWebSocket:
    def __init__(self, messages, query_params=None):
        self.messages = list(messages)
        self.query_params = query_params or {}
        self.accepted = False
        self.sent_json = []
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    async def receive(self):
        if not self.messages:
            raise RuntimeError("no more messages")
        return self.messages.pop(0)

    async def send_json(self, payload):
        self.sent_json.append(payload)


class FakeServerAudioSinkProcess:
    def __init__(self, pid=0, returncode=0):
        self.pid = pid
        self.returncode = returncode
        self.returncode_set = returncode
        self.wait_calls = 0

    async def wait(self):
        self.wait_calls += 1
        return self.returncode_set


class FakeServerAudioSinkHandle:
    def __init__(self, session_id, capture_session_id, sink_name, pid=12345):
        self.session_id = session_id
        self.capture_session_id = capture_session_id
        self.sink_name = sink_name
        self.module_id = f"mod-{session_id}"
        self.ffmpeg_process = FakeServerAudioSinkProcess(pid=pid)
        self.stop_calls = 0

    async def stop(self):
        self.stop_calls += 1


class FakeStdout:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self, _size):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def pcm16_chunk(amplitude, sample_count=1600):
    return struct.pack(f"<{sample_count}h", *([amplitude] * sample_count))


def build_service(memory=None, meeting_store=None):
    service = OrbitWhatsAppService.__new__(OrbitWhatsAppService)
    service.twilio_allowed_from = "whatsapp:+15551234567"
    service.model_name = "test-model"
    service.openai_client = FakeOpenAIClient()
    service.max_parallel_meetings = 3
    service.active_sessions = {}
    service.pending_meeting_starts = set()
    service.lock = asyncio.Lock()
    service.memory = memory or FakeMemory()
    service.meeting_store = meeting_store or FakeMeetingStore()
    service.live_stt = FakeLiveSTT()
    return service
