"""Simple energy-based Voice Activity Detection for streaming STT."""
from __future__ import annotations

import array
from dataclasses import dataclass, field
from typing import List


@dataclass
class StreamingVAD:
    sample_rate: int = 16_000
    frame_ms: int = 30
    speech_ratio: float = 2.5          # ~3 dB above noise floor = speech
    hangover_ms: int = 600             # be more patient between words
    min_utterance_ms: int = 250
    max_utterance_ms: int = 15_000
    min_speech_floor: float = 80.0     # absolute energy floor below which
                                        # we treat as silence regardless of
                                        # noise_floor ratio (catches very
                                        # quiet rooms where everything reads
                                        # as "above noise floor")

    # internal
    _frame_bytes: int = field(init=False, default=0)
    _noise_floor: float = field(init=False, default=300.0)
    _in_speech: bool = field(init=False, default=False)
    _last_speech_ms: int = field(init=False, default=0)
    _clock_ms: int = field(init=False, default=0)
    _buffer: bytearray = field(init=False, default_factory=bytearray)
    _carry: bytearray = field(init=False, default_factory=bytearray)  # partial frames

    def __post_init__(self) -> None:
        # 16-bit mono
        self._frame_bytes = int(self.sample_rate * self.frame_ms / 1000) * 2

    def feed(self, pcm: bytes) -> List[bytes]:
        """Ingest raw PCM. Returns any finalized utterances (bytes)."""
        finalized: List[bytes] = []
        if not pcm:
            return finalized

        self._carry.extend(pcm)
        # Split into frames
        while len(self._carry) >= self._frame_bytes:
            frame = bytes(self._carry[: self._frame_bytes])
            del self._carry[: self._frame_bytes]
            self._clock_ms += self.frame_ms

            energy = _rms(frame)
            is_speech = (
                energy > self.min_speech_floor
                and energy > self._noise_floor * self.speech_ratio
            )

            if is_speech:
                if not self._in_speech:
                    self._in_speech = True
                    self._buffer.clear()
                self._buffer.extend(frame)
                self._last_speech_ms = self._clock_ms
                if len(self._buffer) >= int(self.sample_rate * 2 * self.max_utterance_ms / 1000):
                    utt = bytes(self._buffer)
                    self._buffer.clear()
                    self._in_speech = False
                    finalized.append(utt)
            else:
                # decay noise floor slowly on silence
                self._noise_floor = self._noise_floor * 0.98 + energy * 0.02
                if self._in_speech:
                    self._buffer.extend(frame)  # include hangover tail
                    if self._clock_ms - self._last_speech_ms >= self.hangover_ms:
                        self._in_speech = False
                        if len(self._buffer) >= int(self.sample_rate * 2 * self.min_utterance_ms / 1000):
                            finalized.append(bytes(self._buffer))
                        self._buffer.clear()
        return finalized

    def flush(self) -> bytes:
        """Return any in-progress speech buffer, clear state. Call at end-of-window."""
        if len(self._buffer) >= int(self.sample_rate * 2 * self.min_utterance_ms / 1000):
            out = bytes(self._buffer)
        else:
            out = b""
        self._buffer.clear()
        self._carry.clear()
        self._in_speech = False
        return out


def _rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return 0.0
    s = 0
    for v in samples:
        s += v * v
    return (s / len(samples)) ** 0.5
