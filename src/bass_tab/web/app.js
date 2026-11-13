const PHASES = {
  leyendo: "Leyendo la canción",
  modelo: "Cargando el modelo",
  separando: "Separando las pistas",
  codificando: "Guardando las pistas",
  notas: "Encontrando las notas del bajo",
  tablatura: "Colocando la tablatura",
  listo: "Listo",
};
const MENU_TEXT = "Sube el MP3 completo. Se separa una vez y queda en la lista para tocarla cuando quieras.";

const openButton = document.getElementById("openFile");
const backButton = document.getElementById("back");
const library = document.getElementById("library");
const catalog = document.getElementById("catalog");
const lede = document.getElementById("lede");
const drop = document.getElementById("drop");
const songInput = document.getElementById("songFile");
const progress = document.getElementById("progress");
const progressLabel = document.getElementById("progressLabel");
const progressPct = document.getElementById("progressPct");
const progressBar = document.getElementById("progressBar");
const player = document.getElementById("player");
const playButton = document.getElementById("play");
const timeLabel = document.getElementById("time");
const durationLabel = document.getElementById("duration");
const scrub = document.getElementById("scrub");
const scrubFill = document.getElementById("scrubFill");
const nowPlaying = document.getElementById("nowPlaying");
const names = document.getElementById("names");
const scroller = document.getElementById("scroller");
const sheet = document.getElementById("sheet");
const mixer = document.getElementById("mixer");
const exportButton = document.getElementById("export");
const exportStatus = document.getElementById("exportStatus");
const loopButton = document.getElementById("loop");
const errorBox = document.getElementById("error");

const PIXELS_PER_SECOND = 150;
const PLAYHEAD = 120;
const STRING_TOP = [48, 104, 160, 216];

let job = null;
let pollToken = 0;
let ctx = null;
let buffers = {};
let gains = {};
let active = [];
let speed = 1;
let playing = false;
let anchorOffset = 0;
let anchorCtx = 0;
let duration = 0;
let decodedKey = "";
let decodePromise = null;
const volumes = {};
const muted = {};
let loopOn = false;
let loopStart = 0;
let loopEnd = 0;
let noteButtons = [];
let requestToken = 0;
let separatorReady = true;

openButton.addEventListener("click", () => songInput.click());
backButton.addEventListener("click", () => {
  requestToken += 1;
  showLibrary();
});
songInput.addEventListener("change", () => {
  const file = songInput.files && songInput.files[0];
  songInput.value = "";
  if (file) upload(file);
});
library.addEventListener("dragover", (event) => {
  event.preventDefault();
  drop.classList.add("is-over");
});
library.addEventListener("dragleave", (event) => {
  if (!(event.relatedTarget instanceof Node) || !library.contains(event.relatedTarget)) drop.classList.remove("is-over");
});
library.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("is-over");
  const files = [...(event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files : [])];
  if (files.length) upload(files[0]);
});
playButton.addEventListener("click", () => {
  toggle().catch((error) => showError(error.message || "No se ha podido reproducir"));
});
exportButton.addEventListener("click", () => {
  exportMix().catch((error) => setExport(error.message || "No se ha podido exportar", "bad"));
});
loopButton.addEventListener("click", () => {
  loopOn = !loopOn;
  if (loopOn && loopEnd <= loopStart) {
    loopStart = 0;
    loopEnd = duration;
  }
  loopButton.setAttribute("aria-pressed", loopOn ? "true" : "false");
});
for (const button of document.querySelectorAll("[data-speed]")) {
  button.addEventListener("click", () => {
    setSpeed(Number(button.dataset.speed)).catch((error) => showError(error.message));
  });
}
bindSeek(scrub);
bindSeek(scroller);

window.addEventListener("keydown", (event) => {
  if (!job || job.status !== "done") return;
  if (event.target instanceof HTMLInputElement) return;
  if (event.code === "Space") {
    event.preventDefault();
    toggle().catch((error) => showError(error.message || "No se ha podido reproducir"));
  } else if (event.code === "ArrowRight") {
    event.preventDefault();
    seekTo(position() + 2);
  } else if (event.code === "ArrowLeft") {
    event.preventDefault();
    seekTo(position() - 2);
  }
});

