"""Harmonic tones so the pitch tracker locks onto the fundamental."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def write_bass(path: Path, notes: list[tuple[float, float, float]], rate: int = 16000) -> None:
    """notes are (frequency Hz, seconds, amplitude). Silence is frequency 0."""
    frames = bytearray()
    for frequency, seconds, amplitude in notes:
        count = int(seconds * rate)
        for index in range(count):
            if frequency <= 0 or amplitude <= 0:
                sample = 0
            else:
                t = index / rate
                value = (
                    math.sin(2 * math.pi * frequency * t)
                    + 0.45 * math.sin(2 * math.pi * 2 * frequency * t)
                    + 0.2 * math.sin(2 * math.pi * 3 * frequency * t)
                )
                sample = int(max(-1.0, min(1.0, amplitude * value / 1.65)) * 32767)
            frames += struct.pack("<hh", sample, sample)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
