from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


DEFAULT_PCM16_SAMPLE_RATE = 16000
DEFAULT_SILENCE_RMS_THRESHOLD = 400
DEFAULT_PRE_ROLL_MS = 400
DEFAULT_POST_ROLL_MS = 900
DEFAULT_SILENCE_DROP_AFTER_MS = 1000


def pcm16_rms(chunk: bytes) -> float:
    sample_count = len(chunk) // 2
    if sample_count == 0:
        return 0.0

    total = 0
    for offset in range(0, sample_count * 2, 2):
        sample = int.from_bytes(chunk[offset : offset + 2], byteorder="little", signed=True)
        total += sample * sample
    return math.sqrt(total / sample_count)


def is_pcm16_silent(chunk: bytes, threshold: float = DEFAULT_SILENCE_RMS_THRESHOLD) -> bool:
    return pcm16_rms(chunk) < threshold


@dataclass(frozen=True)
class SilenceGateResult:
    chunks_to_forward: tuple[bytes, ...]
    dropped_silence_bytes: int
    rms: float
    is_silent: bool
    silence_gated: bool


class PCM16SilenceGate:
    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_PCM16_SAMPLE_RATE,
        rms_threshold: float = DEFAULT_SILENCE_RMS_THRESHOLD,
        pre_roll_ms: int = DEFAULT_PRE_ROLL_MS,
        post_roll_ms: int = DEFAULT_POST_ROLL_MS,
        silence_drop_after_ms: int = DEFAULT_SILENCE_DROP_AFTER_MS,
    ):
        self.sample_rate = max(int(sample_rate), 1)
        self.rms_threshold = float(rms_threshold)
        self.pre_roll_ms = max(int(pre_roll_ms), 0)
        self.post_roll_ms = max(int(post_roll_ms), 0)
        self.silence_drop_after_ms = max(int(silence_drop_after_ms), self.post_roll_ms)
        self.speech_active = False
        self.silence_gated = False
        self._continuous_silence_ms = 0.0
        self._pre_roll: deque[tuple[bytes, float]] = deque()
        self._pre_roll_duration_ms = 0.0

    def process(self, chunk: bytes) -> SilenceGateResult:
        rms = pcm16_rms(chunk)
        silent = rms < self.rms_threshold
        chunk_duration_ms = self._duration_ms(chunk)
        dropped_bytes = 0

        if not silent:
            dropped_bytes += self._trim_pre_roll()
            chunks_to_forward = tuple(buffered for buffered, _ in self._pre_roll) + (chunk,)
            self._clear_pre_roll()
            self.speech_active = True
            self.silence_gated = False
            self._continuous_silence_ms = 0.0
            return SilenceGateResult(
                chunks_to_forward=chunks_to_forward,
                dropped_silence_bytes=dropped_bytes,
                rms=rms,
                is_silent=False,
                silence_gated=False,
            )

        self._continuous_silence_ms += chunk_duration_ms
        if self.speech_active and self._continuous_silence_ms <= self.post_roll_ms:
            return SilenceGateResult(
                chunks_to_forward=(chunk,),
                dropped_silence_bytes=0,
                rms=rms,
                is_silent=True,
                silence_gated=False,
            )

        if self.speech_active:
            self.speech_active = False
        self._append_pre_roll(chunk, chunk_duration_ms)
        if self._continuous_silence_ms > self.silence_drop_after_ms:
            self.silence_gated = True
            dropped_bytes += self._trim_pre_roll()

        return SilenceGateResult(
            chunks_to_forward=(),
            dropped_silence_bytes=dropped_bytes,
            rms=rms,
            is_silent=True,
            silence_gated=self.silence_gated,
        )

    def finish(self) -> int:
        dropped_bytes = sum(len(chunk) for chunk, _ in self._pre_roll)
        self._clear_pre_roll()
        return dropped_bytes

    def _duration_ms(self, chunk: bytes) -> float:
        return (len(chunk) // 2) * 1000 / self.sample_rate

    def _append_pre_roll(self, chunk: bytes, duration_ms: float) -> None:
        self._pre_roll.append((chunk, duration_ms))
        self._pre_roll_duration_ms += duration_ms

    def _trim_pre_roll(self) -> int:
        dropped_bytes = 0
        while self._pre_roll and self._pre_roll_duration_ms > self.pre_roll_ms:
            chunk, duration_ms = self._pre_roll.popleft()
            excess_ms = self._pre_roll_duration_ms - self.pre_roll_ms
            if duration_ms <= excess_ms:
                dropped_bytes += len(chunk)
                self._pre_roll_duration_ms -= duration_ms
                continue

            samples_to_drop = min(
                len(chunk) // 2,
                max(1, math.ceil(excess_ms * self.sample_rate / 1000)),
            )
            bytes_to_drop = samples_to_drop * 2
            remaining_chunk = chunk[bytes_to_drop:]
            remaining_duration_ms = self._duration_ms(remaining_chunk)
            dropped_bytes += bytes_to_drop
            self._pre_roll_duration_ms -= duration_ms - remaining_duration_ms
            if remaining_chunk:
                self._pre_roll.appendleft((remaining_chunk, remaining_duration_ms))
            break
        return dropped_bytes

    def _clear_pre_roll(self) -> None:
        self._pre_roll.clear()
        self._pre_roll_duration_ms = 0.0