const initial = new URLSearchParams(location.search).get("song") || new URLSearchParams(location.search).get("job");
if (initial) watch(initial);
else showLibrary();

async function upload(file) {
  const token = ++requestToken;
  clearError();
  stopPlayback(true);
  const body = new FormData();
  body.append("song", file, file.name);
  openButton.disabled = true;
  showProgress({ phase: "leyendo", progress: 0.02, title: file.name });
  try {
    const created = await api("/api/songs", { method: "POST", body });
    if (token !== requestToken) return;
    await watch(created.id);
  } catch (error) {
    if (token !== requestToken) return;
    await showLibrary();
    showError(error.message || "No se ha podido preparar la canción");
  } finally {
    openButton.disabled = false;
  }
}

async function watch(id) {
  const token = ++pollToken;
  const url = new URL(location.href);
  url.searchParams.set("song", id);
  history.replaceState(null, "", url);
  let misses = 0;
  while (token === pollToken) {
    let current;
    try {
      current = await api(`/api/songs/${id}`);
      misses = 0;
    } catch (error) {
      misses += 1;
      if (misses < 8) {
        await sleep(200);
        continue;
      }
      await showLibrary();
      showError(error.message || "No se encuentra esa canción");
      return;
    }
    if (token !== pollToken) return;
    job = current;
    if (current.status === "done") {
      showPlayer(current);
      return;
    }
    if (current.status === "error") {
      await showLibrary();
      showError(current.error || "No se ha podido preparar la canción");
      return;
    }
    showProgress(current);
    await sleep(400);
  }
}

async function showLibrary() {
  const token = ++pollToken;
  stopPlayback(true);
  job = null;
  speed = 1;
  markSpeed(1);
  library.hidden = false;
  progress.hidden = true;
  player.hidden = true;
  backButton.hidden = true;
  lede.textContent = MENU_TEXT;
  document.title = "Bass Tab";
  const url = new URL(location.href);
  if (url.search) {
    url.search = "";
    history.replaceState(null, "", url);
  }
  clearError();
  await refreshLibrary(token);
}

async function refreshLibrary(token) {
  let payload;
  try {
    payload = await api("/api/songs");
  } catch (error) {
    if (token === pollToken) showError(error.message || "No se ha podido leer la lista");
    return;
  }
  if (token !== pollToken) return;
  separatorReady = payload.separation !== false;
  if (!separatorReady) showError("Falta el separador de pistas en este Python.");
  renderCatalog(payload.songs || []);
  if ((payload.songs || []).some((song) => song.status === "running")) {
    setTimeout(() => refreshLibrary(token), 800);
  }
}

