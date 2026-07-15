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
  activeJobTimer: null,
  schedulerPollTimer: null,
  hdhrPollTimer: null,
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

const hdhrState = {
  loaded: false,
  groups: [],
  groupFilter: "",
};

const dlnaState = {
  loaded: false,
};

function setHdhrForm(settings) {
  $("hdhr-enabled").checked = !!settings.enabled;
  $("hdhr-device-name").value = settings.device_name || "iptv-epg";
  $("hdhr-device-id").value = settings.device_id || "";
  $("hdhr-public-base-url").value = settings.public_base_url || "";
  $("hdhr-ffmpeg-path").value = settings.ffmpeg_path || "ffmpeg";
  $("hdhr-channel-limit").value = settings.channel_limit || 450;
  $("hdhr-tuner-count").value = settings.tuner_count || 1;
  $("hdhr-max-upstream-streams").value = settings.max_upstream_streams || 1;
  $("hdhr-stream-mode").value = settings.stream_mode || "direct";
  $("hdhr-buffer-seconds").value = settings.buffer_seconds ?? 30;
  $("hdhr-buffer-max-mb").value = settings.buffer_max_mb || 256;
  $("hdhr-conflict-policy").value = settings.conflict_policy || "reject_new";
  $("hdhr-stream-cleanup-enabled").checked = settings.stream_cleanup_enabled !== false;
  $("hdhr-max-stream-age-minutes").value = settings.max_stream_age_minutes || 240;
  $("hdhr-idle-timeout-seconds").value = settings.idle_timeout_seconds ?? 120;
  $("hdhr-cleanup-interval-seconds").value = settings.cleanup_interval_seconds || 30;
  $("hdhr-scheduled-drop-enabled").checked = !!settings.scheduled_drop_enabled;
  $("hdhr-scheduled-drop-time").value = settings.scheduled_drop_time || "04:00";
}

function renderHdhrGroups() {
  const list = $("hdhr-groups-list");
  if (!list) return;
  const q = hdhrState.groupFilter.trim().toLowerCase();
  const groups = hdhrState.groups.filter((group) => !q || group.name.toLowerCase().includes(q));
  if (!groups.length) {
    list.innerHTML = `<div class="hdhr-group-row muted">No selected groups found.</div>`;
    return;
  }
  list.innerHTML = groups
    .map(
      (group) => `
        <label class="hdhr-group-row">
          <input type="checkbox" class="hdhr-group-exclude" data-group-id="${group.id}" ${group.excluded ? "checked" : ""} />
          <span>${group.name}</span>
          <small>${group.selected_count || 0}</small>
        </label>
      `
    )
    .join("");
}

function hdhrExcludedGroupIdsFromForm() {
  return [...document.querySelectorAll(".hdhr-group-exclude:checked")].map((input) => input.dataset.groupId);
}

function hdhrPayloadFromForm() {
  return {
    enabled: $("hdhr-enabled").checked,
    device_name: $("hdhr-device-name").value.trim() || "iptv-epg",
    device_id: $("hdhr-device-id").value.trim(),
    public_base_url: $("hdhr-public-base-url").value.trim(),
    ffmpeg_path: $("hdhr-ffmpeg-path").value.trim() || "ffmpeg",
    channel_limit: Number($("hdhr-channel-limit").value || 450),
    excluded_group_ids: hdhrExcludedGroupIdsFromForm(),
    tuner_count: Number($("hdhr-tuner-count").value || 1),
    max_upstream_streams: Number($("hdhr-max-upstream-streams").value || 1),
    stream_mode: $("hdhr-stream-mode").value,
    buffer_seconds: Number($("hdhr-buffer-seconds").value || 0),
    buffer_max_mb: Number($("hdhr-buffer-max-mb").value || 256),
    conflict_policy: $("hdhr-conflict-policy").value,
    stream_cleanup_enabled: $("hdhr-stream-cleanup-enabled").checked,
    max_stream_age_minutes: Number($("hdhr-max-stream-age-minutes").value || 240),
    idle_timeout_seconds: Number($("hdhr-idle-timeout-seconds").value || 0),
    cleanup_interval_seconds: Number($("hdhr-cleanup-interval-seconds").value || 30),
    scheduled_drop_enabled: $("hdhr-scheduled-drop-enabled").checked,
    scheduled_drop_time: $("hdhr-scheduled-drop-time").value || "04:00",
  };
}

function updateHdhrLinks(settings) {
  const base = (settings.public_base_url || settings.resolved_base_url || window.location.origin).replace(/\/$/, "");
  $("hdhr-discover-link").href = `${base}/discover.json`;
  $("hdhr-lineup-link").href = `${base}/lineup.json`;
  $("hdhr-lineup-status-link").href = `${base}/lineup_status.json`;
  $("hdhr-catalogue-link").href = `${base}/api/hdhr/catalogue`;
  $("hdhr-m3u-link").href = `${base}/hdhr.m3u`;
  $("hdhr-epg-link").href = `${base}/hdhr_epg.xml`;
}

async function loadHdhr() {
  const body = await api("/api/hdhr/settings");
  setHdhrForm(body.settings || {});
  hdhrState.groups = body.groups || [];
  renderHdhrGroups();
  updateHdhrLinks(body.settings || {});
  renderJson("hdhr-json", body);
  hdhrState.loaded = true;
  setMessage("hdhr-message", body.settings?.enabled ? "HDHR enabled." : "HDHR disabled.");
  return body;
}

async function saveHdhr() {
  setMessage("hdhr-message", "Saving HDHR settings...");
  const body = await api("/api/hdhr/settings", {
    method: "POST",
    body: JSON.stringify(hdhrPayloadFromForm()),
  });
  setHdhrForm(body.settings || {});
  hdhrState.groups = body.groups || [];
  renderHdhrGroups();
  updateHdhrLinks(body.settings || {});
  renderJson("hdhr-json", body);
  setMessage("hdhr-message", "HDHR settings saved.");
  return body;
}

async function generateHdhrM3u() {
  setMessage("hdhr-message", "Generating proxy M3U...");
  const body = await api("/api/hdhr/generate-m3u", { method: "POST" });
  setMessage("hdhr-message", `Generated proxy M3U with ${body.selected_count || 0} channels.`);
  await loadHdhr();
}

async function stopHdhrStreams() {
  const body = await api("/api/hdhr/streams/stop", { method: "POST" });
  renderJson("hdhr-json", body);
  setMessage("hdhr-message", "Stopped active HDHR streams.");
}

function setDlnaForm(settings) {
  $("dlna-enabled").checked = settings.enabled !== false;
  $("dlna-device-name").value = settings.device_name || "iptv-epg DLNA";
  $("dlna-public-base-url").value = settings.public_base_url || "";
  $("dlna-stream-mode").value = settings.stream_mode || "copy";
}

function dlnaPayloadFromForm() {
  return {
    enabled: $("dlna-enabled").checked,
    device_name: $("dlna-device-name").value.trim() || "iptv-epg DLNA",
    public_base_url: $("dlna-public-base-url").value.trim(),
    stream_mode: $("dlna-stream-mode").value,
  };
}

function updateDlnaLinks(settings) {
  const base = (settings.public_base_url || settings.resolved_base_url || window.location.origin).replace(/\/$/, "");
  $("dlna-device-link").href = `${base}/dlna/device.xml`;
  $("dlna-content-directory-link").href = `${base}/dlna/content-directory.xml`;
  $("dlna-connection-manager-link").href = `${base}/dlna/connection-manager.xml`;
}

async function loadDlna() {
  const body = await api("/api/dlna/settings");
  setDlnaForm(body.settings || {});
  updateDlnaLinks(body.settings || {});
  renderJson("dlna-json", body);
  dlnaState.loaded = true;
  setMessage("dlna-message", body.settings?.enabled ? "DLNA enabled." : "DLNA disabled.");
  return body;
}

