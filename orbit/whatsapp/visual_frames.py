from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from orbit.core import env_int, log, now_iso


VISUAL_ANALYSIS_SYSTEM_PROMPT = """You analyze a single Google Meet shared-screen frame.
Return only valid JSON with these keys:
- type: slide, document, spreadsheet, code, dashboard, diagram, browser, or other
- title: short visible title or null
- key_points: at most five concise strings
- visible_text: only important readable text, kept concise
- summary: one concise sentence describing the useful meeting evidence
Do not infer facts that are not visible in the frame."""

DEFAULT_MAX_FRAME_BYTES = 900_000
DEFAULT_MAX_IN_FLIGHT = 2


class VisualFrameMixin:
    async def schedule_visual_frame_analysis(self, active, payload: dict[str, Any]) -> bool:
        if not active or not active.meeting_id:
            return False
        tasks = active.visual_analysis_tasks
        tasks.difference_update(task for task in tasks if task.done())
        if len(tasks) >= env_int("ORBIT_VISUAL_MAX_IN_FLIGHT", DEFAULT_MAX_IN_FLIGHT):
            self._visual_health(active)["frames_dropped_busy"] += 1
            return False

        task = __import__("asyncio").create_task(self._analyze_and_store_visual_frame(active, payload))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return True

    async def _analyze_and_store_visual_frame(self, active, payload: dict[str, Any]) -> None:
        health = self._visual_health(active)
        health["frames_received"] += 1
        try:
            image_data_url, image_bytes, mime_type = self._decode_visual_data_url(
                payload.get("image_data_url")
            )
            timestamp_ms = max(0, int(payload.get("timestamp_ms") or 0))
            change_score = self._optional_float(payload.get("change_score"))
            content_hash = hashlib.sha256(image_bytes).hexdigest()
            analysis = await self._call_visual_model(image_data_url)
            summary = str(analysis.get("summary") or "").strip()
            if not summary:
                summary = self._fallback_visual_summary(analysis)

            await self.meeting_store.create_visual_frame(
                meeting_id=active.meeting_id,
                source_id=active.source_id,
                captured_at_ms=timestamp_ms,
                content_hash=content_hash,
                mime_type=mime_type,
                width=self._optional_int(payload.get("width")),
                height=self._optional_int(payload.get("height")),
                change_score=change_score,
                summary=summary,
                analysis_json=analysis,
            )
            health["frames_analyzed"] += 1
            health["last_frame_at"] = now_iso()
            health["last_error"] = None
            await self._update_capture_session_metadata(active, {"visual": dict(health)})
        except Exception as error:
            health["frames_failed"] += 1
            health["last_error"] = str(error)[:300]
            log(
                f"Visual frame analysis failed for Meet {active.state.meeting_code}: {error}",
                active.session_id,
                level="error",
            )
            await self._update_capture_session_metadata(active, {"visual": dict(health)})

    async def _call_visual_model(self, image_data_url: str) -> dict[str, Any]:
        response = await self.openai_client.chat.completions.create(
            model=os.environ.get("ORBIT_VISUAL_MODEL") or self.model_name,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": VISUAL_ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract only the useful evidence visible in this changed shared-screen frame.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_url, "detail": "low"},
                        },
                    ],
                },
            ],
        )
        raw = (response.choices[0].message.content or "").strip() if response.choices else ""
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("Visual model output must be a JSON object.")
        parsed["key_points"] = [
            str(item).strip()
            for item in (parsed.get("key_points") or [])
            if str(item).strip()
        ][:5]
        return parsed

    @staticmethod
    def _decode_visual_data_url(value: Any) -> tuple[str, bytes, str]:
        if not isinstance(value, str) or not value.startswith("data:image/"):
            raise ValueError("Visual frame must be an image data URL.")
        header, separator, encoded = value.partition(",")
        if not separator or ";base64" not in header:
            raise ValueError("Visual frame must use base64 encoding.")
        mime_type = header[5:].split(";", 1)[0].lower()
        if mime_type not in {"image/jpeg", "image/webp"}:
            raise ValueError("Visual frame must be JPEG or WebP.")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except Exception as error:
            raise ValueError("Visual frame contains invalid base64 data.") from error
        max_bytes = env_int("ORBIT_VISUAL_MAX_FRAME_BYTES", DEFAULT_MAX_FRAME_BYTES)
        if not image_bytes or len(image_bytes) > max_bytes:
            raise ValueError(f"Visual frame must be between 1 and {max_bytes} bytes.")
        return value, image_bytes, mime_type

    @staticmethod
    def _visual_health(active) -> dict[str, Any]:
        return active.capture_health_metadata.setdefault(
            "visual",
            {
                "frames_received": 0,
                "frames_analyzed": 0,
                "frames_failed": 0,
                "frames_dropped_busy": 0,
                "last_frame_at": None,
                "last_error": None,
            },
        )

    @staticmethod
    def _fallback_visual_summary(analysis: dict[str, Any]) -> str:
        title = str(analysis.get("title") or "").strip()
        points = [str(item).strip() for item in (analysis.get("key_points") or []) if str(item).strip()]
        return ": ".join(part for part in (title, "; ".join(points[:3])) if part) or "Changed shared-screen frame."

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
