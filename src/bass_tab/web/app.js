const PHASES = {
  leyendo: "Leyendo la canción",
  modelo: "Cargando el modelo",
  separando: "Separando las pistas",
  codificando: "Guardando las pistas",
  notas: "Encontrando las notas del bajo",
  tablatura: "Colocando la tablatura",
  cola: "En cola",
  listo: "Listo",
};
const MENU_TEXT = "Sube un MP3 o una carpeta. Cada canción se separa una vez y queda en la lista.";
const AUDIO = /\.(mp3|wav|flac|m4a|ogg|opus)$/i;

const openButton = document.getElementById("openFile");
const folderButton = document.getElementById("openFolder");
const backButton = document.getElementById("back");
const library = document.getElementById("library");
const catalog = document.getElementById("catalog");
const catalogTools = document.getElementById("catalogTools");
const searchInput = document.getElementById("search");
const sortInput = document.getElementById("sort");
const lede = document.getElementById("lede");
const drop = document.getElementById("drop");
const batchStatus = document.getElementById("batchStatus");
const songInput = document.getElementById("songFile");
const folderInput = document.getElementById("folderFile");
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
const toneDown = document.getElementById("toneDown");
const toneUp = document.getElementById("toneUp");
const toneLabel = document.getElementById("toneLabel");
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
let semitones = 0;
let arrangeToken = 0;
let baseNotes = [];
let separatorReady = true;
let librarySongs = [];
const SORTS = new Set(["recent", "oldest", "title", "title-desc", "short", "long"]);
let sortMode = SORTS.has(localStorage.getItem("bass-tab-sort")) ? localStorage.getItem("bass-tab-sort") : "recent";
sortInput.value = sortMode;
searchInput.addEventListener("input", () => applyCatalog());
sortInput.addEventListener("change", () => {
  sortMode = SORTS.has(sortInput.value) ? sortInput.value : "recent";
  localStorage.setItem("bass-tab-sort", sortMode);
  applyCatalog();
});

openButton.addEventListener("click", () => songInput.click());
folderButton.addEventListener("click", () => folderInput.click());
backButton.addEventListener("click", () => {
  requestToken += 1;
  showLibrary();
});
songInput.addEventListener("change", () => {
  const file = songInput.files && songInput.files[0];
  songInput.value = "";
  if (file) upload(file);
});
folderInput.addEventListener("change", () => {
  const files = [...(folderInput.files || [])];
  folderInput.value = "";
  if (files.length) uploadFolder(files);
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
  if (uploading) return;
  dropped(event.dataTransfer).then((result) => {
    if (!result.files.length) {
      showError("No hay canciones de audio en lo que has soltado.");
      return;
    }
    if (result.folder || result.files.length > 1) uploadFolder(result.files);
    else upload(result.files[0]);
  }).catch((error) => showError(error.message || "No se ha podido leer la carpeta"));
});
playButton.addEventListener("click", () => {
  toggle().catch((error) => showError(error.message || "No se ha podido reproducir"));
});
exportButton.addEventListener("click", () => {
  exportMix().catch((error) => setExport(error.message || "No se ha podido exportar", "bad"));
});
toneDown.addEventListener("click", () => {
  setTranspose(semitones - 1).catch((error) => showError(error.message));
});
toneUp.addEventListener("click", () => {
  setTranspose(semitones + 1).catch((error) => showError(error.message));
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
  hideBatch();
  stopPlayback(true);
  const body = new FormData();
  body.append("song", file, file.name);
  setUploading(true);
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
    setUploading(false);
  }
}

async function uploadFolder(files) {
  const audio = audioFiles(files);
  if (!audio.length) {
    showError("Esa carpeta no tiene MP3, WAV, FLAC, M4A, OGG ni OPUS.");
    return;
  }
  const token = ++requestToken;
  ++pollToken;
  clearError();
  stopPlayback(true);
  revealLibrary();
  setUploading(true);
  let failed = 0;
  let cached = 0;
  let lastError = "";
  try {
    for (let index = 0; index < audio.length; index += 1) {
      if (token !== requestToken) return;
      const file = audio[index];
      showBatch(`Subiendo ${index + 1} de ${audio.length} · ${file.name}`);
      const body = new FormData();
      body.append("song", file, file.name);
      try {
        const created = await api("/api/songs", { method: "POST", body });
        if (created.cached) cached += 1;
      } catch (error) {
        failed += 1;
        lastError = error.message || "No se ha podido subir";
      }
      await refreshLibrary(pollToken);
    }
  } finally {
    setUploading(false);
  }
  if (token !== requestToken) return;
  if (failed === audio.length && lastError) {
    showBatch("");
    showError(lastError);
    return;
  }
  if (cached === audio.length) {
    showBatch(audio.length === 1 ? "Esa canción ya estaba en la lista." : "Esas canciones ya estaban en la lista.");
    return;
  }
  const added = audio.length - failed;
  const noun = added === 1 ? "canción" : "canciones";
  const extra = failed ? ` ${failed} no se han podido subir.` : " Se separan de una en una.";
  showBatch(`Añadidas ${added} ${noun}.${extra}`);
}

function audioFiles(files) {
  return [...files]
    .filter((file) => AUDIO.test(file.name))
    .sort((a, b) => compareTitle(a.webkitRelativePath || a.name, b.webkitRelativePath || b.name));
}

async function dropped(dataTransfer) {
  const items = [...(dataTransfer && dataTransfer.items ? dataTransfer.items : [])];
  const entries = items.map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null)).filter(Boolean);
  if (entries.length) {
    const files = [];
    for (const entry of entries) await collectEntry(entry, files);
    return { files: audioFiles(files), folder: entries.some((entry) => entry.isDirectory) };
  }
  const files = [...(dataTransfer && dataTransfer.files ? dataTransfer.files : [])];
  return { files: audioFiles(files), folder: false };
}