async function saveDlna() {
  setMessage("dlna-message", "Saving DLNA settings...");
  const body = await api("/api/dlna/settings", {
    method: "POST",
    body: JSON.stringify(dlnaPayloadFromForm()),
  });
  setDlnaForm(body.settings || {});
  updateDlnaLinks(body.settings || {});
  renderJson("dlna-json", body);
  setMessage("dlna-message", "DLNA settings saved.");
  return body;
}

async function refreshDlnaRequests() {
  const body = await api("/api/dlna/requests");
  renderJson("dlna-json", body);
  setMessage("dlna-message", `Loaded ${body.requests?.length || 0} DLNA request log entries.`);
  return body;
}

async function clearDlnaRequests() {
  const body = await api("/api/dlna/requests", { method: "DELETE" });
  renderJson("dlna-json", body);
  setMessage("dlna-message", "DLNA request log cleared.");
  return body;
}

function startHdhrPolling() {
  if (state.hdhrPollTimer) return;
  state.hdhrPollTimer = setInterval(async () => {
    try {
      const body = await api("/api/hdhr/status");
      renderJson("hdhr-json", {
        settings: hdhrPayloadFromForm(),
        ...body,
      });
    } catch (_err) {
      // Keep the tab quiet if the app is restarting.
    }
  }, 5000);
}

function stopHdhrPolling() {
  if (!state.hdhrPollTimer) return;
  clearInterval(state.hdhrPollTimer);
  state.hdhrPollTimer = null;
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


function moveItemInArray(items, index, direction) {
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= items.length) {
    return items;
  }

  const copy = [...items];
  const [item] = copy.splice(index, 1);
  copy.splice(nextIndex, 0, item);
  return copy;
}

async function saveGroupOrderFromVisibleGroups() {
  const groupIds = state.filteredGroups.map((group) => group.id);
  await api("/api/groups/order", {
    method: "POST",
    body: JSON.stringify({ group_ids: groupIds }),
  });
  setMessage("channels-info", "Saved group order.");
  await loadGroups(false);
}

async function moveGroup(groupId, direction) {
  const index = state.filteredGroups.findIndex((group) => group.id === groupId);
  if (index < 0) return;

  state.filteredGroups = moveItemInArray(state.filteredGroups, index, direction);
  renderGroups();
  await saveGroupOrderFromVisibleGroups();
}

async function saveChannelOrderFromVisibleChannels() {
  if (!state.selectedGroupId || !state.currentChannels) return;

  const channelIds = state.currentChannels.map((channel) => channel.id);
  await api("/api/channels/order", {
    method: "POST",
    body: JSON.stringify({
      group_id: state.selectedGroupId,
      channel_ids: channelIds,
    }),
  });
  setMessage("channels-info", "Saved channel order.");
}

async function moveChannel(channelId, direction) {
  if (!state.currentChannels) return;

  const index = state.currentChannels.findIndex((channel) => channel.id === channelId);
  if (index < 0) return;

  state.currentChannels = moveItemInArray(state.currentChannels, index, direction);
  renderChannels(state.currentChannels);
  await saveChannelOrderFromVisibleChannels();
}


function renderGroups() {
  const list = $("groups-list");
  list.innerHTML = "";

  if (!state.filteredGroups.length) {
    list.innerHTML = `<div class="group-row"><span>No groups loaded.</span></div>`;
    return;
  }

  const fragment = document.createDocumentFragment();

  for (const [index, group] of state.filteredGroups.entries()) {
    const row = document.createElement("div");
    row.className = "group-row";
    if (group.id === state.selectedGroupId) {
      row.classList.add("active");
    }

    row.innerHTML = `
      <span class="group-name" title="${escapeHtml(group.name)}">${escapeHtml(group.name)}</span>
      <span class="counts">${group.selected_count || 0}/${group.channel_count || 0}</span>
      <button class="order-button group-up" title="Move group up" ${index === 0 ? "disabled" : ""}>↑</button>
      <button class="order-button group-down" title="Move group down" ${index === state.filteredGroups.length - 1 ? "disabled" : ""}>↓</button>
    `;

    row.addEventListener("click", () => {
      state.selectedGroupId = group.id;
      state.selectedGroup = group;
      state.channelsOffset = 0;
      renderGroups();

      const channelsPane = document.querySelector(".channels-pane");
      const channelsList = $("channels-list");
      if (channelsPane) channelsPane.scrollTop = 0;
      if (channelsList) channelsList.scrollTop = 0;

      loadChannels().catch((err) => {
        $("selected-group-meta").textContent = "Could not load channels.";
        $("channels-list").innerHTML = `<div class="channel-row"><span></span><span></span><span>Could not load channels: ${escapeHtml(err.message)}</span><span></span><span></span><span></span></div>`;
        setMessage("channels-info", `Could not load channels: ${err.message}`, true);
      });
    });

    row.querySelector(".group-up").addEventListener("click", (event) => {
      event.stopPropagation();
      moveGroup(group.id, -1).catch((err) => setMessage("channels-info", `Could not move group: ${err.message}`, true));
    });

    row.querySelector(".group-down").addEventListener("click", (event) => {
      event.stopPropagation();
      moveGroup(group.id, 1).catch((err) => setMessage("channels-info", `Could not move group: ${err.message}`, true));
    });

    fragment.appendChild(row);
  }

  list.appendChild(fragment);
}


function resetSelectShownCheckbox() {
  const checkbox = $("select-shown-checkbox");
  if (!checkbox) return;

  checkbox.checked = false;
  checkbox.indeterminate = false;
  checkbox.disabled = true;
}

function updateSelectShownCheckbox() {
  const checkbox = $("select-shown-checkbox");
  if (!checkbox) return;

  const total = state.visibleChannelIds?.length || 0;
  const selected = state.visibleSelectedIds?.length || 0;

  checkbox.disabled = total === 0;
  checkbox.checked = total > 0 && selected === total;
  checkbox.indeterminate = selected > 0 && selected < total;

  const meta = $("shown-selection-meta");
  if (meta) {
    meta.textContent = total ? `${selected}/${total} shown selected` : "No shown channels";
  }
}


async function loadChannels(options = {}) {
  if (!state.selectedGroupId) return;

  const preserveScroll = Boolean(options.preserveScroll);
  const previousScrollTop = preserveScroll ? ($("channels-list")?.scrollTop || 0) : 0;

  $("selected-group-title").textContent = state.selectedGroup?.name || "Channels";
  $("selected-group-meta").textContent = "Loading channels…";
  $("shown-selection-meta").textContent = "Loading…";
  $("channels-list").innerHTML = "";
  resetSelectShownCheckbox();

  const result = await api(
    `/api/channels?group_id=${encodeURIComponent(state.selectedGroupId)}&offset=${state.channelsOffset}&limit=${state.channelsLimit}`
  );

  state.channelsTotal = result.total || 0;
  state.visibleChannelIds = (result.channels || []).map((c) => c.id);
  state.visibleSelectedIds = (result.channels || []).filter((c) => c.selected).map((c) => c.id);
  state.currentChannels = result.channels || [];

  $("selected-group-meta").textContent =
    `${state.channelsTotal} channels · showing ${state.channelsOffset + 1}-${Math.min(state.channelsOffset + state.channelsLimit, state.channelsTotal)}`;

  try {
    renderChannels(result.channels || []);
    const channelsList = $("channels-list");
    if (channelsList) channelsList.scrollTop = preserveScroll ? previousScrollTop : 0;
    updateSelectShownCheckbox();
  } catch (err) {
    $("selected-group-meta").textContent = "Could not render channels.";
    $("channels-list").innerHTML = `<div class="channel-row"><span></span><span></span><span>Could not render channels: ${escapeHtml(err.message)}</span><span></span><span></span><span></span></div>`;
    throw err;
  }
}

