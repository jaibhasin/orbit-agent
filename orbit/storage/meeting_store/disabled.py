# mypy: disable-error-code="arg-type,no-redef"
from __future__ import annotations

class DisabledMeetingStore:
    async def find_or_create_person_by_phone(self, phone: str, name: str | None = None) -> str | None:
        return None

    async def create_source(
        self,
        source_type: str,
        *,
        url: str | None = None,
        title: str | None = None,
        raw_text: str | None = None,
        raw_payload: str | None = None,
    ) -> str | None:
        return None

    async def create_meeting(
        self,
        gmeet_url: str,
        *,
        source_id: str | None,
        status: str,
        requested_by_person_id: str | None = None,
        summary_short: str | None = None,
        summary_long: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> str | None:
        return None

    async def update_meeting_status(
        self,
        meeting_id: str,
        status: str,
        *,
        started_at: str | None = None,
        ended_at: str | None = None,
        summary_short: str | None = None,
        summary_long: str | None = None,
        overwrite_summary: bool = False,
    ) -> None:
        return None

    async def create_capture_session(
        self,
        meeting_id: str,
        source_id: str | None,
        capture_strategy: str = "chrome_extension",
        stt_provider: str | None = "deepgram",
    ) -> dict | None:
        return None

    async def update_capture_session_status(
        self,
        capture_session_id: str,
        status: str,
        metadata: dict | None = None,
    ) -> dict | None:
        return None

    async def update_capture_session_metadata(
        self,
        capture_session_id: str,
        patch: dict,
        merge: bool = True,
    ) -> dict | None:
        return None

    async def heartbeat_capture_session(self, capture_session_id: str) -> None:
        return None

    async def mark_capture_session_failed(
        self,
        capture_session_id: str,
        error_code: str,
        error_message: str,
        metadata: dict | None = None,
    ) -> dict | None:
        return None

    async def mark_capture_session_finished(self, capture_session_id: str) -> dict | None:
        return None

    async def get_latest_capture_session_for_meeting(self, meeting_id: str) -> dict | None:
        return None

    async def save_transcript_chunks(self, source_id: str, chunks: list[dict]) -> int:
        return 0

    async def saveTranscriptChunks(self, payload: dict) -> int:
        source_id = payload.get("sourceId") or payload.get("source_id")
        chunks = payload.get("chunks") or []
        return await self.save_transcript_chunks(source_id, chunks)

    async def get_source_chunks_by_source_id(self, source_id: str):
        return []

    async def getSourceChunksBySourceId(self, source_id: str):
        return await self.get_source_chunks_by_source_id(source_id)

    async def create_visual_frame(self, **kwargs) -> str | None:
        return None

    async def get_visual_frames_by_meeting_id(self, meeting_id: str):
        return []

    async def create_extraction_run(
        self,
        *,
        source_id: str | None = None,
        meeting_id: str | None = None,
        run_type: str = "full_meeting_extraction",
        model: str | None = None,
        prompt_version: str | None = None,
        output_json: dict | list | None = None,
        status: str = "success",
        error: str | None = None,
    ):
        return None

    async def createExtractionRun(self, payload: dict):
        if not isinstance(payload, dict):
            return None

        return await self.create_extraction_run(
            source_id=payload.get("sourceId") or payload.get("source_id"),
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            run_type=payload.get("runType") or payload.get("run_type", "full_meeting_extraction"),
            model=payload.get("model"),
            prompt_version=payload.get("promptVersion") or payload.get("prompt_version"),
            output_json=payload.get("outputJson") if "outputJson" in payload else payload.get("output_json"),
            status=payload.get("status", "success"),
            error=payload.get("error"),
        )

    async def get_meeting_by_id(self, meeting_id: str):
        return None

    async def create_decision(
        self,
        *,
        meeting_id: str | None = None,
        source_id: str | None = None,
        title: str | None = None,
        decision_text: str | None = None,
        rationale: str | None = None,
        owner_text: str | None = None,
        confidence: float | None = None,
    ) -> str | None:
        return None

    async def createDecision(self, payload: dict):
        if not isinstance(payload, dict):
            return None

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
        meeting_id: str | None = None,
        source_id: str | None = None,
        decisions=None,
    ) -> int:
        return 0

    async def create_action_item(
        self,
        *,
        meeting_id: str | None = None,
        source_id: str | None = None,
        task: str | None = None,
        owner_text: str | None = None,
        due_date: str | None = None,
        status: str = "open",
        confidence: float | None = None,
    ) -> str | None:
        return None

    async def createActionItem(self, payload: dict):
        if not isinstance(payload, dict):
            return None

        return await self.create_action_item(
            meeting_id=payload.get("meetingId") or payload.get("meeting_id"),
            source_id=payload.get("sourceId") or payload.get("source_id"),
            task=payload.get("task"),
            owner_text=payload.get("ownerText") or payload.get("owner_text"),
            due_date=payload.get("dueDate") or payload.get("due_date"),
            status=payload.get("status", "open"),
            confidence=payload.get("confidence"),
        )

    async def createActionItemsFromExtraction(
        self,
        *,
        meeting_id: str | None = None,
        source_id: str | None = None,
        action_items=None,
    ) -> int:
        return 0

    async def create_memory(
        self,
        *,
        meeting_id: str | None = None,
        source_id: str | None = None,
        memory_type: str | None = None,
        content: str | None = None,
        importance: str | None = None,
        confidence: float | None = None,
    ) -> str | None:
        return None

    async def createMemory(self, payload: dict):
        if not isinstance(payload, dict):
            return None

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
        meeting_id: str | None = None,
        source_id: str | None = None,
        memories=None,
    ) -> int:
        return 0

    async def get_memories_by_meeting_id(self, meeting_id: str):
        return []

    async def getMemoriesByMeetingId(self, meeting_id: str):
        return await self.get_memories_by_meeting_id(meeting_id)

    async def get_recent_memories(self, limit: int = 20):
        return []

    async def getRecentMemories(self, limit: int = 20):
        return await self.get_recent_memories(limit=limit)

    async def get_memories_by_type(self, memory_type: str, limit: int = 20):
        return []

    async def getMemoriesByType(self, memory_type: str, limit: int = 20):
        return await self.get_memories_by_type(memory_type, limit=limit)

    async def get_decisions_by_meeting_id(self, meeting_id: str):
        return []

    async def getDecisionsByMeetingId(self, meeting_id: str):
        return await self.get_decisions_by_meeting_id(meeting_id)

    async def get_recent_decisions(self, limit: int = 20):
        return []

    async def getRecentDecisions(self, limit: int = 20):
        return await self.get_recent_decisions(limit=limit)

    async def get_action_items_by_meeting_id(self, meeting_id: str):
        return []

    async def getActionItemsByMeetingId(self, meeting_id: str):
        return await self.get_action_items_by_meeting_id(meeting_id)

    async def get_recent_action_items(self, limit: int = 20):
        return []

    async def getRecentActionItems(self, limit: int = 20):
        return await self.get_recent_action_items(limit=limit)
