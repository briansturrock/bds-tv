const state = {
  status: null,
  groups: [],
  filteredGroups: [],
  selectedGroupId: null,
  selectedGroup: null,
  channelsOffset: 0,
  channelsLimit: 200,
  channelsTotal: 0,
  visibleChannelIds: [],
  visibleSelectedIds: [],
  visibleChannels: [],
  activeJobTimer: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  let body = null;
  if (contentType.includes("application/json")) {
    body = await response.json();
  } else {
    body = await response.text();
  }

  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText;
    throw new Error(detail);
  }

  return body;
}

function setMessage(id, text, isError = false) {
  const el = $(id);
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function renderJson(id, value) {
  $(id).textContent = JSON.stringify(value, null, 2);
}

async function loadStatus() {
  const status = await api("/api/status");
  state.status = status;
  $("header-status").textContent =
    `${status.version} · ${status.group_count || 0} groups · ${status.channel_count || 0} channels · ${status.selected_count || 0} selected`;
  renderJson("status-json", status);
  return status;
}

async function loadSettings() {
  const settings = await api("/api/settings");
  $("m3u-url").value = settings.m3u_url || "";
}

async function saveSettings() {
  const m3uUrl = $("m3u-url").value.trim();
  const result = await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({ m3u_url: m3uUrl }),
  });
  setMessage("settings-message", "Settings saved.");
  return result;
}

async function startFetchM3u() {
  setMessage("settings-message", "Starting M3U fetch/index…");
  const result = await api("/api/m3u/fetch", { method: "POST" });
  pollJob(result.job_id, "settings-message", async () => {
    await loadStatus();
    await loadGroups(false);
  });
}

async function generateFilteredM3u() {
  setMessage("channels-info", "Starting filtered M3U generation…");
  const result = await api("/api/m3u/generate-filtered", { method: "POST" });
  pollJob(result.job_id, "channels-info", async () => {
    await loadStatus();
  });
}

function pollJob(jobId, messageElementId, onComplete) {
  if (state.activeJobTimer) {
    clearInterval(state.activeJobTimer);
  }

  async function tick() {
    try {
      const result = await api(`/api/jobs/${jobId}`);
      const job = result.job;
      const progress =
        job.progress_total && job.progress_total > 0
          ? ` (${job.progress_current || 0}/${job.progress_total})`
          : "";
      setMessage(messageElementId, `${job.status}: ${job.message || ""}${progress}`, job.status === "failed");

      if (job.status === "complete" || job.status === "failed") {
        clearInterval(state.activeJobTimer);
        state.activeJobTimer = null;
        if (job.status === "complete" && onComplete) {
          await onComplete(job);
        }
      }
    } catch (err) {
      setMessage(messageElementId, `Job polling failed: ${err.message}`, true);
      clearInterval(state.activeJobTimer);
      state.activeJobTimer = null;
    }
  }

  tick();
  state.activeJobTimer = setInterval(tick, 2000);
}

async function loadGroups(showMessage = true) {
  if (showMessage) {
    setMessage("channels-info", "Loading groups…");
  }
  const result = await api("/api/groups");
  state.groups = result.groups || [];
  filterGroups();
  if (showMessage) {
    setMessage(
      "channels-info",
      `Loaded ${state.groups.length} groups. ${state.status?.selected_count || 0} channels selected.`
    );
  }
}

function filterGroups() {
  const q = $("group-search").value.trim().toLowerCase();
  state.filteredGroups = state.groups.filter((g) => !q || g.name.toLowerCase().includes(q));
  renderGroups();
}

function selectedGroupsInCurrentOrder() {
  return state.groups.filter((g) => (g.selected_count || 0) > 0);
}

async function saveSelectedGroupOrder() {
  const groupIds = selectedGroupsInCurrentOrder().map((g) => g.id);
  await api("/api/groups/order", {
    method: "POST",
    body: JSON.stringify({ group_ids: groupIds }),
  });
}

async function moveSelectedGroup(groupId, direction) {
  const selectedGroups = selectedGroupsInCurrentOrder();
  const from = selectedGroups.findIndex((g) => g.id === groupId);
  if (from < 0) return;

  const to = from + direction;
  if (to < 0 || to >= selectedGroups.length) return;

  const selectedIds = new Set(selectedGroups.map((g) => g.id));
  const globalFrom = state.groups.findIndex((g) => g.id === selectedGroups[from].id);
  const globalTo = state.groups.findIndex((g) => g.id === selectedGroups[to].id);

  const temp = state.groups[globalFrom];
  state.groups[globalFrom] = state.groups[globalTo];
  state.groups[globalTo] = temp;

  try {
    await saveSelectedGroupOrder();
    setMessage("channels-info", "Saved group order.");
    filterGroups();
  } catch (err) {
    setMessage("channels-info", `Could not save group order: ${err.message}`, true);
    await loadGroups(false);
  }
}

