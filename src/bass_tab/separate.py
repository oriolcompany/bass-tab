"""Split a full mix into vocals, drums, bass and other.

Same path as Stem Mixer: audio-separator with Demucs htdemucs, reusing the
weights already downloaded for Karaoke Party when they are on this PC.
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .audio import AudioError, ffmpeg_available, to_pcm_wav

DEFAULT_MODEL = (os.environ.get("BASS_TAB_MODEL") or "").strip() or "htdemucs.yaml"

TRACKS: dict[str, dict[str, str]] = {
    "bass": {"name": "Bajo", "role": "bass"},
    "drums": {"name": "Batería", "role": "backing"},
    "vocals": {"name": "Voces", "role": "backing"},
    "other": {"name": "Otros", "role": "backing"},
    "instrumental": {"name": "Instrumental", "role": "backing"},
}
TRACK_ORDER = ("bass", "drums", "vocals", "other", "instrumental")

_SAFE_STEM_NAMES = {
    "Vocals": "stem_vocals",
    "Instrumental": "stem_instrumental",
    "Bass": "stem_bass",
    "Drums": "stem_drums",
    "Other": "stem_other",
}

_EXACT = {
    "stem_vocals": "vocals",
    "vocals": "vocals",
    "stem_drums": "drums",
    "drums": "drums",
    "stem_bass": "bass",
    "bass": "bass",
    "stem_other": "other",
    "other": "other",
    "stem_instrumental": "instrumental",
    "instrumental": "instrumental",
}

_SEPARATE_FROM = 0.12
_SEPARATE_TO = 0.82

_separator = None
_separator_model: str | None = None
_separator_lock = threading.Lock()
_separation_lock = threading.Lock()


class SeparationError(AudioError):
    pass


def separation_available() -> bool:
    return importlib.util.find_spec("audio_separator") is not None and ffmpeg_available()


def _explain(exc: Exception) -> SeparationError:
    message = str(exc).strip() or exc.__class__.__name__
    if "out of memory" in message.lower():
        return SeparationError(
            "La tarjeta gráfica se ha quedado sin memoria. Cierra otros programas que la usen y vuelve a añadir la canción."
        )
    return SeparationError(f"El separador ha fallado: {message}")


def track_payload(stem_id: str) -> dict[str, str]:
    meta = TRACKS[stem_id]
    return {"id": stem_id, "name": meta["name"], "role": meta["role"]}


def separate_file(
    audio_path: Path,
    dest_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[str]:
    """Write `dest_dir/{stem}.wav` and return the stem ids that were produced."""
    if not audio_path.is_file():
        raise SeparationError(f"No existe el archivo: {audio_path}")
    if not ffmpeg_available():
        raise SeparationError("Falta ffmpeg en el PATH")
    if importlib.util.find_spec("audio_separator") is None:
        raise SeparationError('Falta el separador. Instálalo con: pip install -e ".[stems]"')

    def report(ratio: float, phase: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0.0, min(1.0, ratio)), phase)
        except Exception:  # noqa: BLE001 — progress must never abort separation
            pass

    dest_dir.mkdir(parents=True, exist_ok=True)
    with _separation_lock:
        report(0.04, "modelo")
        separator = _get_separator()
        run_dir = dest_dir / f"run-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            _use_output_dir(separator, run_dir)
            staged = _stage_input(audio_path, run_dir)
            report(_SEPARATE_FROM, "separando")
            with _demucs_progress(report):
                try:
                    # Separator.separate() swallows the real exception and returns [].
                    produced = separator._separate_file(str(staged), dict(_SAFE_STEM_NAMES))
                except Exception as exc:
                    raise _explain(exc) from exc
            classified = _classify(_collect_wavs(produced, run_dir))
            if "bass" not in classified:
                listing = ", ".join(path.name for path in run_dir.glob("*.wav")) or "(vacío)"
                raise SeparationError(f"La separación no ha producido pista de bajo: {listing}")
            report(0.86, "codificando")
            written: list[str] = []
            for stem_id in TRACK_ORDER:
                source = classified.get(stem_id)
                if source is None:
                    continue
                to_pcm_wav(source, dest_dir / f"{stem_id}.wav")
                written.append(stem_id)
            return written
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


def models_dir() -> Path:
    env = (os.environ.get("BASS_TAB_MODELS") or "").strip()
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    local = base / "BassTab" / "models"
    local.mkdir(parents=True, exist_ok=True)
    if _has_weights(local):
        return local
    for candidate in (base / "KaraokeParty" / "stem-models", base / "StemMixer" / "models"):
        if candidate.is_dir() and _has_weights(candidate):
            return candidate
    return local


def _has_weights(path: Path) -> bool:
    patterns = ("*.th", "*.ckpt", "*.onnx", "*.pth")
    return any(any(path.glob(pattern)) for pattern in patterns)


def _stage_input(audio_path: Path, run_dir: Path) -> Path:
    suffix = audio_path.suffix.lower()
    if suffix not in {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}:
        suffix = ".mp3"
    staged = run_dir / f"input{suffix}"
    shutil.copy2(audio_path, staged)
    return staged


def _use_output_dir(separator, folder: Path) -> None:
    separator.output_dir = str(folder)
    model = getattr(separator, "model_instance", None)
    if model is not None:
        model.output_dir = str(folder)


def _get_separator():
    global _separator, _separator_model
    from audio_separator.separator import Separator

    with _separator_lock:
        if _separator is None or _separator_model != DEFAULT_MODEL:
            separator = Separator(
                log_level=40,
                output_dir=str(models_dir().parent / "scratch"),
                output_format="WAV",
                model_file_dir=str(models_dir()),
                use_autocast=(os.environ.get("BASS_TAB_AUTOCAST") or "").strip()
                not in {"", "0", "false"},
            )
            separator.load_model(model_filename=DEFAULT_MODEL)
            _separator = separator
            _separator_model = DEFAULT_MODEL
        return _separator


@contextmanager
def _demucs_progress(report: Callable[[float, str], None]) -> Iterator[None]:
    try:
        from audio_separator.separator.architectures import demucs_separator

        original = demucs_separator.apply_model
        supported = "set_progress_bar" in inspect.signature(original).parameters
    except Exception:  # noqa: BLE001 — progress must never block separation
        yield
        return
    if not supported:
        yield
        return

    def on_chunk(_base: float, value: float) -> None:
        done = min(1.0, max(0.0, float(value) / 0.8))
        report(_SEPARATE_FROM + done * (_SEPARATE_TO - _SEPARATE_FROM), "separando")

    def with_progress(*args, **kwargs):
        if kwargs.get("set_progress_bar") is None:
            kwargs["set_progress_bar"] = on_chunk
        return original(*args, **kwargs)

    demucs_separator.apply_model = with_progress
    try:
        yield
    finally:
        demucs_separator.apply_model = original


def _collect_wavs(produced: list | None, folder: Path) -> list[Path]:
    on_disk = {
        path.name.lower(): path
        for path in folder.glob("*.wav")
        if path.is_file() and path.stat().st_size > 0 and not path.stem.lower().startswith("input")
    }
    ordered: list[Path] = []
    seen: set[str] = set()
    for item in produced or []:
        name = Path(str(item)).name.lower()
        path = on_disk.get(name)
        if path is not None and name not in seen:
            ordered.append(path)
            seen.add(name)
    for name, path in sorted(on_disk.items()):
        if name not in seen:
            ordered.append(path)
    return ordered


def _classify(paths: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in paths:
        stem = path.stem.lower()
        kind = _EXACT.get(stem)
        if kind is None:
            name = path.name.lower()
            for key in ("vocals", "drums", "bass", "instrumental", "other"):
                if f"({key})" in name or stem.endswith(f"_{key}") or stem.endswith(f"-{key}"):
                    kind = key
                    break
        if kind is not None and kind not in found:
            found[kind] = path
    return found
