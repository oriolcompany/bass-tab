from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bass_tab import app as app_module
from bass_tab import library
from bass_tab.audio import to_pcm_wav
from wavutil import write_bass


def _inline(target, args):
    target(*args)


@pytest.fixture(autouse=True)
def isolated_songs(tmp_path, monkeypatch):
    monkeypatch.setenv("BASS_TAB_SONGS", str(tmp_path / "songs"))
    library._cache.clear()
    library._recovered = False
    with app_module._active_lock:
        app_module._active = None
    yield
    library._cache.clear()
    library._recovered = False
    with app_module._active_lock:
        app_module._active = None


@pytest.fixture(autouse=True)
def fake_separator(monkeypatch):
    def fake(audio_path, dest_dir, on_progress=None):
        fake.calls += 1
        if on_progress:
            on_progress(0.4, "separando")
        folder = Path(dest_dir)
        to_pcm_wav(audio_path, folder / "bass.wav")
        to_pcm_wav(audio_path, folder / "drums.wav")
        return ["bass", "drums"]

    fake.calls = 0
    monkeypatch.setattr(app_module, "separate_file", fake)
    monkeypatch.setattr(app_module, "_start_background", _inline)
    return fake


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "ffmpeg" in body
    assert "separation" in body


def test_menu_starts_empty(client):
    response = client.get("/api/songs")
    assert response.status_code == 200
    assert response.json()["songs"] == []


def test_rejects_unknown_extension(client):
    response = client.post("/api/songs", files={"song": ("notes.txt", b"hola", "text/plain")})
    assert response.status_code == 400


def test_missing_separator_is_refused(client, monkeypatch):
    monkeypatch.setattr(app_module, "separation_available", lambda: False)
    response = client.post("/api/songs", files={"song": ("tema.mp3", b"abc", "audio/mpeg")})
    assert response.status_code == 503


def test_song_is_separated_once_and_listed(client, fake_separator, tmp_path):
    audio = tmp_path / "caminata.wav"
    write_bass(audio, [(55.0, 0.45, 0.6), (0.0, 0.12, 0.0), (82.4069, 0.45, 0.6)])
    payload = audio.read_bytes()
    first = client.post("/api/songs", files={"song": ("caminata.wav", payload, "audio/wav")})
    assert first.status_code == 202
    song_id = first.json()["id"]
    assert first.json()["cached"] is False

    status = client.get(f"/api/songs/{song_id}")
    body = status.json()
    assert body["status"] == "done"
    assert body["title"] == "caminata"
    assert [note["fret"] for note in body["notes"]] == [0, 2]
    assert [note["stringName"] for note in body["notes"]] == ["A", "D"]
    assert [track["id"] for track in body["tracks"]] == ["bass", "drums"]

    menu = client.get("/api/songs").json()["songs"]
    assert [song["title"] for song in menu] == ["caminata"]
    assert "notes" not in menu[0]

    second = client.post("/api/songs", files={"song": ("otra-copia.wav", payload, "audio/wav")})
    assert second.status_code == 200
    assert second.json() == {"id": song_id, "cached": True}
    assert fake_separator.calls == 1
    assert client.get(f"/api/songs/{song_id}").json()["title"] == "otra-copia"

    bass = client.get(f"/api/songs/{song_id}/audio/bass")
    drums = client.get(f"/api/songs/{song_id}/audio/drums")
    assert bass.status_code == 200
    assert drums.status_code == 200
    assert bass.headers["content-type"].startswith("audio/wav")

    removed = client.delete(f"/api/songs/{song_id}")
    assert removed.status_code == 204
    assert client.get("/api/songs").json()["songs"] == []
    again = client.post("/api/songs", files={"song": ("caminata.wav", payload, "audio/wav")})
    assert again.status_code == 202
    assert fake_separator.calls == 2


@pytest.mark.skipif(not app_module.ffmpeg_available(), reason="ffmpeg no está instalado")
def test_export_uses_the_fader_gains(client, tmp_path):
    audio = tmp_path / "tema.wav"
    write_bass(audio, [(55.0, 0.4, 0.5)])
    created = client.post("/api/songs", files={"song": ("tema.wav", audio.read_bytes(), "audio/wav")})
    song_id = created.json()["id"]
    silent = client.post(f"/api/songs/{song_id}/export", json={"gains": {"bass": 0, "drums": 0}})
    assert silent.status_code == 400
    exported = client.post(f"/api/songs/{song_id}/export", json={"gains": {"bass": 1, "drums": 0.25}})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("audio/mpeg")
    assert len(exported.content) > 500
    assert "tema.mp3" in exported.headers["content-disposition"]


@pytest.mark.skipif(not app_module.ffmpeg_available(), reason="ffmpeg no está instalado")
def test_half_speed_keeps_a_longer_file(client, tmp_path):
    audio = tmp_path / "bajo.wav"
    write_bass(audio, [(55.0, 0.8, 0.5)])
    created = client.post("/api/songs", files={"song": ("bajo.wav", audio.read_bytes(), "audio/wav")})
    song_id = created.json()["id"]
    slowed = client.get(f"/api/songs/{song_id}/audio/bass", params={"speed": 0.5})
    assert slowed.status_code == 200
    assert len(slowed.content) > 1000
