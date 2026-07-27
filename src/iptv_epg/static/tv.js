const tvState = {
  groups: [],
  channels: [],
  activeGroupIndex: 0,
  focusedPane: "groups",
  focusedGroupIndex: 0,
  focusedChannelIndex: 0,
  selectedDate: "",
  windowStart: null,
  loading: false,
};

const $ = (id) => document.getElementById(id);

async function api(path) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" } });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.detail || response.statusText);
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function floorDateToHalfHour(date) {
  const copy = new Date(date);
  copy.setMinutes(copy.getMinutes() >= 30 ? 30 : 0, 0, 0);
  return copy;
}

function setStatus(message) {
  $("tv-status").textContent = message;
}

function updateClock() {
  $("tv-clock").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scrollFocusedIntoView(selector) {
  const focused = document.querySelector(selector);
  if (focused) {
    focused.scrollIntoView({ block: "nearest" });
  }
}

function renderGroups() {
  const groupsEl = $("tv-groups");
  if (!tvState.groups.length) {
    groupsEl.innerHTML = `<div class="tv-empty">No selected channel groups.</div>`;
    return;
  }

  groupsEl.innerHTML = tvState.groups.map((group, index) => `
    <div class="tv-group ${index === tvState.activeGroupIndex ? "active" : ""} ${tvState.focusedPane === "groups" && index === tvState.focusedGroupIndex ? "focused" : ""}" data-index="${index}">
      <strong>${escapeHtml(group.name)}</strong>
      <span class="tv-count">${group.selected_channel_count || 0}</span>
    </div>
  `).join("");

  scrollFocusedIntoView(".tv-group.focused");
}

function programmeCard(programme, fallback) {
  if (!programme) {
    return `
      <div class="tv-programme">
        <strong>${escapeHtml(fallback)}</strong>
        <span>No programme data</span>
      </div>
    `;
  }
  const time = `${formatTime(programme.start)} - ${formatTime(programme.stop)}`;
  return `
    <div class="tv-programme ${programme.is_now ? "now" : ""}">
      <strong>${escapeHtml(programme.title || "Unknown")}</strong>
      <span>${escapeHtml(time)}${programme.is_now ? " · Now" : ""}</span>
    </div>
  `;
}

function renderChannels() {
  const guideEl = $("tv-guide");
  const group = tvState.groups[tvState.activeGroupIndex];
  $("tv-group-title").textContent = group?.name || "Guide";
  $("tv-group-meta").textContent = tvState.channels.length
    ? `${tvState.channels.length} channels · Enter plays highlighted channel`
    : "No channels in this group";

  if (!tvState.channels.length) {
    guideEl.innerHTML = `<div class="tv-empty">No selected channels.</div>`;
    return;
  }

  guideEl.innerHTML = tvState.channels.map((channel, index) => {
    const programmes = channel.programmes || [];
    const current = programmes.find((item) => item.is_now) || programmes[0];
    const next = programmes.find((item) => !item.is_now && item.start && (!current?.stop || item.start >= current.stop));
    const logo = channel.logo_url
      ? `<img class="tv-logo" src="${escapeAttr(channel.logo_url)}" alt="" referrerpolicy="no-referrer" onerror="this.replaceWith(logoFallback())" />`
      : `<div class="tv-logo-fallback">TV</div>`;

    return `
      <div class="tv-channel ${tvState.focusedPane === "channels" && index === tvState.focusedChannelIndex ? "focused" : ""}" data-index="${index}">
        <div>${logo}</div>
        <div>
          <div class="tv-channel-name">${escapeHtml(channel.name)}</div>
          <div class="tv-channel-meta">${escapeHtml(channel.tvg_id || channel.group_name || "")}</div>
        </div>
        <div class="tv-programmes">
          ${programmeCard(current, "Unknown")}
          ${programmeCard(next, "Next")}
        </div>
      </div>
    `;
  }).join("");

  scrollFocusedIntoView(".tv-channel.focused");
}

function logoFallback() {
  const fallback = document.createElement("div");
  fallback.className = "tv-logo-fallback";
  fallback.textContent = "TV";
  return fallback;
}

async function loadGroups() {
  setStatus("Loading groups...");
  const body = await api("/api/guide/groups");
  tvState.groups = body.groups || [];
  tvState.activeGroupIndex = 0;
  tvState.focusedGroupIndex = 0;
  renderGroups();
  if (tvState.groups.length) {
    await loadActiveGroup();
  } else {
    setStatus("No selected channels");
  }
}

async function loadActiveGroup() {
  if (tvState.loading) return;
  const group = tvState.groups[tvState.activeGroupIndex];
  if (!group) return;

  tvState.loading = true;
  setStatus("Loading guide...");
  try {
    const start = floorDateToHalfHour(new Date()).toISOString();
    const params = new URLSearchParams({
      group_id: group.id,
      start,
      hours: "6",
    });
    const body = await api(`/api/guide?${params.toString()}`);
    tvState.channels = body.channels || [];
    tvState.focusedChannelIndex = Math.min(tvState.focusedChannelIndex, Math.max(0, tvState.channels.length - 1));
    tvState.windowStart = body.window_start;
    renderGroups();
    renderChannels();
    setStatus("Ready");
  } catch (err) {
    setStatus(`Guide failed: ${err.message}`);
  } finally {
    tvState.loading = false;
  }
}

function moveFocus(delta) {
  if (tvState.focusedPane === "groups") {
    tvState.focusedGroupIndex = Math.max(0, Math.min(tvState.groups.length - 1, tvState.focusedGroupIndex + delta));
    renderGroups();
    return;
  }

  tvState.focusedChannelIndex = Math.max(0, Math.min(tvState.channels.length - 1, tvState.focusedChannelIndex + delta));
  renderChannels();
}

async function activateFocused() {
  if (tvState.focusedPane === "groups") {
    tvState.activeGroupIndex = tvState.focusedGroupIndex;
    tvState.focusedChannelIndex = 0;
    await loadActiveGroup();
    return;
  }

  const channel = tvState.channels[tvState.focusedChannelIndex];
  if (channel) {
    playChannel(channel);
  }
}

function playChannel(channel) {
  const playerShell = $("tv-player-shell");
  const player = $("tv-player");
  $("tv-player-title").textContent = channel.name || "Channel";
  playerShell.classList.remove("hidden");
  player.src = `/dlna/channel/${encodeURIComponent(channel.channel_id)}.mpg`;
  const playPromise = player.play();
  if (playPromise?.catch) {
    playPromise.catch((err) => setStatus(`Playback failed: ${err.message}`));
  }
}

function stopPlayback() {
  const playerShell = $("tv-player-shell");
  const player = $("tv-player");
  player.pause();
  player.removeAttribute("src");
  player.load();
  playerShell.classList.add("hidden");
}

function playerOpen() {
  return !$("tv-player-shell").classList.contains("hidden");
}

function handleKey(event) {
  const key = event.key || event.code;
  const code = event.keyCode || event.which || 0;
  const normalisedKey = ({
    13: "Enter",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    10009: "Backspace",
  })[code] || key;

  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Backspace", "Escape"].includes(normalisedKey)) {
    event.preventDefault();
  }

  if (playerOpen()) {
    if (["Backspace", "Escape", "BrowserBack", "GoBack"].includes(normalisedKey)) {
      stopPlayback();
    }
    return;
  }

  if (normalisedKey === "ArrowUp") moveFocus(-1);
  if (normalisedKey === "ArrowDown") moveFocus(1);
  if (normalisedKey === "ArrowRight") {
    tvState.focusedPane = "channels";
    renderGroups();
    renderChannels();
  }
  if (normalisedKey === "ArrowLeft") {
    tvState.focusedPane = "groups";
    renderGroups();
    renderChannels();
  }
  if (normalisedKey === "Enter") {
    activateFocused().catch((err) => setStatus(`Action failed: ${err.message}`));
  }
  if (["Backspace", "Escape", "BrowserBack", "GoBack"].includes(normalisedKey)) {
    tvState.focusedPane = "groups";
    renderGroups();
    renderChannels();
  }
}

document.addEventListener("keydown", handleKey);
setInterval(updateClock, 15000);
updateClock();
loadGroups().catch((err) => setStatus(`Startup failed: ${err.message}`));
