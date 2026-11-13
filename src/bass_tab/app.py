"""Local web app: a full mix in, a saved bass tablature out."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import library
from .audio import SPEEDS, AudioError, ffmpeg_available, stretch_wav
from .mix import export_mix
from .separate import TRACK_ORDER, separate_file, separation_available, track_payload
from .transcribe import transcribe_bass

log = logging.getLogger("bass_tab")

WEB_DIR = Path(__file__).resolve().parent / "web"
ALLOWED = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

class ExportBody(BaseModel):
    gains: dict[str, float] = {}


app = FastAPI(title="Bass Tab", docs_url=None, redoc_url=None)
_active_lock = threading.Lock()
_active: str | None = None


def _begin(song_id: str) -> bool:
    global _active
    with _active_lock:
        if _active is not None:
            return False
        _active = song_id
        return True


def _end(song_id: str) -> None:
    global _active
    with _active_lock:
        if _active == song_id:
            _active = None


def _load(song_id: str) -> dict:
    try:
        return library.read_song(song_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No se encuentra esa canción") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No se encuentra esa canción") from None
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="La ficha de la canción está dañada") from None


def _safe_name(filename: str | None, fallback: str) -> str:
    raw = Path(filename or fallback).name
    cleaned = _UNSAFE.sub(" ", raw).strip().rstrip(". ") or fallback
    return cleaned[:180]


def _title(filename: str | None) -> str:
    name = _safe_name(filename, "canción")
    stem = Path(name).stem.strip() or name
    return stem[:160]


async def _save(upload: UploadFile, dest: Path) -> int:
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    return total


def _suffix(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail="Usa MP3, WAV, FLAC, M4A, OGG u OPUS")
    return suffix


def _start_background(target, args: tuple) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def _finished(song_id: str) -> bool:
    try:
        song = library.read_song(song_id)
    except (KeyError, FileNotFoundError, json.JSONDecodeError):
        return False
    return song.get("status") == "done" and (library.song_dir(song_id) / "bass.wav").is_file()


def _run_song(song_id: str, source: Path) -> None:
    try:
        last = 0.0

        def on_progress(ratio: float, phase: str) -> None:
            nonlocal last
            moment = time.monotonic()
            if moment - last < 0.4 and ratio < 0.99:
                return
            last = moment
            library.write_song(song_id, status="running", phase=phase, progress=round(0.08 + 0.74 * ratio, 4))

        stems = separate_file(source, library.song_dir(song_id), on_progress)
        tracks = [track_payload(stem_id) for stem_id in TRACK_ORDER if stem_id in stems]
        library.write_song(song_id, status="running", phase="notas", progress=0.9, tracks=tracks)
        result = transcribe_bass(library.song_dir(song_id) / "bass.wav")
        library.write_song(
            song_id,
            status="done",
            phase="listo",
            progress=1,
            duration=result["duration"],
            tuning=result["tuning"],
            notes=result["notes"],
            tempo=result["tempo"],
            tracks=tracks,
            error=None,
        )
    except AudioError as exc:
        log.warning("Canción %s: %s", song_id, exc)
        library.write_song(song_id, status="error", phase="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("Canción %s ha fallado", song_id)
        library.write_song(song_id, status="error", phase="error", error=f"No se ha podido preparar: {exc}")
    finally:
        _end(song_id)


@app.get("/api/health")
def health() -> dict:
    return {"ffmpeg": ffmpeg_available(), "separation": separation_available()}


@app.get("/api/songs")
def songs() -> dict:
    library.recover_interrupted()
    return {"separation": separation_available(), "songs": library.list_songs()}


@app.post("/api/songs", status_code=202, response_model=None)
async def create_song(song: UploadFile = File(...)):
    suffix = _suffix(song)
    if not ffmpeg_available():
        raise HTTPException(status_code=503, detail="Falta ffmpeg en el PATH")
    if not separation_available():
        raise HTTPException(status_code=503, detail="Falta el separador de pistas en este Python")
    library.recover_interrupted()

    incoming = library.songs_root() / "incoming" / f"{uuid.uuid4().hex}{suffix}"
    started = False
    song_id = ""
    try:
        if await _save(song, incoming) <= 0:
            raise HTTPException(status_code=400, detail="El archivo está vacío")
        song_id = library.file_sha256(incoming)
        if _finished(song_id):
            library.write_song(song_id, title=_title(song.filename))
            return JSONResponse({"id": song_id, "cached": True}, status_code=200)
        if not _begin(song_id):
            if _active == song_id:
                return {"id": song_id, "cached": False}
            raise HTTPException(status_code=409, detail="Ya se está preparando otra canción")
        started = True
        folder = library.song_dir(song_id)
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("source.*"):
            old.unlink()
        source = folder / f"source{suffix}"
        shutil.move(str(incoming), source)
        existing: dict = {}
        try:
            existing = library.read_song(song_id)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}
        library.write_song(
            song_id,
            title=_title(song.filename),
            created=existing.get("created") or library.now(),
            status="running",
            phase="leyendo",
            progress=0.02,
            tracks=[],
            notes=[],
            tuning=[],
            duration=existing.get("duration"),
            tempo=None,
            error=None,
        )
    except HTTPException:
        if started:
            _end(song_id)
        raise
    except Exception as exc:
        if started:
            _end(song_id)
        log.exception("No se ha podido guardar la canción")
        raise HTTPException(status_code=500, detail="No se ha podido guardar la canción") from exc
    finally:
        incoming.unlink(missing_ok=True)

    _start_background(_run_song, (song_id, source))
    return {"id": song_id, "cached": False}


@app.get("/api/songs/{song_id}")
def song_status(song_id: str) -> dict:
    return _load(song_id)


@app.delete("/api/songs/{song_id}", status_code=204)
def remove_song(song_id: str) -> None:
    if _active == song_id:
        raise HTTPException(status_code=409, detail="Esa canción se está preparando")
    try:
        library.delete_song(song_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No se encuentra esa canción") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No se encuentra esa canción") from None


@app.post("/api/songs/{song_id}/export")
def export_song(song_id: str, body: ExportBody) -> FileResponse:
    status = _load(song_id)
    if status.get("status") != "done":
        raise HTTPException(status_code=409, detail="La canción todavía no está lista")
    tracks = status.get("tracks") or []
    if not tracks:
        raise HTTPException(status_code=409, detail="Esta canción no tiene pistas")
    folder = library.song_dir(song_id)
    pairs = []
    for track in tracks:
        track_id = track["id"]
        pairs.append((folder / f"{track_id}.wav", body.gains.get(track_id, 1.0)))
    target = folder / "mix.mp3"
    try:
        export_mix(pairs, target)
    except AudioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(target, media_type="audio/mpeg", filename=f"{_title(status.get('title'))}.mp3")


@app.get("/api/songs/{song_id}/audio/{track_id}")
def track_audio(song_id: str, track_id: str, speed: float = 1.0) -> FileResponse:
    status = _load(song_id)
    known = {item["id"] for item in status.get("tracks") or []}
    if track_id not in known:
        raise HTTPException(status_code=404, detail="Pista desconocida")
    if speed not in SPEEDS:
        raise HTTPException(status_code=400, detail="La velocidad tiene que ser 0.5, 0.75 o 1")
    source = library.song_dir(song_id) / f"{track_id}.wav"
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if speed == 1.0:
        return FileResponse(source, media_type="audio/wav")
    cached = library.song_dir(song_id) / f"{track_id}-{speed:.2f}.wav"
    if not cached.is_file():
        try:
            stretch_wav(source, cached, speed)
        except AudioError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(cached, media_type="audio/wav")


@app.middleware("http")
async def no_cache_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        response.headers["Cache-Control"] = "no-store"
    return response


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Bass Tab, tablatura de bajo local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--open", dest="open_browser", action="store_true", default=True)
    parser.add_argument("--no-open", dest="open_browser", action="store_false")
    args = parser.parse_args()
    if not WEB_DIR.is_dir():
        raise SystemExit(f"No está la interfaz en {WEB_DIR}")
    url = f"http://{args.host}:{args.port}"
    log.info("Bass Tab en %s", url)
    if args.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