function renderChannels(channels) {
  state.currentChannels = Array.isArray(channels) ? channels : [];
  const list = $("channels-list");
  list.innerHTML = "";

  if (!state.currentChannels.length) {
    list.innerHTML = `<div class="channel-row"><span></span><span></span><span>No channels.</span><span></span><span></span><span></span></div>`;
    return;
  }

  const fragment = document.createDocumentFragment();

  for (const [index, channel] of state.currentChannels.entries()) {
    const row = document.createElement("div");
    row.className = "channel-row";

    const logo = channel.logo_url
      ? `<img src="${escapeAttr(channel.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />`
      : `<span></span>`;

    const tvg = channel.tvg_id ? `tvg-id: ${escapeHtml(channel.tvg_id)}` : "";
    row.innerHTML = `
      <input type="checkbox" ${channel.selected ? "checked" : ""} />
      ${logo}
      <div>
        <div class="channel-name" title="${escapeHtml(channel.name)}">${escapeHtml(channel.name)}</div>
        <div class="channel-meta">${tvg}</div>
      </div>
      <span class="muted">#${channel.provider_order}</span>
      <button class="order-button channel-up" title="Move channel up" ${index === 0 ? "disabled" : ""}>↑</button>
      <button class="order-button channel-down" title="Move channel down" ${index === state.currentChannels.length - 1 ? "disabled" : ""}>↓</button>
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
        await loadChannels({ preserveScroll: true });
      } catch (err) {
        checkbox.checked = !checkbox.checked;
        setMessage("channels-info", `Save failed: ${err.message}`, true);
      } finally {
        checkbox.disabled = false;
      }
    });

    row.querySelector(".channel-up").addEventListener("click", (event) => {
      event.stopPropagation();
      moveChannel(channel.id, -1).catch((err) => setMessage("channels-info", `Could not move channel: ${err.message}`, true));
    });

    row.querySelector(".channel-down").addEventListener("click", (event) => {
      event.stopPropagation();
      moveChannel(channel.id, 1).catch((err) => setMessage("channels-info", `Could not move channel: ${err.message}`, true));
    });

    fragment.appendChild(row);
  }

  list.appendChild(fragment);
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
    await loadChannels({ preserveScroll: true });
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

  if (tab === "guide") {
    startGuideAutoRefresh();
  } else {
    stopGuideAutoRefresh();
  }

  if (tab === "hdhr") {
    startHdhrPolling();
  } else {
    stopHdhrPolling();
  }

  if (tab === "channels" && !state.groups.length) {
    loadGroups(true).catch((err) => setMessage("channels-info", `Could not load groups: ${err.message}`, true));
  }

  if (tab === "epg" && !epgState.loaded) {
    loadEpgReview().catch((err) => {
      $("epg-job-status").textContent = `Could not load EPG review: ${err.message}`;
    });
  }

  if (tab === "guide" && !guideState.loaded) {
    loadGuideGroups().catch((err) => {
      $("guide-status").textContent = `Could not load guide groups: ${err.message}`;
    });
  }

  if (tab === "scheduler" && !schedulerState.loaded) {
    loadScheduler().catch((err) => setMessage("scheduler-message", `Could not load scheduler: ${err.message}`, true));
  }

  if (tab === "hdhr" && !hdhrState.loaded) {
    loadHdhr().catch((err) => setMessage("hdhr-message", `Could not load HDHR settings: ${err.message}`, true));
  }

  if (tab === "dlna" && !dlnaState.loaded) {
    loadDlna().catch((err) => setMessage("dlna-message", `Could not load DLNA settings: ${err.message}`, true));
  }

  if (["settings", "channels", "epg", "scheduler", "hdhr", "dlna", "guide"].includes(tab)) {
    history.replaceState(null, "", `#${tab}`);
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

  $("hdhr-save").addEventListener("click", () => {
    saveHdhr().catch((err) => setMessage("hdhr-message", `Save failed: ${err.message}`, true));
  });

  $("hdhr-generate-m3u").addEventListener("click", () => {
    generateHdhrM3u().catch((err) => setMessage("hdhr-message", `Generate failed: ${err.message}`, true));
  });

  $("hdhr-stop-streams").addEventListener("click", () => {
    stopHdhrStreams().catch((err) => setMessage("hdhr-message", `Stop failed: ${err.message}`, true));
  });
  $("hdhr-group-filter").addEventListener("input", (event) => {
    hdhrState.groupFilter = event.target.value;
    renderHdhrGroups();
  });

  $("dlna-save").addEventListener("click", () => {
    saveDlna().catch((err) => setMessage("dlna-message", `Save failed: ${err.message}`, true));
  });
  $("dlna-refresh-requests").addEventListener("click", () => {
    refreshDlnaRequests().catch((err) => setMessage("dlna-message", `Refresh failed: ${err.message}`, true));
  });
  $("dlna-clear-requests").addEventListener("click", () => {
    clearDlnaRequests().catch((err) => setMessage("dlna-message", `Clear failed: ${err.message}`, true));
  });
}

async function init() {
  wireEvents();
  wireEpgEvents();
  wireSchedulerEvents();
  wireGuideEvents();

  const initialTab = window.location.hash.replace("#", "");
  if (["settings", "channels", "epg", "scheduler", "hdhr", "dlna", "guide"].includes(initialTab)) {
    switchTab(initialTab);
  }

  try {
    await loadSettings();
    await loadStatus();
    setMessage("settings-message", "Ready.");
  } catch (err) {
    setMessage("settings-message", `Startup load failed: ${err.message}`, true);
    $("header-status").textContent = "Startup load failed";
  }
}



/* EPG tab integration */
const epgState = {
  review: null,
  rows: [],
  groups: [],
  filteredGroups: [],
  activeGroupName: null,
  activeChannelId: null,
  pending: null,
  manualSearch: {
    channelId: null,
    query: "",
    results: [],
  },
  loaded: false,
};

function epgStatusFor(row) {
  if (row.saved_mapping?.ignored) return "ignored";
  if (row.saved_mapping) return "saved";
  return row.status || "unmatched";
}

function epgMappingFromSaved(row) {
  if (!row.saved_mapping || row.saved_mapping.ignored) return null;
  return {
    channel_id: row.channel_id,
    xmltv_id: row.saved_mapping.xmltv_id,
    source_key: row.saved_mapping.source_key,
    mapping_type: row.saved_mapping.mapping_type || "manual",
    confidence: row.saved_mapping.confidence ?? null,
  };
}

function epgMappingFromOption(row, opt, mappingType = "manual") {
  return {
    channel_id: row.channel_id,
    xmltv_id: opt.xmltv_id,
    source_key: opt.source_key,
    mapping_type: mappingType,
    confidence: opt.confidence ?? 1,
  };
}

async function loadEpgReview() {
  const body = await api("/api/epgshare/mapping-review");
  epgState.review = body;
  epgState.rows = body.rows || [];
  epgState.groups = buildEpgGroups(epgState.rows);
  epgState.filteredGroups = [...epgState.groups];
  epgState.loaded = true;

  const activeRow = epgState.rows.find((row) => row.channel_id === epgState.activeChannelId);
  if (activeRow) {
    epgState.activeGroupName = activeRow.group_name || "Ungrouped";
  }

  if (!epgState.activeGroupName || !epgState.groups.some((group) => group.name === epgState.activeGroupName)) {
    epgState.activeGroupName = epgState.groups[0]?.name || null;
  }

  const rowsForGroup = epgRowsForActiveGroup();
  if (!epgState.activeChannelId && rowsForGroup.length) {
    epgState.activeChannelId = rowsForGroup[0].channel_id;
  }

  if (!rowsForGroup.some((row) => row.channel_id === epgState.activeChannelId)) {
    epgState.activeChannelId = rowsForGroup[0]?.channel_id || null;
  }

  epgState.pending = null;
  renderEpg();
  await loadEpgJobs();
}

async function refreshEpg() {
  await loadEpgReview();
}

function renderEpg() {
  renderEpgSummary();
  renderEpgGroupList();
  renderEpgChannelList();
  renderEpgDetail();
}


function epgOrderNumber(value, fallback = 999999999) {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function compareEpgGroupOrder(a, b) {
  const aHasUser = a.group_user_order !== null && a.group_user_order !== undefined;
  const bHasUser = b.group_user_order !== null && b.group_user_order !== undefined;

  if (aHasUser !== bHasUser) return aHasUser ? -1 : 1;

  const userDiff = epgOrderNumber(a.group_user_order) - epgOrderNumber(b.group_user_order);
  if (userDiff) return userDiff;

  const providerDiff = epgOrderNumber(a.group_provider_order) - epgOrderNumber(b.group_provider_order);
  if (providerDiff) return providerDiff;

  return String(a.name || "").localeCompare(String(b.name || ""));
}

function compareEpgChannelOrder(a, b) {
  const aHasUser = a.channel_user_order !== null && a.channel_user_order !== undefined;
  const bHasUser = b.channel_user_order !== null && b.channel_user_order !== undefined;

  if (aHasUser !== bHasUser) return aHasUser ? -1 : 1;

  const userDiff = epgOrderNumber(a.channel_user_order) - epgOrderNumber(b.channel_user_order);
  if (userDiff) return userDiff;

  const providerDiff = epgOrderNumber(a.channel_provider_order) - epgOrderNumber(b.channel_provider_order);
  if (providerDiff) return providerDiff;

  return String(a.name || "").localeCompare(String(b.name || ""));
}

function buildEpgGroups(rows) {
  const groupsByName = new Map();

  for (const row of rows) {
    const name = row.group_name || "Ungrouped";
    if (!groupsByName.has(name)) {
      groupsByName.set(name, {
        name,
        group_id: row.group_id,
        group_user_order: row.group_user_order,
        group_provider_order: row.group_provider_order,
        channel_count: 0,
        mapped_count: 0,
        unmatched_count: 0,
        ignored_count: 0,
      });
    }

    const group = groupsByName.get(name);
    group.channel_count += 1;

    const status = epgStatusFor(row);
    if (status === "saved" || status === "exact") group.mapped_count += 1;
    if (status === "unmatched") group.unmatched_count += 1;
    if (status === "ignored") group.ignored_count += 1;
  }

  return [...groupsByName.values()].sort(compareEpgGroupOrder);
}

function epgRowsForActiveGroup() {
  if (!epgState.activeGroupName) return [];
  return epgState.rows
    .filter((row) => (row.group_name || "Ungrouped") === epgState.activeGroupName)
    .sort(compareEpgChannelOrder);
}

function renderEpgGroupList() {
  if (!epgState.review) return;

  const filter = $("epg-group-filter")?.value.trim().toLowerCase() || "";
  epgState.filteredGroups = epgState.groups.filter((group) =>
    !filter || group.name.toLowerCase().includes(filter)
  );

  const list = $("epg-group-list");
  if (!list) return;

  if (!epgState.filteredGroups.length) {
    list.innerHTML = `<div class="epg-group-row"><strong>No groups.</strong></div>`;
    return;
  }

  list.innerHTML = epgState.filteredGroups.map((group) => `
    <div class="epg-group-row ${group.name === epgState.activeGroupName ? "active" : ""}" data-group-name="${escapeAttr(group.name)}">
      <strong title="${escapeAttr(group.name)}">${escapeHtml(group.name)}</strong>
      <div class="meta">${group.channel_count} channels · ${group.mapped_count} mapped · ${group.unmatched_count} unmatched</div>
    </div>
  `).join("");

  document.querySelectorAll(".epg-group-row[data-group-name]").forEach((el) => {
    el.addEventListener("click", () => {
      epgState.activeGroupName = el.dataset.groupName;
      const rows = epgRowsForActiveGroup();
      epgState.activeChannelId = rows[0]?.channel_id || null;
      epgState.pending = null;
      renderEpg();
    });
  });
}


function renderEpgSummary() {
  if (!epgState.review) return;
  const s = epgState.review.summary;
  $("epg-summary").innerHTML = `
    <span class="epg-pill">Selected <strong>${s.selected_channel_count}</strong></span>
    <span class="epg-pill">Exact <strong>${s.exact_match_count}</strong></span>
    <span class="epg-pill">Suggested <strong>${s.suggested_match_count}</strong></span>
    <span class="epg-pill">Unmatched <strong>${s.unmatched_count}</strong></span>
    <span class="epg-pill">Saved <strong>${s.saved_mapping_count}</strong></span>
    <span class="epg-pill">Required XML <strong>${s.required_source_count}</strong></span>
  `;
}

function renderEpgChannelList() {
  if (!epgState.review) return;

  const filter = $("epg-channel-filter").value.trim().toLowerCase();
  const rows = epgRowsForActiveGroup().filter((row) => {
    const haystack = `${row.name} ${row.tvg_id} ${row.group_name} ${epgStatusFor(row)}`.toLowerCase();
    return !filter || haystack.includes(filter);
  });

  if (!rows.length) {
    $("epg-channel-list").innerHTML = `<div class="epg-channel-card"><strong>No channels in this group.</strong></div>`;
    return;
  }

  $("epg-channel-list").innerHTML = rows.map((row) => `
    <div class="epg-channel-card ${row.channel_id === epgState.activeChannelId ? "active" : ""}" data-channel-id="${escapeAttr(row.channel_id)}">
      <strong>${escapeHtml(row.name)}</strong>
      <div class="meta">${escapeHtml(row.tvg_id || "")}</div>
      <div class="epg-badges">
        <span class="epg-status ${escapeAttr(epgStatusFor(row))}">${escapeHtml(epgStatusFor(row))}</span>
        ${row.recommended ? `<span class="epg-status">${escapeHtml(row.recommended.source_key)}</span>` : ""}
      </div>
    </div>
  `).join("");

  document.querySelectorAll(".epg-channel-card[data-channel-id]").forEach((el) => {
    el.addEventListener("click", () => {
      epgState.activeChannelId = el.dataset.channelId;
      epgState.pending = null;
      renderEpg();
    });
  });
}

function activeEpgRow() {
  return epgState.rows.find((row) => row.channel_id === epgState.activeChannelId) || null;
}

function renderEpgDetail() {
  const row = activeEpgRow();

  if (!row) {
    $("epg-detail").classList.add("hidden");
    $("epg-detail-empty").classList.remove("hidden");
    return;
  }

  $("epg-detail-empty").classList.add("hidden");
  $("epg-detail").classList.remove("hidden");

  $("epg-detail-title").textContent = row.name || "";
  $("epg-detail-meta").textContent = `${row.group_name || ""} · tvg-id: ${row.tvg_id || ""}`;
  $("epg-detail-status").textContent = epgStatusFor(row);
  $("epg-detail-status").className = `epg-status ${epgStatusFor(row)}`;

  if (epgState.manualSearch.channelId !== row.channel_id) {
    epgState.manualSearch = {
      channelId: row.channel_id,
      query: row.tvg_id || row.name || "",
      results: [],
    };
  }

  renderEpgLogoEditor(row);
  renderEpgCurrent(row);
  renderEpgSuggestions(row);
  $("epg-manual-query").value = epgState.manualSearch.query;
  renderEpgManualResults();
  $("epg-save-state").textContent = "";
}

function logoValue(value) {
  return String(value || "").trim();
}

function renderLogoPreview(url, label) {
  const clean = logoValue(url);
  if (!clean) {
    return `<div class="epg-logo-preview empty">No ${escapeHtml(label)} logo</div>`;
  }

  return `<img class="epg-logo-preview" src="${escapeAttr(clean)}" alt="${escapeAttr(label)} logo" loading="lazy" referrerpolicy="no-referrer" onerror="this.classList.add('broken')" />`;
}

function renderEpgLogoEditor(row) {
  const defaultLogo = logoValue(row.default_logo_url || row.logo_url);
  const preferredLogo = logoValue(row.preferred_logo_url);
  const currentLogo = logoValue(row.effective_logo_url || row.logo_url);

  $("epg-logo-editor").innerHTML = `
    <div class="epg-logo-grid">
      <div class="epg-logo-card">
        <h3>Default logo URL</h3>
        ${renderLogoPreview(defaultLogo, "default")}
        <input class="epg-logo-url" value="${escapeAttr(defaultLogo)}" readonly />
      </div>
      <div class="epg-logo-card">
        <h3>Custom logo URL</h3>
        ${renderLogoPreview(preferredLogo, "custom")}
        <input id="epg-preferred-logo-url" class="epg-logo-url" value="${escapeAttr(preferredLogo)}" placeholder="Paste custom logo URL" />
      </div>
      <div class="epg-logo-card">
        <h3>Current logo URL</h3>
        ${renderLogoPreview(currentLogo, "current")}
        <input class="epg-logo-url" value="${escapeAttr(currentLogo)}" readonly />
      </div>
    </div>
    <div class="epg-logo-actions">
      <button id="epg-save-logo">Save logo</button>
      <button id="epg-clear-logo">Use default</button>
      <span id="epg-logo-state" class="muted"></span>
    </div>
  `;

  $("epg-save-logo").addEventListener("click", () => saveEpgLogo(row.channel_id, $("epg-preferred-logo-url").value).catch((err) => alert(err.message)));
  $("epg-clear-logo").addEventListener("click", () => saveEpgLogo(row.channel_id, "").catch((err) => alert(err.message)));
}

async function saveEpgLogo(channelId, preferredLogoUrl) {
  $("epg-logo-state").textContent = "Saving...";
  const body = await api(`/api/channels/${encodeURIComponent(channelId)}/preferred-logo`, {
    method: "POST",
    body: JSON.stringify({ preferred_logo_url: preferredLogoUrl }),
  });

  const row = epgState.rows.find((item) => item.channel_id === channelId);
  if (row) {
    const tvgId = row.tvg_id || "";
    for (const item of epgState.rows) {
      if (tvgId && item.tvg_id !== tvgId) continue;
      if (!tvgId && item.channel_id !== channelId) continue;

      item.default_logo_url = body.default_logo_url || item.default_logo_url || item.logo_url || "";
      item.preferred_logo_url = body.preferred_logo_url || "";
      item.effective_logo_url = body.effective_logo_url || item.default_logo_url || "";
      item.logo_url = item.effective_logo_url;
    }
  }

  $("epg-logo-state").textContent = "Saved";
  renderEpgDetail();
}

function renderEpgCurrent(row) {
  const saved = row.saved_mapping;

  if (!saved) {
    $("epg-current-mapping").innerHTML = `<p>No saved mapping yet.</p>`;
    return;
  }

  if (saved.ignored) {
    $("epg-current-mapping").innerHTML = `<div class="epg-option selected"><strong>No EPG / ignored</strong><div class="meta">Saved ${escapeHtml(saved.updated_at)}</div></div>`;
    return;
  }

  $("epg-current-mapping").innerHTML = `
    <div class="epg-option selected">
      <strong>${escapeHtml(saved.xmltv_id)}</strong>
      <div class="meta">${escapeHtml(saved.source_key)} · ${escapeHtml(saved.mapping_type)} · saved ${escapeHtml(saved.updated_at)}</div>
    </div>
  `;
}

function renderEpgSuggestions(row) {
  const suggestions = row.suggestions || [];
  const pendingHtml = renderEpgPendingOption(row);

  const filteredSuggestions = suggestions.filter((opt) =>
    !epgState.pending ||
    epgState.pending.channel_id !== row.channel_id ||
    epgState.pending.xmltv_id !== opt.xmltv_id ||
    epgState.pending.source_key !== opt.source_key
  );

  const suggestionHtml = filteredSuggestions.length
    ? filteredSuggestions
        .map((opt, idx) => renderEpgOption(opt, idx === 0 ? "recommended" : "manual"))
        .join("")
    : `<p>No other suggestions. Use manual search.</p>`;

  $("epg-suggestions").innerHTML = `
    ${pendingHtml}
    ${pendingHtml ? `<h3 class="epg-subhead">Other options</h3>` : ""}
    ${suggestionHtml}
  `;

  wireEpgOptions();
}

function renderEpgPendingOption(row) {
  if (!epgState.pending || epgState.pending.channel_id !== row.channel_id) {
    return "";
  }

  return `
    <h3 class="epg-subhead">Preferred mapping</h3>
    ${renderEpgOption({
      xmltv_id: epgState.pending.xmltv_id,
      source_key: epgState.pending.source_key,
      confidence: epgState.pending.confidence ?? 1,
      reason: epgState.pending.mapping_type === "manual" ? "selected from manual search" : "selected option",
    }, epgState.pending.mapping_type || "manual")}
  `;
}

function renderEpgOption(opt, type) {
  const row = activeEpgRow();
  const pending = epgState.pending;
  const selected =
    row &&
    pending?.channel_id === row.channel_id &&
    pending?.xmltv_id === opt.xmltv_id &&
    pending?.source_key === opt.source_key;

  return `
    <div class="epg-option ${selected ? "selected" : ""}"
      data-xmltv-id="${escapeAttr(opt.xmltv_id)}"
      data-source-key="${escapeAttr(opt.source_key)}"
      data-confidence="${escapeAttr(opt.confidence ?? 1)}"
      data-type="${escapeAttr(type)}">
      <strong>${escapeHtml(opt.xmltv_id)}</strong>
      <div class="meta">${escapeHtml(opt.source_key)} · confidence ${escapeHtml(opt.confidence ?? "exact")}</div>
      <div class="reason">${escapeHtml(opt.reason || "exact/manual")} ${opt.country_match ? "· country match" : ""}</div>
    </div>
  `;
}

function wireEpgOptions() {
  document.querySelectorAll("#epg-suggestions .epg-option, #epg-manual-results .epg-option").forEach((el) => {
    el.addEventListener("click", () => {
      const row = activeEpgRow();
      if (!row) return;

      epgState.pending = {
        channel_id: row.channel_id,
        xmltv_id: el.dataset.xmltvId,
        source_key: el.dataset.sourceKey,
        mapping_type: el.dataset.type || "manual",
        confidence: Number(el.dataset.confidence || 1),
      };

      renderEpgSuggestions(row);
      renderEpgManualResults();
      $("epg-save-state").textContent = "Unsaved selection";
    });
  });
}

async function saveCurrentEpgMapping() {
  const row = activeEpgRow();
  const mapping =
    epgState.pending ||
    epgMappingFromSaved(row) ||
    (row.recommended ? epgMappingFromOption(row, row.recommended, row.status === "exact" ? "exact" : "suggested") : null);

  if (!mapping) {
    alert("Choose a mapping first.");
    return;
  }

  await saveEpgMappings([mapping]);
}

async function ignoreCurrentEpgMapping() {
  const row = activeEpgRow();
  await saveEpgMappings([{ channel_id: row.channel_id, ignored: true, mapping_type: "ignored" }]);
}

function applySavedEpgMappingsLocally(mappings) {
  const nowText = "just now";

  for (const mapping of mappings) {
    const row = epgState.rows.find((item) => item.channel_id === mapping.channel_id);
    if (!row) continue;
    const matchingRows = epgState.rows.filter((item) =>
      row.tvg_id ? item.tvg_id === row.tvg_id : item.channel_id === row.channel_id
    );

    if (mapping.ignored) {
      for (const item of matchingRows) {
        item.saved_mapping = {
          ignored: true,
          mapping_type: "ignored",
          updated_at: nowText,
        };
        item.status = "saved";
      }
      continue;
    }

    for (const item of matchingRows) {
      item.saved_mapping = {
        channel_id: item.channel_id,
        xmltv_id: mapping.xmltv_id,
        source_key: mapping.source_key,
        mapping_type: mapping.mapping_type || "manual",
        confidence: mapping.confidence ?? 1,
        ignored: false,
        updated_at: nowText,
      };
      item.status = "saved";
      item.recommended = {
        xmltv_id: mapping.xmltv_id,
        source_key: mapping.source_key,
        confidence: mapping.confidence ?? 1,
        reason: "saved mapping",
      };
    }
  }

  epgState.groups = buildEpgGroups(epgState.rows);
  epgState.filteredGroups = [...epgState.groups];
}

async function saveEpgMappings(mappings) {
  $("epg-save-state").textContent = "Saving...";
  const body = await api("/api/epgshare/mappings", {
    method: "POST",
    body: JSON.stringify({ mappings }),
  });

  if (!body.ok) {
    $("epg-save-state").textContent = "Save failed";
    alert(JSON.stringify(body));
    return;
  }

  applySavedEpgMappingsLocally(mappings);
  epgState.pending = null;
  $("epg-save-state").textContent = "Saved";
  renderEpg();
}

function renderEpgManualResults() {
  const row = activeEpgRow();
  const search = epgState.manualSearch;

  if (!row || search.channelId !== row.channel_id) {
    $("epg-manual-results").innerHTML = "";
    return;
  }

  if (!search.results.length) {
    $("epg-manual-results").innerHTML = "";
    return;
  }

  $("epg-manual-results").innerHTML = search.results
    .map((result) => renderEpgOption({
      xmltv_id: result.xmltv_id,
      source_key: result.source_key,
      confidence: result.confidence ?? 1,
      reason: result.reason || "manual search result",
    }, "manual"))
    .join("");

  wireEpgOptions();
}

async function manualEpgSearch() {
  const row = activeEpgRow();
  if (!row) return;

  const q = $("epg-manual-query").value.trim();
  epgState.manualSearch = {
    channelId: row.channel_id,
    query: q,
    results: [],
  };

  $("epg-manual-results").innerHTML = `<p>Searching...</p>`;

  const body = await api(`/api/epgshare/search?q=${encodeURIComponent(q)}&limit=30`);
  epgState.manualSearch.results = (body.results || []).map((result) => ({
    xmltv_id: result.xmltv_id,
    source_key: result.source_key,
    confidence: result.confidence ?? 1,
    reason: result.reason || "manual search result",
  }));

  renderEpgManualResults();

  if (!epgState.manualSearch.results.length) {
    $("epg-manual-results").innerHTML = `<p>No results.</p>`;
  }
}

async function importEpgIndex() {
  if (!confirm("Start EPGShare index import/update?")) return;
  const body = await api("/api/epgshare/index", { method: "POST" });
  alert(`Index job started: ${body.job_id}`);
  await loadEpgJobs();
}

async function generateEpgFromMappings() {
  if (!confirm("Generate filtered_epg.xml from saved mappings only?")) return;
  const body = await api("/api/epgshare/generate-filtered?days=3", { method: "POST" });
  alert(`Generation job started: ${body.job_id}`);
  await loadEpgJobs();
}

async function loadEpgJobs() {
  try {
    const body = await api("/api/jobs");
    const jobs = (body.jobs || []).filter((job) => String(job.job_type || "").startsWith("epgshare"));
    const latest = jobs[0];

    $("epg-job-status").innerHTML = latest
      ? `Latest EPGShare job: <strong>${escapeHtml(latest.status)}</strong> — ${escapeHtml(latest.message || latest.job_type || "")}`
      : "No EPGShare jobs yet.";
  } catch (err) {
    $("epg-job-status").textContent = `Could not load EPG jobs: ${err.message}`;
  }
}

function wireEpgEvents() {
  $("epg-refresh").addEventListener("click", () => refreshEpg().catch((err) => alert(err.message)));
  $("epg-group-filter").addEventListener("input", renderEpgGroupList);
  $("epg-channel-filter").addEventListener("input", renderEpgChannelList);
  $("epg-save-current").addEventListener("click", () => saveCurrentEpgMapping().catch((err) => alert(err.message)));
  $("epg-ignore-current").addEventListener("click", () => ignoreCurrentEpgMapping().catch((err) => alert(err.message)));
  $("epg-manual-query").addEventListener("input", () => {
    const row = activeEpgRow();
    if (!row) return;
    epgState.manualSearch.channelId = row.channel_id;
    epgState.manualSearch.query = $("epg-manual-query").value;
  });
  $("epg-manual-search").addEventListener("click", () => manualEpgSearch().catch((err) => alert(err.message)));
  $("epg-import-index").addEventListener("click", () => importEpgIndex().catch((err) => alert(err.message)));
  $("epg-generate").addEventListener("click", () => generateEpgFromMappings().catch((err) => alert(err.message)));
}


/* Guide tab integration */
const guideState = {
  groups: [],
  filteredGroups: [],
  dates: [],
  activeGroupId: null,
  selectedDate: null,
  autoRefreshTimer: null,
  loaded: false,
};

async function loadGuideGroups() {
  await loadGuideDates();
  const body = await api("/api/guide/groups");
  guideState.groups = body.groups || [];
  guideState.filteredGroups = [...guideState.groups];
  guideState.loaded = true;

  if (!guideState.activeGroupId && guideState.groups.length) {
    guideState.activeGroupId = guideState.groups[0].id;
  }

  renderGuideGroups();

  if (guideState.activeGroupId) {
    await loadGuideForGroup(guideState.activeGroupId);
  } else {
    $("guide-status").textContent = "No selected channels. Select channels first, then generate EPG.";
    $("guide-content").classList.add("hidden");
    $("guide-empty").classList.remove("hidden");
  }
}

function filterGuideGroups() {
  const term = $("guide-group-filter").value.trim().toLowerCase();
  guideState.filteredGroups = guideState.groups.filter((group) =>
    !term || `${group.name}`.toLowerCase().includes(term)
  );
  renderGuideGroups();
}

function renderGuideGroups() {
  const list = $("guide-group-list");
  list.innerHTML = "";

  if (!guideState.filteredGroups.length) {
    list.innerHTML = `<div class="guide-group-row"><strong>No groups with selected channels.</strong></div>`;
    return;
  }

  list.innerHTML = guideState.filteredGroups.map((group) => `
    <div class="guide-group-row ${group.id === guideState.activeGroupId ? "active" : ""}" data-group-id="${escapeAttr(group.id)}">
      <strong title="${escapeAttr(group.name)}">${escapeHtml(group.name)}</strong>
      <span class="muted">${group.selected_channel_count}</span>
    </div>
  `).join("");

  document.querySelectorAll(".guide-group-row[data-group-id]").forEach((row) => {
    row.addEventListener("click", () => {
      guideState.activeGroupId = row.dataset.groupId;
      renderGuideGroups();
      loadGuideForGroup(guideState.activeGroupId).catch((err) => {
        $("guide-status").textContent = `Could not load guide: ${err.message}`;
      });
    });
  });
}

async function loadGuideForGroup(groupId) {
  $("guide-status").textContent = "Loading guide…";
  $("guide-content").classList.add("hidden");
  $("guide-empty").classList.remove("hidden");
  $("guide-empty").textContent = "Loading guide…";

  const body = await api(`/api/guide?group_id=${encodeURIComponent(groupId)}`);

  if (!body.group) {
    $("guide-status").textContent = body.message || "No guide data.";
    $("guide-empty").textContent = body.message || "No guide data.";
    return;
  }

  renderGuide(body);
}

function formatGuideTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function renderGuide(body) {
  $("guide-status").textContent =
    `${body.group.name}: ${body.channel_count} selected channels · ${body.programme_count} programmes`;

  const content = $("guide-content");
  content.classList.remove("hidden");
  $("guide-empty").classList.add("hidden");

  content.innerHTML = (body.channels || []).map((channel) => {
    const logo = channel.logo_url
      ? `<img src="${escapeAttr(channel.logo_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />`
      : `<span></span>`;

    const programmes = (channel.programmes || []).length
      ? channel.programmes.map(renderGuideProgramme).join("")
      : `<div class="guide-programme"><strong>No programme data</strong><div class="desc">No matching EPG entries were found for ${escapeHtml(channel.tvg_id || channel.name)}.</div></div>`;

    return `
      <div class="guide-channel-row">
        <div class="guide-channel-info">
          ${logo}
          <div>
            <strong title="${escapeAttr(channel.name)}">${escapeHtml(channel.name)}</strong>
            <div class="muted">${escapeHtml(channel.tvg_id || "")}</div>
          </div>
        </div>
        <div class="guide-programmes">${programmes}</div>
      </div>
    `;
  }).join("");
}

function renderGuideProgramme(programme) {
  const title = programme.title || "Untitled";
  const desc = programme.desc || "";
  const time = `${formatGuideTime(programme.start)} – ${formatGuideTime(programme.stop)}`;

  return `
    <div class="guide-programme ${programme.is_now ? "now" : ""}">
      <div class="guide-programme-visible">
        <strong>${escapeHtml(title)}</strong>
        <div class="time">${escapeHtml(time)}${programme.is_now ? " · Now" : ""}</div>
        ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ""}
      </div>
      <div class="guide-programme-hover">
        <strong>${escapeHtml(title)}</strong>
        <div>${escapeHtml(time)}</div>
        ${desc ? `<div>${escapeHtml(desc)}</div>` : ""}
      </div>
    </div>
  `;
}

function wireGuideEvents() {
  const refreshButton = $("guide-refresh");
  if (refreshButton) {
    refreshButton.addEventListener("click", () => loadGuideGroups().catch((err) => {
      $("guide-status").textContent = `Could not refresh guide: ${err.message}`;
    }));
  }

  const groupFilter = $("guide-group-filter");
  if (groupFilter) {
    groupFilter.addEventListener("input", filterGuideGroups);
  }
}


/* Scheduler tab integration */
const schedulerState = {
  loaded: false,
  settings: null,
};

function renderScheduler(body) {
  schedulerState.loaded = true;
  schedulerState.settings = body;

  $("scheduler-enabled").checked = Boolean(body.enabled);
  $("scheduler-days").value = body.days || 3;
  $("scheduler-time").value = body.run_time || "04:00";
  renderJson("scheduler-json", body);

  const lastJob = body.last_job;
  if (lastJob) {
    const progress =
      lastJob.progress_total && lastJob.progress_total > 0
        ? ` (${lastJob.progress_current || 0}/${lastJob.progress_total})`
        : "";
    setMessage("scheduler-message", `${lastJob.status}: ${lastJob.message || ""}${progress}`, lastJob.status === "failed");
  } else if (body.enabled) {
    setMessage("scheduler-message", `Enabled. Next run is daily at ${body.run_time}.`);
  } else {
    setMessage("scheduler-message", "Scheduler is disabled.");
  }
}

async function loadScheduler() {
  const body = await api("/api/scheduler");
  renderScheduler(body);
  scheduleSchedulerRefresh(body);
}

function scheduleSchedulerRefresh(body) {
  if (state.schedulerPollTimer) {
    clearInterval(state.schedulerPollTimer);
    state.schedulerPollTimer = null;
  }

  if (body.last_job && body.last_job.status === "running") {
    state.schedulerPollTimer = setInterval(() => {
      loadScheduler().catch((err) => setMessage("scheduler-message", `Could not refresh scheduler: ${err.message}`, true));
    }, 3000);
  }
}

async function saveScheduler() {
  const payload = {
    enabled: $("scheduler-enabled").checked,
    days: Number($("scheduler-days").value || 3),
    run_time: $("scheduler-time").value || "04:00",
  };

  const body = await api("/api/scheduler", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderScheduler(body);
  setMessage("scheduler-message", body.enabled ? `Saved. Daily run set for ${body.run_time}.` : "Saved. Scheduler is disabled.");
}

async function runSchedulerNow() {
  setMessage("scheduler-message", "Starting scheduled EPG generation...");
  const body = await api("/api/scheduler/run-now", { method: "POST" });
  pollJob(body.job_id, "scheduler-message", async () => {
    await loadScheduler();
  });
  await loadScheduler();
}

function wireSchedulerEvents() {
  $("scheduler-save").addEventListener("click", () => {
    saveScheduler().catch((err) => setMessage("scheduler-message", `Save failed: ${err.message}`, true));
  });

  $("scheduler-run-now").addEventListener("click", () => {
    runSchedulerNow().catch((err) => setMessage("scheduler-message", `Run failed: ${err.message}`, true));
  });
}




async function loadGuideDates() {
  const body = await api("/api/guide/dates");
  guideState.dates = body.dates || [];

  if (!guideState.selectedDate) {
    const today = new Date().toISOString().slice(0, 10);
    const hasToday = guideState.dates.some((item) => item.date === today);
    guideState.selectedDate = hasToday ? today : (guideState.dates[0]?.date || today);
  }
}


/* Guide timeline-grid overrides */
const GUIDE_HOURS = 8; // fallback only; normal guide window runs to end of selected day
const GUIDE_HOUR_WIDTH = 360;

function floorDateToHalfHour(date) {
  const copy = new Date(date);
  copy.setMinutes(copy.getMinutes() >= 30 ? 30 : 0, 0, 0);
  return copy;
}

function initialiseGuideDate() {
  if (!guideState.selectedDate) {
    guideState.selectedDate = new Date().toISOString().slice(0, 10);
  }
}

function selectedGuideDate() {
  initialiseGuideDate();
  return guideState.selectedDate;
}

function currentGuideStart() {
  const active = guideState.windowStart ? new Date(guideState.windowStart) : null;
  if (active && !Number.isNaN(active.getTime())) return active;
  return guideStartForSelectedDate();
}

function guideStartForSelectedDate() {
  const selected = selectedGuideDate();
  const now = new Date();
  const today = now.toISOString().slice(0, 10);

  if (selected === today) {
    return floorDateToHalfHour(now);
  }

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(selected);
  if (!match) return floorDateToHalfHour(now);

  const start = new Date(Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    now.getUTCHours(),
    now.getUTCMinutes(),
    0,
    0
  ));

  return floorDateToHalfHour(start);
}

function guideHoursUntilEndOfDay(startDate) {
  const end = new Date(startDate);
  end.setHours(24, 0, 0, 0);

  const ms = end.getTime() - startDate.getTime();
  if (ms <= 0) return GUIDE_HOURS;

  // Round up to the next half hour so the end-of-day grid is complete.
  const hours = Math.ceil(ms / (30 * 60000)) / 2;
  return Math.max(1, Math.min(24, hours));
}


async function loadGuideForGroup(groupId, startDate = null, options = {}) {
  initialiseGuideDate();

  const quiet = Boolean(options.quiet);
  const preserveScroll = Boolean(options.preserveScroll);

  if (!quiet) {
    $("guide-status").textContent = "Loading guide…";
    $("guide-content").classList.add("hidden");
    $("guide-empty").classList.remove("hidden");
    $("guide-empty").textContent = "Loading guide…";
  }

  const windowStart = startDate || guideStartForSelectedDate();
  const guideHours = guideHoursUntilEndOfDay(windowStart);

  const params = new URLSearchParams({
    group_id: groupId,
    date: selectedGuideDate(),
    start: windowStart.toISOString(),
    hours: String(guideHours),
  });

  const body = await api(`/api/guide?${params.toString()}`);
  guideState.windowStart = body.window_start;
  guideState.windowEnd = body.window_end;

  if (!body.group) {
    $("guide-status").textContent = body.message || "No guide data.";
    $("guide-empty").textContent = body.message || "No guide data.";
    return;
  }

  renderGuide(body, { preserveScroll });
}

function formatGuideTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function guideOffsetPx(value, windowStart) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 0;
  return ((date.getTime() - windowStart.getTime()) / 3600000) * GUIDE_HOUR_WIDTH;
}

function guideWidthPx(start, stop, windowStart, windowEnd) {
  const startDate = new Date(start);
  const stopDate = new Date(stop);
  const leftDate = startDate < windowStart ? windowStart : startDate;
  const rightDate = stopDate > windowEnd ? windowEnd : stopDate;
  return Math.max(48, ((rightDate.getTime() - leftDate.getTime()) / 3600000) * GUIDE_HOUR_WIDTH - 6);
}

function guideStreamUrl(channelId) {
  return `/watch/${encodeURIComponent(channelId)}`;
}

function openGuideStream(channelId) {
  if (!channelId) return;
  window.open(guideStreamUrl(channelId), "_blank", "noopener");
}

function renderGuide(body, options = {}) {
  const windowStart = new Date(body.window_start);
  const windowEnd = new Date(body.window_end);
  const guideHours = Number(body.hours || GUIDE_HOURS);
  const timelineWidth = guideHours * GUIDE_HOUR_WIDTH;
  const now = new Date();

  $("guide-status").textContent =
    `${body.group.name}: ${body.channel_count} selected channels · ${body.programme_count} programmes · ${formatGuideTime(body.window_start)} – ${formatGuideTime(body.window_end)}`;

  const content = $("guide-content");
  const previousScrollLeft = options.preserveScroll ? content.scrollLeft : 0;
  const previousScrollTop = options.preserveScroll ? content.scrollTop : 0;
  content.classList.remove("hidden");
  $("guide-empty").classList.add("hidden");

  const ticks = [];
  for (let i = 0; i <= guideHours * 2; i++) {
    const tick = new Date(windowStart.getTime() + i * 30 * 60000);
    ticks.push(`
      <div class="guide-time-tick" style="left:${i * (GUIDE_HOUR_WIDTH / 2)}px">
        ${formatGuideTime(tick.toISOString())}
      </div>
    `);
  }

  const showNow = now >= windowStart && now <= windowEnd;
  const nowLeft = showNow ? guideOffsetPx(now.toISOString(), windowStart) : null;

  const rowsHtml = (body.channels || []).map((channel) => {
    const channelTooltip = [
      channel.name,
      channel.tvg_id ? `tvg-id: ${channel.tvg_id}` : "",
      channel.group_name ? `group: ${channel.group_name}` : "",
    ].filter(Boolean).join("\n");

    const logo = channel.logo_url
      ? `<img src="${escapeAttr(channel.logo_url)}" alt="${escapeAttr(channel.name || "")}" title="${escapeAttr(channelTooltip)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />`
      : `<div class="guide-channel-placeholder" title="${escapeAttr(channelTooltip)}">TV</div>`;

    const programmes = (channel.programmes || []).length
      ? channel.programmes.map((programme) => renderGuideProgramme(programme, windowStart, windowEnd, channel)).join("")
      : `<div class="guide-programme" style="left:0;width:180px"><strong>No programme data</strong><div class="desc">No matching EPG entries were found.</div></div>`;

    return `
      <div class="guide-channel-row" data-channel-id="${escapeAttr(channel.channel_id)}">
        <div class="guide-channel-info" data-channel-id="${escapeAttr(channel.channel_id)}">
          ${logo}
        </div>
        <div class="guide-timeline-row" data-channel-id="${escapeAttr(channel.channel_id)}" style="width:${timelineWidth}px">
          ${showNow ? `<div class="guide-now-line" style="left:${nowLeft}px"></div>` : ""}
          ${programmes}
        </div>
      </div>
    `;
  }).join("");

  content.innerHTML = `
    <div class="guide-grid" style="--hour-width:${GUIDE_HOUR_WIDTH}px">
      <div class="guide-time-header">
        <div class="guide-time-corner">${renderGuideDateSelect(body.date || selectedGuideDate())}</div>
        <div class="guide-time-axis" style="width:${timelineWidth}px">${ticks.join("")}</div>
      </div>
      ${rowsHtml}
    </div>
  `;

  content.scrollLeft = options.preserveScroll ? previousScrollLeft : 0;
  content.scrollTop = options.preserveScroll ? previousScrollTop : content.scrollTop;

  content.querySelectorAll(".guide-preview-button[data-channel-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openGuideStream(button.dataset.channelId);
    });
  });

  const dateSelect = document.getElementById("guide-date-select");
  if (dateSelect) {
    dateSelect.addEventListener("change", () => {
      guideState.selectedDate = dateSelect.value;
      guideState.windowStart = null;
      if (guideState.activeGroupId) {
        loadGuideForGroup(guideState.activeGroupId, guideStartForSelectedDate()).catch((err) => {
          $("guide-status").textContent = `Could not load guide date: ${err.message}`;
        });
      }
    });
  }
}

