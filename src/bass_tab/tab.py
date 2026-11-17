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


def transpose_notes(notes: list[dict], semitones: int) -> list[dict]:
    """Shift the bass line, then finger it again. A phrase that leaves the neck moves by octaves."""
    if not notes:
        return []
    requested = [int(note["midi"]) + semitones for note in notes]
    sounding = arrange_midis(requested, _phrase_breaks(notes))
    positions = assign_positions(sounding)
    rendered: list[dict] = []
    for note, midi, asked, (string, fret) in zip(notes, sounding, requested, positions):
        name, open_midi = STRINGS[string]
        rendered.append(
            {
                "start": note["start"],
                "duration": note["duration"],
                "midi": midi,
                "name": note_name(midi),
                "string": string,
                "stringName": name,
                "fret": fret,
                "openMidi": open_midi,
                "shifted": (midi - asked) // 12,
            }
        )
    return rendered


def arrange_midis(midis: list[int], breaks: list[bool] | None = None) -> list[int]:
    """Move a whole phrase by octaves when several notes leave the neck; otherwise fix the outliers."""
    if not midis:
        return []
    breaks = breaks or [False] * len(midis)
    sounding: list[int] = []
    phrase: list[int] = []
    for midi, new_phrase in zip(midis, breaks):
        if new_phrase and phrase:
            sounding.extend(_arrange_phrase(phrase))
            phrase = []
        phrase.append(midi)
    if phrase:
        sounding.extend(_arrange_phrase(phrase))
    return sounding


def _phrase_breaks(notes: list[dict]) -> list[bool]:
    breaks = [False]
    for previous, note in zip(notes, notes[1:]):
        gap = float(note["start"]) - (float(previous["start"]) + float(previous["duration"]))
        breaks.append(gap > 0.5)
    return breaks


def _arrange_phrase(midis: list[int]) -> list[int]:
    best_shift = 0
    best_cost: float | None = None
    for shift in (0, 1, -1, 2, -2):
        moved = [midi + 12 * shift for midi in midis]
        misses = sum(1 for midi in moved if not candidates(midi))
        cost = abs(shift) * len(midis) + misses * 3
        if best_cost is None or cost < best_cost or (cost == best_cost and abs(shift) < abs(best_shift)):
            best_cost = cost
            best_shift = shift
    chosen: list[int] = []
    for midi in midis:
        pitched = midi + 12 * best_shift
        if candidates(pitched):
            chosen.append(pitched)
        else:
            chosen.append(_nearest_playable(pitched))
    return chosen


def _nearest_playable(midi: int) -> int:
    options = _playable_pitches(midi)
    if not options:
        raise ValueError(f"Nota fuera del mástil: {midi}")
    return min(options, key=lambda item: (abs(item - midi), -item))


def _playable_pitches(midi: int) -> list[int]:
    found: list[int] = []
    for octave in range(-5, 6):
        candidate = midi + 12 * octave
        if candidates(candidate):
            found.append(candidate)
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
