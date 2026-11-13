"""ffmpeg helpers: read audio and time-stretch without changing pitch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np


class AudioError(RuntimeError):
    pass


SPEEDS = (0.5, 0.75, 1.0)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def run_ffmpeg(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    if not ffmpeg_available():
        raise AudioError("Falta ffmpeg en el PATH")
    result = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        raise AudioError(detail[:400] or "ffmpeg ha fallado")
    return result


def read_mono(path: Path, sample_rate: int = 16000) -> np.ndarray:
    result = run_ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path.resolve()),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "pipe:1",
        ]
    )
    if not result.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def to_pcm_wav(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source.resolve()),
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(dest.resolve()),
        ]
    )


def stretch_wav(source: Path, dest: Path, speed: float) -> None:
    """Write a copy whose duration is 1/speed. Pitch stays the same."""
    if speed not in SPEEDS:
        raise AudioError("Velocidad no admitida")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if speed == 1.0:
        if source.resolve() != dest.resolve():
            dest.write_bytes(source.read_bytes())
        return
    run_ffmpeg(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source.resolve()),
            "-filter:a",
            f"atempo={speed}",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(dest.resolve()),
        ]
    )
