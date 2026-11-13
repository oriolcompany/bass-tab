import numpy as np

from bass_tab.pitch import track_pitch
from bass_tab.separate import _explain
from bass_tab.tab import assign_positions, notes_from_track


def _tone(frequency: float, seconds: float = 0.45, rate: int = 16000) -> np.ndarray:
    count = int(seconds * rate)
    time = np.arange(count) / rate
    signal = (
        np.sin(2 * np.pi * frequency * time)
        + 0.45 * np.sin(2 * np.pi * 2 * frequency * time)
        + 0.2 * np.sin(2 * np.pi * 3 * frequency * time)
    )
    return (0.55 * signal / 1.65).astype(np.float64)


def test_open_a_is_fret_zero_on_the_a_string():
    samples = _tone(55.0, 0.5)
    times, midis, confidence = track_pitch(samples)
    notes = notes_from_track(times, midis, confidence)
    assert notes
    assert notes[0]["midi"] == 33
    assert notes[0]["stringName"] == "A"
    assert notes[0]["fret"] == 0


def test_e2_prefers_the_low_fret_on_the_d_string():
    samples = _tone(82.4069, 0.5)
    times, midis, confidence = track_pitch(samples)
    notes = notes_from_track(times, midis, confidence)
    assert notes
    assert notes[0]["midi"] == 40
    assert (notes[0]["stringName"], notes[0]["fret"]) == ("D", 2)


def test_silence_has_no_notes():
    times, midis, confidence = track_pitch(np.zeros(16000))
    assert notes_from_track(times, midis, confidence) == []


def test_two_pitches_stay_in_position():
    gap = np.zeros(int(0.12 * 16000))
    samples = np.concatenate([_tone(55.0), gap, _tone(61.735), gap])
    times, midis, confidence = track_pitch(samples)
    notes = notes_from_track(times, midis, confidence)
    assert len(notes) == 2
    assert [note["stringName"] for note in notes] == ["A", "A"]
    assert [note["fret"] for note in notes] == [0, 2]


def test_gpu_memory_error_is_explained():
    message = str(_explain(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")))
    assert "tarjeta gráfica" in message


def test_single_note_position_without_audio():
    assert assign_positions([33]) == [(2, 0)]
    assert assign_positions([40]) == [(1, 2)]
