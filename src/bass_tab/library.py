"""Saved songs. A finished song stays on disk and in memory, so separation runs once."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

_SONG_ID = re.compile(r"^[0-9a-f]{64}$")
_lock = threading.Lock()
_cache: dict[str, dict] = {}
_recovered = False

_SUMMARY = ("id", "title", "status", "phase", "progress", "duration", "created", "error")


def songs_root() -> Path:
    env = (os.environ.get("BASS_TAB_SONGS") or os.environ.get("BASS_TAB_JOBS") or "").strip()
    if env:
        path = Path(env)
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        path = base / "BassTab" / "songs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def song_dir(song_id: str) -> Path:
    if not _SONG_ID.fullmatch(song_id):
        raise KeyError(song_id)
    return songs_root() / song_id


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_song(song_id: str, **fields) -> dict:
    path = song_dir(song_id) / "song.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        current: dict = {}
        if path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current.update(fields)
        current["id"] = song_id
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        if current.get("status") == "done":
            _cache[song_id] = current
        else:
            _cache.pop(song_id, None)
        return current


def read_song(song_id: str) -> dict:
    with _lock:
        cached = _cache.get(song_id)
        if cached and cached.get("status") == "done":
            return cached
        path = song_dir(song_id) / "song.json"
        if not path.is_file():
            raise FileNotFoundError(song_id)
        song = json.loads(path.read_text(encoding="utf-8"))
        if song.get("status") == "done":
            _cache[song_id] = song
        return song


def list_songs() -> list[dict]:
    root = songs_root()
    songs: list[dict] = []
    for folder in root.iterdir():
        if not folder.is_dir() or not _SONG_ID.fullmatch(folder.name):
            continue
        path = folder / "song.json"
        if not path.is_file():
            continue
        try:
            song = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        songs.append({key: song.get(key) for key in _SUMMARY})
    songs.sort(key=lambda song: song.get("created") or "", reverse=True)
    return songs


def delete_song(song_id: str) -> None:
    folder = song_dir(song_id)
    if not folder.is_dir():
        raise FileNotFoundError(song_id)
    with _lock:
        _cache.pop(song_id, None)
    shutil.rmtree(folder)


def recover_interrupted() -> None:
    """A song left on "running" belongs to a process that is no longer here."""
    global _recovered
    with _lock:
        if _recovered:
            return
        _recovered = True
        pending = [
            song["id"]
            for song in _songs_unlocked()
            if song.get("status") == "running" and song.get("id")
        ]
    for song_id in pending:
        write_song(
            song_id,
            status="error",
            phase="error",
            error="La preparación se interrumpió. Vuelve a añadir la canción.",
        )


def _songs_unlocked() -> list[dict]:
    root = songs_root()
    songs: list[dict] = []
    if not root.is_dir():
        return songs
    for folder in root.iterdir():
        path = folder / "song.json"
        if not path.is_file():
            continue
        try:
            songs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return songs