function renderCatalog(songs) {
  catalog.replaceChildren();
  if (!songs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Todavía no hay canciones. Suelta un MP3 para añadir la primera.";
    catalog.append(empty);
    return;
  }
  for (const song of songs) {
    const row = document.createElement("div");
    row.className = song.status === "error" ? "song-row is-error" : "song-row";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "song-open";
    const copy = document.createElement("span");
    copy.className = "song-copy";
    const title = document.createElement("span");
    title.className = "song-title";
    title.textContent = song.title || "Canción";
    const meta = document.createElement("span");
    meta.className = "song-meta";
    meta.textContent = songMeta(song);
    copy.append(title, meta);
    const action = document.createElement("span");
    action.className = "song-action";
    action.textContent = song.status === "done" ? "Tocar" : song.status === "error" ? "Ha fallado" : "Preparando";
    open.append(copy, action);
    open.addEventListener("click", () => {
      if (song.status === "error") {
        showError(song.error || "No se ha podido preparar la canción");
        return;
      }
      requestToken += 1;
      stopPlayback(true);
      speed = 1;
      markSpeed(1);
      watch(song.id);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "song-delete";
    remove.textContent = "Quitar";
    remove.setAttribute("aria-label", `Quitar ${song.title || "canción"}`);
    remove.addEventListener("click", async () => {
      if (!window.confirm(`¿Quitar «${song.title || "esta canción"}» de la lista?`)) return;
      try {
        await api(`/api/songs/${song.id}`, { method: "DELETE" });
        await refreshLibrary(pollToken);
      } catch (error) {
        showError(error.message || "No se ha podido quitar");
      }
    });
    row.append(open, remove);
    catalog.append(row);
  }
}

function songMeta(song) {
  const bits = [];
  if (song.duration) bits.push(formatTime(song.duration));
  if (song.created) bits.push(formatDate(song.created));
  if (song.status === "running") {
    const pct = Math.round(clamp(Number(song.progress) || 0, 0, 1) * 100);
    bits.push(`${PHASES[song.phase] || "Preparando"} ${pct}%`);
  }
  if (song.status === "error") bits.push(song.error || "No se ha podido preparar");
  return bits.join(" · ") || "Lista para separar";
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function markSpeed(next) {
  for (const button of document.querySelectorAll("[data-speed]")) {
    button.classList.toggle("is-on", Number(button.dataset.speed) === next);
  }
}

function showProgress(current) {
  library.hidden = true;
  player.hidden = true;
  progress.hidden = false;
  backButton.hidden = false;
  const phase = PHASES[current.phase] || "Trabajando";
  progressLabel.textContent = current.title ? `${phase} · ${current.title}` : phase;
  const pct = Math.round(clamp(Number(current.progress) || 0, 0, 1) * 100);
  progressPct.textContent = `${pct}%`;
  progressBar.style.width = `${pct}%`;
}

function showPlayer(current) {
  clearError();
  library.hidden = true;
  progress.hidden = true;
  player.hidden = false;
  backButton.hidden = false;
  lede.textContent = current.title || "Bass Tab";
  document.title = current.title ? `${current.title} · Bass Tab` : "Bass Tab";
  duration = Number(current.duration) || 0;
  durationLabel.textContent = formatTime(duration);
  loopStart = 0;
  loopEnd = duration;
  renderNames(current.tuning || []);
  renderSheet(current);
  resetMix(current.tracks || []);
  renderMixer(current.tracks || []);
  for (const track of current.tracks || []) applyGain(track.id);
  setExport("", "");
  draw();
}

function resetMix(tracks) {
  for (const track of tracks) {
    volumes[track.id] = track.role === "bass" ? 1 : 0.25;
    muted[track.id] = false;
  }
}

function layoutSheet() {
  const view = Math.max(scroller.clientWidth || 0, 320);
  sheet.style.width = `${duration * PIXELS_PER_SECOND + view}px`;
}

window.addEventListener("resize", () => {
  if (player.hidden) return;
  layoutSheet();
  draw();
});

function renderNames(tuning) {
  names.replaceChildren();
  const rows = tuning.length ? tuning : [{ name: "G" }, { name: "D" }, { name: "A" }, { name: "E" }];
  rows.forEach((row, index) => {
    const label = document.createElement("span");
    label.textContent = row.name;
    label.style.top = `${STRING_TOP[index]}px`;
    names.append(label);
  });
}

function renderSheet(current) {
  sheet.replaceChildren();
  layoutSheet();
  STRING_TOP.forEach((top) => {
    const line = document.createElement("div");
    line.className = "string-line";
    line.style.top = `${top}px`;
    sheet.append(line);
  });
  if (current.tempo) {
    const beat = 60 / Number(current.tempo);
    for (let time = 0; time < duration; time += beat) {
      const mark = document.createElement("div");
      mark.className = "beat";
      mark.style.left = `${time * PIXELS_PER_SECOND + PLAYHEAD}px`;
      sheet.append(mark);
    }
  }
  noteButtons = [];
  for (const note of current.notes || []) {
    const left = note.start * PIXELS_PER_SECOND + PLAYHEAD;
    const sustain = document.createElement("div");
    sustain.className = "sustain";
    sustain.style.left = `${left}px`;
    sustain.style.width = `${Math.max(8, note.duration * PIXELS_PER_SECOND)}px`;
    sustain.style.top = `${STRING_TOP[note.string]}px`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "note";
    button.textContent = String(note.fret);
    button.style.left = `${left}px`;
    button.style.top = `${STRING_TOP[note.string]}px`;
    button.title = `${note.name} · cuerda ${note.stringName} · traste ${note.fret}`;
    button.dataset.start = String(note.start);
    button.dataset.end = String(note.start + note.duration);
    button.dataset.label = button.title;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      seekTo(note.start);
    });
    sheet.append(sustain, button);
    noteButtons.push(button);
  }
}

function renderMixer(tracks) {
  mixer.replaceChildren();
  for (const track of tracks) {
    if (volumes[track.id] == null) volumes[track.id] = track.role === "bass" ? 1 : 0.25;
    if (muted[track.id] == null) muted[track.id] = false;
    const row = document.createElement("div");
    row.className = "track";
    const title = document.createElement("strong");
    title.textContent = track.name;
    const role = document.createElement("span");
    role.className = "role";
    role.textContent = track.role === "bass" ? "Bajo, la que se tabula" : "Acompañamiento";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "150";
    slider.value = String(Math.round(volumes[track.id] * 100));
    slider.setAttribute("aria-label", `Volumen de ${track.name}`);
    const out = document.createElement("output");
    out.textContent = `${slider.value}%`;
    slider.addEventListener("input", () => {
      volumes[track.id] = Number(slider.value) / 100;
      out.textContent = `${slider.value}%`;
      applyGain(track.id);
    });
    const mute = document.createElement("button");
    mute.type = "button";
    mute.textContent = "Mute";
    mute.setAttribute("aria-pressed", muted[track.id] ? "true" : "false");
    mute.addEventListener("click", () => {
      muted[track.id] = !muted[track.id];
      mute.setAttribute("aria-pressed", muted[track.id] ? "true" : "false");
      applyGain(track.id);
    });
    row.append(title, role, slider, out, mute);
    mixer.append(row);
  }
}

function bindSeek(element) {
  element.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest(".note")) return;
    const wasPlaying = playing;
    element.setPointerCapture(event.pointerId);
    const fromScroller = element === scroller;
    const seek = (next) => {
      const ratio = fromScroller ? timeFromScroller(next) / Math.max(duration, 0.001) : ratioFromEvent(next, element);
      previewSeek(ratio);
    };
    seek(event);
    function move(next) { seek(next); }
    function up(next) {
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", up);
      seek(next);
      if (wasPlaying) {
        ensureAudio().then(() => startSources()).catch((error) => showError(error.message));
      }
    }
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", up);
  });
}