function renderGroups() {
  const list = $("groups-list");
  list.innerHTML = "";

  if (!state.filteredGroups.length) {
    list.innerHTML = `<div class="group-row"><span>No groups loaded.</span></div>`;
    return;
  }

  const selectedGroups = selectedGroupsInCurrentOrder();
  const selectedIndexById = new Map(selectedGroups.map((g, i) => [g.id, i]));
  const fragment = document.createDocumentFragment();

  for (const group of state.filteredGroups) {
    const row = document.createElement("div");
    row.className = "group-row";
    if (group.id === state.selectedGroupId) {
      row.classList.add("active");
    }

    const selectedIndex = selectedIndexById.get(group.id);
    const canOrder = selectedIndex !== undefined;
    const upDisabled = !canOrder || selectedIndex === 0;
    const downDisabled = !canOrder || selectedIndex === selectedGroups.length - 1;

    row.innerHTML = `
      <span title="${escapeHtml(group.name)}">${escapeHtml(group.name)}</span>
      <span class="counts">${group.selected_count || 0}/${group.channel_count || 0}</span>
      <span class="order-buttons">
        <button class="group-up" title="Move selected group up" ${upDisabled ? "disabled" : ""}>↑</button>
        <button class="group-down" title="Move selected group down" ${downDisabled ? "disabled" : ""}>↓</button>
      </span>
    `;

    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      state.selectedGroupId = group.id;
      state.selectedGroup = group;
      state.channelsOffset = 0;
      renderGroups();
      loadChannels();
    });

    row.querySelector(".group-up").addEventListener("click", () => moveSelectedGroup(group.id, -1));
    row.querySelector(".group-down").addEventListener("click", () => moveSelectedGroup(group.id, 1));

    fragment.appendChild(row);
  }

  list.appendChild(fragment);
}

async function loadChannels() {
  if (!state.selectedGroupId) return;

  $("selected-group-title").textContent = state.selectedGroup?.name || "Channels";
  $("selected-group-meta").textContent = "Loading channels…";
  $("shown-selection-meta").textContent = "Loading…";
  $("channels-list").innerHTML = "";
  resetSelectShownCheckbox();

  const result = await api(
    `/api/channels?group_id=${encodeURIComponent(state.selectedGroupId)}&offset=${state.channelsOffset}&limit=${state.channelsLimit}`
  );

  state.channelsTotal = result.total || 0;
  state.visibleChannels = result.channels || [];
  state.visibleChannelIds = state.visibleChannels.map((c) => c.id);
  state.visibleSelectedIds = state.visibleChannels.filter((c) => c.selected).map((c) => c.id);

  $("selected-group-meta").textContent =
    `${state.channelsTotal} channels · showing ${state.channelsOffset + 1}-${Math.min(state.channelsOffset + state.channelsLimit, state.channelsTotal)}`;

  renderChannels(state.visibleChannels);
  updateSelectShownCheckbox();
}

function selectedVisibleChannelsInOrder() {
  return state.visibleChannels.filter((c) => c.selected);
}

async function saveSelectedChannelOrder() {
  const channelIds = selectedVisibleChannelsInOrder().map((c) => c.id);
  if (!state.selectedGroupId || !channelIds.length) return;

  await api("/api/channels/order", {
    method: "POST",
    body: JSON.stringify({ group_id: state.selectedGroupId, channel_ids: channelIds }),
  });
}

async function moveSelectedChannel(channelId, direction) {
  const selectedChannels = selectedVisibleChannelsInOrder();
  const from = selectedChannels.findIndex((c) => c.id === channelId);
  if (from < 0) return;

  const to = from + direction;
  if (to < 0 || to >= selectedChannels.length) return;

  const globalFrom = state.visibleChannels.findIndex((c) => c.id === selectedChannels[from].id);
  const globalTo = state.visibleChannels.findIndex((c) => c.id === selectedChannels[to].id);

  const temp = state.visibleChannels[globalFrom];
  state.visibleChannels[globalFrom] = state.visibleChannels[globalTo];
  state.visibleChannels[globalTo] = temp;

  try {
    await saveSelectedChannelOrder();
    setMessage("channels-info", "Saved channel order.");
    renderChannels(state.visibleChannels);
    updateSelectShownCheckbox();
  } catch (err) {
    setMessage("channels-info", `Could not save channel order: ${err.message}`, true);
    await loadChannels();
  }
}