function collectEntry(entry, files) {
  return new Promise((resolve) => {
    if (!entry) {
      resolve();
      return;
    }
    if (entry.isFile) {
      entry.file(
        (file) => {
          files.push(file);
          resolve();
        },
        () => resolve(),
      );
      return;
    }
    if (!entry.isDirectory) {
      resolve();
      return;
    }
    const reader = entry.createReader();
    const children = [];
    const read = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          Promise.all(children.map((child) => collectEntry(child, files))).then(() => resolve());
          return;
        }
        children.push(...batch);
        read();
      }, () => resolve());
    };
    read();
  });
}

function revealLibrary() {
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
}

function showBatch(text) {
  batchStatus.hidden = !text;
  batchStatus.textContent = text || "";
}

function hideBatch() {
  showBatch("");
}

let uploading = false;

function setUploading(busy) {
  uploading = busy;
  openButton.disabled = busy;
  folderButton.disabled = busy;
  songInput.disabled = busy;
  folderInput.disabled = busy;
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
  hideBatch();
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
  if ((payload.songs || []).some((song) => song.status === "running" || song.status === "queued")) {
    setTimeout(() => refreshLibrary(token), 800);
  }
}

function renderCatalog(songs) {
  librarySongs = songs;
  applyCatalog();
}

function applyCatalog() {
  catalogTools.hidden = librarySongs.length === 0;
  const query = fold(searchInput.value.trim());
  const matched = librarySongs.filter((song) => !query || fold(song.title).includes(query));
  catalog.replaceChildren();
  if (!librarySongs.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Todavía no hay canciones. Suelta un MP3 o una carpeta para añadirlas.";
    catalog.append(empty);
    return;
  }
  if (!matched.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = `Ninguna canción coincide con «${searchInput.value.trim()}».`;
    catalog.append(empty);
    return;
  }
  for (const song of sortSongs(matched)) {
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
    action.textContent = song.status === "done" ? "Tocar" : song.status === "error" ? "Ha fallado" : song.status === "queued" ? "En cola" : "Preparando";
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

function sortSongs(songs) {
  const copy = [...songs];
  if (sortMode === "recent") {
    const rank = (song) => (song.status === "running" ? 0 : song.status === "queued" ? 1 : 2);
    copy.sort((a, b) => {
      const diff = rank(a) - rank(b);
      if (diff) return diff;
      if (a.status === "queued") return (a.created || "").localeCompare(b.created || "");
      return (b.created || "").localeCompare(a.created || "");
    });
    return copy;
  }
  copy.sort((a, b) => {
    if (sortMode === "oldest") return (a.created || "").localeCompare(b.created || "");
    if (sortMode === "title") return compareTitle(a.title, b.title);
    if (sortMode === "title-desc") return compareTitle(b.title, a.title);
    if (sortMode === "short") return (Number(a.duration) || 0) - (Number(b.duration) || 0);
    return (Number(b.duration) || 0) - (Number(a.duration) || 0);
  });
  return copy;
}

function compareTitle(a, b) {
  return fold(a).localeCompare(fold(b), "es", { numeric: true, sensitivity: "base" });
}

function fold(value) {
  return (value || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

function songMeta(song) {
  const bits = [];
  if (song.duration) bits.push(formatTime(song.duration));
  if (song.created) bits.push(formatDate(song.created));
  if (song.status === "running") {
    const pct = Math.round(clamp(Number(song.progress) || 0, 0, 1) * 100);
    bits.push(`${PHASES[song.phase] || "Preparando"} ${pct}%`);
  }
  if (song.status === "queued") bits.push("En cola");
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
  semitones = 0;
  arrangeToken += 1;
  baseNotes = (current.notes || []).map((note) => ({ ...note, shifted: 0 }));
  current.notes = baseNotes.map((note) => ({ ...note }));
  markTone();
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
    button.className = note.shifted ? "note is-moved" : "note";
    button.textContent = String(note.fret);
    button.style.left = `${left}px`;
    button.style.top = `${STRING_TOP[note.string]}px`;
    const moved = note.shifted > 0 ? " · octava arriba para que quepa" : note.shifted < 0 ? " · octava abajo para que quepa" : "";
    button.title = `${note.name} · cuerda ${note.stringName} · traste ${note.fret}${moved}`;
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
    source.detune.value = semitones * 100;
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
      body: JSON.stringify({ gains, semitones }),
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

async function setTranspose(next) {
  if (!job || job.status !== "done") return;
  const target = clamp(Math.round(next), -12, 12);
  semitones = target;
  markTone();
  applyDetune();
  if (target === 0) {
    arrangeToken += 1;
    job.notes = baseNotes.map((note) => ({ ...note }));
    clearError();
    renderSheet(job);
    draw();
    return;
  }
  const token = ++arrangeToken;
  const songId = job.id;
  const arranged = await api(`/api/songs/${songId}/arrange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ semitones: target }),
  });
  if (token !== arrangeToken || !job || job.id !== songId || semitones !== target) return;
  job.notes = arranged.notes || [];
  clearError();
  renderSheet(job);
  markTone();
  draw();
}

function markTone() {
  const moved = (job && job.notes || []).some((note) => note.shifted);
  if (!semitones) toneLabel.textContent = "Tono";
  else toneLabel.textContent = `Tono ${semitones > 0 ? "+" : "−"}${Math.abs(semitones)}${moved ? " · arreglo" : ""}`;
  toneDown.disabled = semitones <= -12;
  toneUp.disabled = semitones >= 12;
}

function applyDetune() {
  const cents = semitones * 100;
  for (const source of active) source.detune.value = cents;
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