function renderGuideDateSelect(selectedDate) {
  const dates = guideState.dates.length
    ? guideState.dates
    : [{ date: selectedDate, label: "Today" }];

  return `
    <select id="guide-date-select" class="guide-date-select" aria-label="Guide date">
      ${dates.map((item) => `
        <option value="${escapeAttr(item.date)}" ${item.date === selectedDate ? "selected" : ""}>
          ${escapeHtml(item.label)}
        </option>
      `).join("")}
    </select>
  `;
}

function renderGuideProgramme(programme, windowStart, windowEnd, channel = null) {
  const title = programme.title || "Untitled";
  const desc = programme.desc || "";
  const time = `${formatGuideTime(programme.start)} – ${formatGuideTime(programme.stop)}`;

  const startDate = new Date(programme.start);
  const left = guideOffsetPx((startDate < windowStart ? windowStart : startDate).toISOString(), windowStart);
  const width = guideWidthPx(programme.start, programme.stop, windowStart, windowEnd);
  const channelId = channel?.channel_id || programme.channel || "";
  const preview = programme.is_now && channelId
    ? `
      <button class="guide-preview-button" type="button" data-channel-id="${escapeAttr(channelId)}" aria-label="Preview ${escapeAttr(channel?.name || title)}">
        <span class="guide-preview-icon" aria-hidden="true">▶</span>
        <span>Preview</span>
      </button>
    `
    : "";

  return `
    <div class="guide-programme ${programme.is_now ? "now" : ""}" style="left:${left}px;width:${width}px">
      <div class="guide-programme-visible">
        <strong>${escapeHtml(title)}</strong>
        <div class="time">${escapeHtml(time)}${programme.is_now ? " · Now" : ""}</div>
        ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ""}
      </div>
      ${preview}
      <div class="guide-programme-hover">
        <strong>${escapeHtml(title)}</strong>
        <div>${escapeHtml(time)}</div>
        ${desc ? `<div>${escapeHtml(desc)}</div>` : ""}
      </div>
    </div>
  `;
}