function renderChannels(channels) {
  const list = $("channels-list");
  list.innerHTML = "";

  if (!channels.length) {
    list.innerHTML = `<div class="channel-row"><span></span><span></span><span>No channels.</span><span></span><span></span></div>`;
    return;
  }

  const selectedChannels = channels.filter((c) => c.selected);
  const selectedIndexById = new Map(selectedChannels.map((c, i) => [c.id, i]));
  const fragment = document.createDocumentFragment();

  for (const channel of channels) {
    const row = document.createElement("div");
    row.className = "channel-row";

    const logo = channel.logo_url
      ? `<img src="${escapeAttr(channel.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />`
      : `<span></span>`;

    const tvg = channel.tvg_id ? `tvg-id: ${escapeHtml(channel.tvg_id)}` : "";
    const selectedIndex = selectedIndexById.get(channel.id);
    const canOrder = selectedIndex !== undefined;
    const upDisabled = !canOrder || selectedIndex === 0;
    const downDisabled = !canOrder || selectedIndex === selectedChannels.length - 1;

    row.innerHTML = `
      <input type="checkbox" ${channel.selected ? "checked" : ""} />
      ${logo}
      <div>
        <div class="channel-name" title="${escapeHtml(channel.name)}">${escapeHtml(channel.name)}</div>
        <div class="channel-meta">${tvg}</div>
      </div>
      <span class="muted">#${channel.provider_order}</span>
      <span class="order-buttons">
        <button class="channel-up" title="Move selected channel up" ${upDisabled ? "disabled" : ""}>↑</button>
        <button class="channel-down" title="Move selected channel down" ${downDisabled ? "disabled" : ""}>↓</button>
      </span>
    `;

    const checkbox = row.querySelector("input");
    checkbox.addEventListener("change", async () => {
      checkbox.disabled = true;
      try {
        await api("/api/channels/select", {
          method: "POST",
          body: JSON.stringify({ channel_ids: [channel.id], selected: checkbox.checked }),
        });
        setMessage("channels-info", `Saved: ${channel.name} ${checkbox.checked ? "selected" : "unselected"}.`);
        await loadStatus();
        await loadGroups(false);
        await loadChannels();
      } catch (err) {
        checkbox.checked = !checkbox.checked;
        setMessage("channels-info", `Selection failed: ${err.message}`, true);
      } finally {
        checkbox.disabled = false;
      }
    });

    row.querySelector(".channel-up").addEventListener("click", () => moveSelectedChannel(channel.id, -1));
    row.querySelector(".channel-down").addEventListener("click", () => moveSelectedChannel(channel.id, 1));

    fragment.appendChild(row);
  }

  list.appendChild(fragment);
}

function resetSelectShownCheckbox() {
  const checkbox = $("select-shown-checkbox");
  checkbox.checked = false;
  checkbox.indeterminate = false;
  checkbox.disabled = true;
}

function updateSelectShownCheckbox() {
  const checkbox = $("select-shown-checkbox");
  const total = state.visibleChannelIds.length;
  const selected = state.visibleSelectedIds.length;

  checkbox.disabled = total === 0;
  checkbox.checked = total > 0 && selected === total;
  checkbox.indeterminate = selected > 0 && selected < total;

  $("shown-selection-meta").textContent =
    total === 0 ? "No channels shown." : `${selected}/${total} shown channels selected.`;
}

async function setShownChannelsSelected(selected) {
  if (!state.visibleChannelIds.length) return;

  const checkbox = $("select-shown-checkbox");
  checkbox.disabled = true;
  setMessage("channels-info", selected ? "Selecting shown channels…" : "Unselecting shown channels…");

  try {
    await api("/api/channels/select", {
      method: "POST",
      body: JSON.stringify({ channel_ids: state.visibleChannelIds, selected }),
    });

    await loadStatus();
    await loadGroups(false);
    await loadChannels();
    setMessage("channels-info", selected ? "Saved: shown channels selected." : "Saved: shown channels unselected.");
  } catch (err) {
    setMessage("channels-info", `Selection failed: ${err.message}`, true);
    updateSelectShownCheckbox();
  }
}

function nextPage() {
  if (state.channelsOffset + state.channelsLimit >= state.channelsTotal) return;
  state.channelsOffset += state.channelsLimit;
  loadChannels();
}

function prevPage() {
  state.channelsOffset = Math.max(0, state.channelsOffset - state.channelsLimit);
  loadChannels();
}

function switchTab(tab) {
  document.querySelectorAll(".tab-button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${tab}`));

  if (tab === "channels" && !state.groups.length) {
    loadGroups(true).catch((err) => setMessage("channels-info", `Could not load groups: ${err.message}`, true));
  }
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

function wireEvents() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  $("save-settings").addEventListener("click", () => {
    saveSettings().catch((err) => setMessage("settings-message", `Save failed: ${err.message}`, true));
  });

  $("fetch-m3u").addEventListener("click", () => {
    startFetchM3u().catch((err) => setMessage("settings-message", `Fetch failed: ${err.message}`, true));
  });

  $("refresh-groups").addEventListener("click", () => {
    loadGroups(true).catch((err) => setMessage("channels-info", `Could not load groups: ${err.message}`, true));
  });

  $("generate-m3u").addEventListener("click", () => {
    generateFilteredM3u().catch((err) => setMessage("channels-info", `Generate failed: ${err.message}`, true));
  });

  $("group-search").addEventListener("input", filterGroups);
  $("select-shown-checkbox").addEventListener("change", (event) => setShownChannelsSelected(event.target.checked));
  $("next-page").addEventListener("click", nextPage);
  $("prev-page").addEventListener("click", prevPage);
}

async function init() {
  wireEvents();
  try {
    await loadSettings();
    await loadStatus();
    setMessage("settings-message", "Ready.");
  } catch (err) {
    setMessage("settings-message", `Startup load failed: ${err.message}`, true);
    $("header-status").textContent = "Startup load failed";
  }
}

init();