function timeFromScroller(event) {
  const rect = scroller.getBoundingClientRect();
  return (event.clientX - rect.left + scroller.scrollLeft - PLAYHEAD) / PIXELS_PER_SECOND;
}

async function toggle() {
  if (!job || job.status !== "done") return;
  await ensureAudio();
  if (playing) {
    anchorOffset = position();
    stopSources();
    playing = false;
    draw();
  } else {
    startSources();
  }
  updatePlayButton();
}

async function setSpeed(next) {
  const was = playing;
  const at = position();
  stopSources();
  playing = false;
  speed = next;
  anchorOffset = at;
  decodePromise = null;
  decodedKey = "";
  markSpeed(next);
  if (was) await toggle();
  else draw();
}

async function ensureAudio() {
  if (!job) return;
  const key = `${job.id}@${speed}`;
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") await ctx.resume();
  if (decodedKey === key) return;
  if (!decodePromise) {
    const task = decodeAll(job, speed);
    decodePromise = task;
    task.then(
      () => {
        if (decodePromise === task && decodedKey !== key) decodePromise = null;
      },
      () => {
        if (decodePromise === task) decodePromise = null;
      },
    );
  }
  await decodePromise;
}

async function decodeAll(current, requested) {
  playButton.disabled = true;
  playButton.textContent = "Cargando…";
  try {
    const next = {};
    await Promise.all(
      (current.tracks || []).map(async (track) => {
        const response = await fetch(
          `/api/songs/${current.id}/audio/${encodeURIComponent(track.id)}?speed=${requested}`,
        );
        if (!response.ok) throw new Error(`No se ha podido leer ${track.name}`);
        next[track.id] = await ctx.decodeAudioData((await response.arrayBuffer()).slice(0));
      }),
    );
    if (!job || job.id !== current.id || speed !== requested) return;
    buffers = next;
    decodedKey = `${current.id}@${requested}`;
    ensureGains();
  } finally {
    playButton.disabled = false;
    updatePlayButton();
  }
}

function ensureGains() {
  for (const track of job.tracks || []) {
    let node = gains[track.id];
    if (!node) {
      node = ctx.createGain();
      node.connect(ctx.destination);
      gains[track.id] = node;
    }
    node.gain.value = gainOf(track.id);
  }
}

