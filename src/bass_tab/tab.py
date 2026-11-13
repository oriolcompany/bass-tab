"""Turn a bass pitch track into 4-string tablature."""

from __future__ import annotations

import numpy as np

# Standard bass, highest string first, the way tab is written.
STRINGS: tuple[tuple[str, int], ...] = (
    ("G", 43),
    ("D", 38),
    ("A", 33),
    ("E", 28),
)
MAX_FRET = 20
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def candidates(midi: int) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for index, (_name, open_midi) in enumerate(STRINGS):
        fret = midi - open_midi
        if 0 <= fret <= MAX_FRET:
            found.append((index, fret))
    return found


def assign_positions(midis: list[int]) -> list[tuple[int, int]]:
    """Pick a fret and string per note, staying in a comfortable position."""
    options = [candidates(midi) for midi in midis]
    if any(not choice for choice in options):
        missing = [midi for midi, choice in zip(midis, options) if not choice]
        raise ValueError(f"Nota fuera del mástil: {missing[0]}")
    count = len(options)
    costs: list[list[float]] = []
    previous: list[list[int]] = []
    for index, choice in enumerate(options):
        step_costs: list[float] = []
        step_back: list[int] = []
        for string, fret in choice:
            if index == 0:
                step_costs.append(_place_cost(fret))
                step_back.append(-1)
                continue
            best = 1e12
            best_index = 0
            for back, (prev_string, prev_fret) in enumerate(options[index - 1]):
                jump = abs(fret - prev_fret)
                switch = 0.0 if prev_string == string else 1.6
                stretch = max(0, jump - 4) * 0.6
                total = costs[index - 1][back] + switch + jump * 0.22 + stretch + _place_cost(fret) * 0.35
                if total < best:
                    best = total
                    best_index = back
            step_costs.append(best)
            step_back.append(best_index)
        costs.append(step_costs)
        previous.append(step_back)
    chosen = int(np.argmin(costs[-1]))
    positions = [options[-1][chosen]]
    for index in range(count - 1, 0, -1):
        chosen = previous[index][chosen]
        positions.append(options[index - 1][chosen])
    positions.reverse()
    return positions


def notes_from_track(
    times: np.ndarray,
    midis: np.ndarray,
    confidence: np.ndarray,
    min_duration: float = 0.07,
    min_confidence: float = 0.8,
) -> list[dict]:
    smoothed = _smooth(midis, confidence, min_confidence)
    grouped = _group(times, smoothed, min_duration)
    if not grouped:
        return []
    positions = assign_positions([note["midi"] for note in grouped])
    rendered: list[dict] = []
    for note, (string, fret) in zip(grouped, positions):
        name, open_midi = STRINGS[string]
        rendered.append(
            {
                "start": round(note["start"], 4),
                "duration": round(note["duration"], 4),
                "midi": note["midi"],
                "name": note_name(note["midi"]),
                "string": string,
                "stringName": name,
                "fret": fret,
                "openMidi": open_midi,
            }
        )
    return rendered


def _place_cost(fret: int) -> float:
    if fret <= 5:
        return fret * 0.15
    if fret <= 9:
        return 0.8 + (fret - 5) * 0.25
    return 2.0 + (fret - 9) * 0.45


def _smooth(midis: np.ndarray, confidence: np.ndarray, min_confidence: float) -> np.ndarray:
    cleaned = np.array(midis, copy=True)
    cleaned[confidence < min_confidence] = 0
    for index in range(1, len(cleaned) - 1):
        if cleaned[index] == 0:
            continue
        window = [int(cleaned[pos]) for pos in (index - 1, index, index + 1) if cleaned[pos] != 0]
        if len(window) >= 2:
            cleaned[index] = int(np.median(window))
    return cleaned


def _group(times: np.ndarray, midis: np.ndarray, min_duration: float) -> list[dict]:
    if len(times) == 0:
        return []
    hop = float(times[1] - times[0]) if len(times) > 1 else 0.016
    notes: list[dict] = []
    start_index: int | None = None
    current = 0
    for index, midi in enumerate(midis):
        midi = int(midi)
        if midi <= 0:
            if start_index is not None:
                _close(notes, times, start_index, index, current, hop, min_duration)
                start_index = None
            continue
        if start_index is None:
            start_index = index
            current = midi
        elif midi != current:
            _close(notes, times, start_index, index, current, hop, min_duration)
            start_index = index
            current = midi
    if start_index is not None:
        _close(notes, times, start_index, len(midis), current, hop, min_duration)
    merged: list[dict] = []
    for note in notes:
        if (
            merged
            and merged[-1]["midi"] == note["midi"]
            and note["start"] - (merged[-1]["start"] + merged[-1]["duration"]) < 0.05
        ):
            end = note["start"] + note["duration"]
            merged[-1]["duration"] = end - merged[-1]["start"]
        else:
            merged.append(note)
    return [note for note in merged if note["duration"] >= min_duration]


def _close(
    notes: list[dict],
    times: np.ndarray,
    start_index: int,
    end_index: int,
    midi: int,
    hop: float,
    min_duration: float,
) -> None:
    start = float(times[start_index]) - hop / 2
    end = float(times[end_index - 1]) + hop / 2
    duration = end - start
    if duration < min_duration * 0.45:
        return
    notes.append({"start": max(0.0, start), "duration": duration, "midi": midi})