function stopGuideAutoRefresh() {
  if (guideState.autoRefreshTimer) {
    clearInterval(guideState.autoRefreshTimer);
    guideState.autoRefreshTimer = null;
  }
}

function startGuideAutoRefresh() {
  stopGuideAutoRefresh();

  guideState.autoRefreshTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    if (!document.getElementById("tab-guide")?.classList.contains("active")) return;
    if (!guideState.activeGroupId) return;

    const today = new Date().toISOString().slice(0, 10);
    if (selectedGuideDate() !== today) return;

    guideState.windowStart = null;

    loadGuideForGroup(guideState.activeGroupId, guideStartForSelectedDate(), {
      quiet: true,
      preserveScroll: true,
    }).catch((err) => {
      $("guide-status").textContent = `Could not auto-refresh guide: ${err.message}`;
    });
  }, 60000);
}

function wireGuideEvents() {
  initialiseGuideDate();

  const refreshButton = $("guide-refresh");
  if (refreshButton) {
    refreshButton.addEventListener("click", () => {
      const start = currentGuideStart();
      loadGuideGroups().then(() => {
        if (guideState.activeGroupId) return loadGuideForGroup(guideState.activeGroupId, start);
      }).catch((err) => {
        $("guide-status").textContent = `Could not refresh guide: ${err.message}`;
      });
    });
  }

  const groupFilter = $("guide-group-filter");
  if (groupFilter) {
    groupFilter.addEventListener("input", filterGuideGroups);
  }
}


// Start the app after every tab module has been declared.
init().catch((err) => {
  console.error(err);
  const status = document.getElementById("header-status") || document.getElementById("guide-status");
  if (status) status.textContent = `Startup failed: ${err.message || err}`;
});