function applyGain(trackId) {
  const node = gains[trackId];
  if (node) node.gain.value = gainOf(trackId);
}

function gainOf(trackId) {
  if (muted[trackId]) return 0;
  const value = volumes[trackId];
  return Number.isFinite(value) ? value : 1;
}

function startSources() {
  if (!ctx || decodedKey !== `${job && job.id}@${speed}`) return;
  if (anchorOffset >= duration - 0.05) anchorOffset = loopOn ? loopStart : 0;
  stopSources();
  anchorCtx = ctx.currentTime;
  const offset = anchorOffset / speed;
  for (const track of job.tracks || []) {
    const buffer = buffers[track.id];
    if (!buffer || offset >= buffer.duration - 0.001) continue;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(gains[track.id]);
    source.start(anchorCtx, offset);
    active.push(source);
  }
  if (!active.length) return;
  playing = true;
  updatePlayButton();
  requestAnimationFrame(tick);
}

function stopSources() {
  for (const source of active) {
    try {
      source.onended = null;
      source.stop();
    } catch {
      /* already stopped */
    }
  }
  active = [];
}

function stopPlayback(reset) {
  stopSources();
  playing = false;
  if (reset) {
    anchorOffset = 0;
    buffers = {};
    decodePromise = null;
    decodedKey = "";
  }
  updatePlayButton();
}

function tick() {
  if (!playing) return;
  const at = position();
  if (loopOn && loopEnd > loopStart && at >= loopEnd) {
    anchorOffset = loopStart;
    startSources();
    return;
  }
  if (at >= duration - 0.03) {
    stopSources();
    playing = false;
    anchorOffset = duration;
    draw();
    updatePlayButton();
    return;
  }
  draw();
  requestAnimationFrame(tick);
}

function seekTo(time) {
  const was = playing;
  previewSeek(time / Math.max(duration, 0.001));
  if (was) {
    ensureAudio().then(() => startSources()).catch((error) => showError(error.message));
  }
}

function previewSeek(ratio) {
  anchorOffset = clamp(ratio, 0, 1) * (Number.isFinite(duration) ? duration : 0);
  stopSources();
  playing = false;
  draw();
  updatePlayButton();
}

function ratioFromEvent(event, element) {
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0) return 0;
  return clamp((event.clientX - rect.left) / rect.width, 0, 1);
}

function position() {
  if (!playing || !ctx) return anchorOffset;
  return anchorOffset + (ctx.currentTime - anchorCtx) * speed;
}

function draw() {
  const at = clamp(position(), 0, duration || 0);
  const ratio = duration > 0 ? at / duration : 0;
  scrubFill.style.width = `${ratio * 100}%`;
  scrub.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
  timeLabel.textContent = formatTime(at);
  scroller.scrollLeft = Math.max(0, at * PIXELS_PER_SECOND);
  let current = null;
  for (const button of noteButtons) {
    const start = Number(button.dataset.start);
    const end = Number(button.dataset.end);
    const on = at >= start && at < end;
    button.classList.toggle("is-on", on);
    if (on) current = button.dataset.label;
  }
  nowPlaying.textContent = current || "Silencio";
}

function updatePlayButton() {
  if (playButton.disabled) return;
  playButton.textContent = playing ? "Pausa" : "Reproducir";
}

async function exportMix() {
  if (!job || job.status !== "done") return;
  exportButton.disabled = true;
  setExport("Exportando la mezcla…", "");
  try {
    const gains = {};
    for (const track of job.tracks || []) gains[track.id] = gainOf(track.id);
    const response = await fetch(`/api/songs/${job.id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gains }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const detail = typeof data.detail === "string" ? data.detail : "No se ha podido exportar";
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    const base = (job.title || "mezcla").replace(/[<>:"/\\|?*]+/g, " ").trim() || "mezcla";
    link.download = `${base}.mp3`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setExport("Mezcla descargada.", "ok");
  } finally {
    exportButton.disabled = false;
  }
}

function setExport(message, kind) {
  exportStatus.textContent = message;
  exportStatus.className = kind || "";
}

function showError(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Error ${response.status}`;
    throw new Error(detail);
  }
  return data;
}
