"""Transcribe an isolated bass stem into timed tablature."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .audio import read_mono
from .pitch import SAMPLE_RATE, track_pitch
from .tab import STRINGS, notes_from_track


def transcribe_bass(path: Path) -> dict:
    samples = read_mono(path, SAMPLE_RATE)
    duration = float(len(samples) / SAMPLE_RATE) if len(samples) else 0.0
    times, midis, confidence = track_pitch(samples, SAMPLE_RATE)
    notes = notes_from_track(times, midis, confidence)
    return {
        "duration": round(duration, 3),
        "tuning": [{"name": name, "midi": midi} for name, midi in STRINGS],
        "notes": notes,
        "tempo": estimate_tempo(notes, duration),
    }


def estimate_tempo(notes: list[dict], duration: float) -> float | None:
    if len(notes) < 8 or duration < 4:
        return None
    hop = 0.02
    bins = int(duration / hop) + 1
    envelope = np.zeros(bins)
    for note in notes:
        envelope[min(bins - 1, int(note["start"] / hop))] = 1.0
    correlation = np.correlate(envelope, envelope, mode="full")
    center = len(correlation) // 2
    min_lag = int(0.3 / hop)
    max_lag = min(int(1.0 / hop), len(correlation) - center - 1)
    if max_lag <= min_lag:
        return None
    region = correlation[center + min_lag : center + max_lag]
    if float(region.max()) < 3:
        return None
    lag = min_lag + int(np.argmax(region))
    return round(60.0 / (lag * hop), 1)
