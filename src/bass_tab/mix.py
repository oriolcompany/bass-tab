"""Sum the stems with per-track linear gains and encode an MP3."""

from __future__ import annotations

import wave
from pathlib import Path

from .audio import AudioError, run_ffmpeg

MAX_GAIN = 1.5
DEFAULT_BITRATE = "192k"


def clamp_gain(value: float) -> float:
    try:
        gain = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioError("Volumen inválido") from exc
    if gain != gain:  # NaN
        raise AudioError("Volumen inválido")
    return min(MAX_GAIN, max(0.0, gain))


def export_mix(
    stems: list[tuple[Path, float]],
    target: Path,
    bitrate: str = DEFAULT_BITRATE,
    semitones: int = 0,
) -> None:
    audible = [(path, clamp_gain(gain)) for path, gain in stems if clamp_gain(gain) > 0]
    if not audible:
        raise AudioError("Sube el volumen de alguna pista antes de exportar")
    missing = [path.name for path, _gain in audible if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise AudioError("Faltan pistas: " + ", ".join(missing))
    target.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(mix_command(audible, target, bitrate, semitones))
    if not target.is_file() or target.stat().st_size <= 0:
        raise AudioError("La mezcla no se ha escrito")


def mix_command(
    stems: list[tuple[Path, float]],
    target: Path,
    bitrate: str = DEFAULT_BITRATE,
    semitones: int = 0,
) -> list[str]:
    command = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error"]
    for path, _gain in stems:
        command += ["-i", str(path.resolve())]
    if len(stems) == 1:
        path, gain = stems[0]
        command += ["-filter:a", f"{_pitch(path, semitones)}volume={gain:.6f}"]
    else:
        parts: list[str] = []
        labels: list[str] = []
        for index, (path, gain) in enumerate(stems):
            parts.append(f"[{index}:a]{_pitch(path, semitones)}volume={gain:.6f}[s{index}]")
            labels.append(f"[s{index}]")
        mix = (
            "".join(labels)
            + f"amix=inputs={len(stems)}:normalize=0:duration=longest:dropout_transition=0[out]"
        )
        command += ["-filter_complex", ";".join([*parts, mix]), "-map", "[out]"]
    command += ["-c:a", "libmp3lame", "-b:a", bitrate, str(target.resolve())]
    return command


def _pitch(path: Path, semitones: int) -> str:
    if semitones == 0:
        return ""
    ratio = 2 ** (semitones / 12)
    rate = _sample_rate(path)
    return f"asetrate={rate * ratio:.6f},aresample={rate},atempo={1 / ratio:.6f},"


def _sample_rate(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
    except (FileNotFoundError, wave.Error, OSError):
        return 44100
    return rate or 44100
