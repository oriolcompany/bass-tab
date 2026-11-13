"""Monophonic pitch tracking for an isolated bass stem (YIN)."""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
FRAME = 2048
HOP = 256


def difference_function(frame: np.ndarray) -> np.ndarray:
    values = np.asarray(frame, dtype=np.float64)
    values = values - np.mean(values)
    size = len(values)
    padded = np.zeros(2 * size, dtype=np.float64)
    padded[:size] = values
    spectrum = np.fft.rfft(padded)
    autocorr = np.fft.irfft(spectrum * np.conj(spectrum), n=2 * size)[:size]
    cumulative = np.empty(size + 1, dtype=np.float64)
    cumulative[0] = 0.0
    np.cumsum(values * values, out=cumulative[1:])
    tau = np.arange(size)
    length = size - tau
    summed = cumulative[length] + (cumulative[size] - cumulative[tau]) - 2.0 * autocorr
    summed[0] = 0.0
    np.maximum(summed, 0.0, out=summed)
    return summed


def cumulative_mean_normalized(difference: np.ndarray) -> np.ndarray:
    normalized = np.ones_like(difference)
    prefix = np.cumsum(difference)
    taus = np.arange(1, len(difference))
    denominator = prefix[1:]
    good = denominator > 1e-12
    scaled = np.ones(len(taus), dtype=np.float64)
    scaled[good] = difference[1:][good] * taus[good] / denominator[good]
    normalized[1:] = scaled
    return normalized


def yin_frame(
    frame: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    fmin: float = 40.0,
    fmax: float = 400.0,
    threshold: float = 0.15,
    rms_gate: float = 0.02,
) -> tuple[float | None, float]:
    samples = np.asarray(frame, dtype=np.float64)
    if float(np.sqrt(np.mean(samples * samples))) < rms_gate:
        return None, 0.0
    normalized = cumulative_mean_normalized(difference_function(samples))
    tau_min = max(2, int(sample_rate / fmax))
    tau_max = min(len(normalized) - 2, int(sample_rate / fmin))
    if tau_max <= tau_min:
        return None, 0.0
    region = normalized[tau_min:tau_max]
    below = np.flatnonzero(region < threshold)
    if len(below):
        tau = tau_min + int(below[0])
        while tau + 1 < tau_max and normalized[tau + 1] < normalized[tau]:
            tau += 1
    else:
        tau = tau_min + int(np.argmin(region))
        if normalized[tau] > 0.5:
            return None, 0.0
    refined = float(tau)
    if 1 <= tau < len(normalized) - 1:
        left, center, right = normalized[tau - 1], normalized[tau], normalized[tau + 1]
        denominator = 2.0 * (2.0 * center - right - left)
        if abs(denominator) > 1e-12:
            refined = tau + (left - right) / denominator
    refined = max(refined, 1.0)
    return sample_rate / refined, float(max(0.0, 1.0 - normalized[int(tau)]))


def track_pitch(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    frame_size: int = FRAME,
    hop: int = HOP,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    audio = np.asarray(samples, dtype=np.float64)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-8:
        audio = audio / peak * 0.8
    if len(audio) < frame_size:
        empty = np.zeros(0)
        return empty, empty.astype(int), empty
    times: list[float] = []
    midis: list[int] = []
    confidence: list[float] = []
    for start in range(0, len(audio) - frame_size, hop):
        frequency, weight = yin_frame(audio[start : start + frame_size], sample_rate)
        times.append((start + frame_size / 2) / sample_rate)
        if frequency is None or frequency <= 0:
            midis.append(0)
            confidence.append(0.0)
            continue
        midi = int(round(69.0 + 12.0 * np.log2(frequency / 440.0)))
        midis.append(midi)
        confidence.append(weight)
    return np.asarray(times), np.asarray(midis, dtype=int), np.asarray(confidence)
