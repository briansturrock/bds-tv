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
  state.visibleChannelIds = (result.channels || []).map((c) => c.id);
  state.visibleSelectedIds = (result.channels || []).filter((c) => c.selected).map((c) => c.id);
  state.currentChannels = result.channels || [];

  $("selected-group-meta").textContent =
    `${state.channelsTotal} channels · showing ${state.channelsOffset + 1}-${Math.min(state.channelsOffset + state.channelsLimit, state.channelsTotal)}`;

  try {
    renderChannels(result.channels || []);
    const channelsList = $("channels-list");
    if (channelsList) channelsList.scrollTop = 0;
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
        if (checkbox.checked) {
          if (!state.visibleSelectedIds.includes(channel.id)) state.visibleSelectedIds.push(channel.id);
        } else {
          state.visibleSelectedIds = state.visibleSelectedIds.filter((id) => id !== channel.id);
        }
        updateSelectShownCheckbox();
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

  if (tab === "epg" && !epgState.loaded) {
    loadEpgReview().catch((err) => {
      $("epg-job-status").textContent = `Could not load EPG review: ${err.message}`;
    });
  }

  if (["settings", "channels", "epg"].includes(tab)) {
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
}

async function init() {
  wireEvents();
  wireEpgEvents();

  const initialTab = window.location.hash.replace("#", "");
  if (["settings", "channels", "epg"].includes(initialTab)) {
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
  activeChannelId: null,
  pending: null,
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
  epgState.loaded = true;

  if (!epgState.activeChannelId && epgState.rows.length) {
    epgState.activeChannelId = epgState.rows[0].channel_id;
  }

  if (!epgState.rows.some((row) => row.channel_id === epgState.activeChannelId)) {
    epgState.activeChannelId = epgState.rows[0]?.channel_id || null;
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
  renderEpgChannelList();
  renderEpgDetail();
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
  const rows = epgState.rows.filter((row) => {
    const haystack = `${row.name} ${row.tvg_id} ${row.group_name} ${epgStatusFor(row)}`.toLowerCase();
    return !filter || haystack.includes(filter);
  });

  $("epg-channel-list").innerHTML = rows.map((row) => `
    <div class="epg-channel-card ${row.channel_id === epgState.activeChannelId ? "active" : ""}" data-channel-id="${escapeAttr(row.channel_id)}">
      <strong>${escapeHtml(row.name)}</strong>
      <div class="meta">${escapeHtml(row.group_name)} · ${escapeHtml(row.tvg_id)}</div>
      <div class="epg-badges">
        <span class="epg-status ${escapeAttr(epgStatusFor(row))}">${escapeHtml(epgStatusFor(row))}</span>
        ${row.recommended ? `<span class="epg-status">${escapeHtml(row.recommended.source_key)}</span>` : ""}
      </div>
    </div>
  `).join("");

  document.querySelectorAll(".epg-channel-card").forEach((el) => {
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

  renderEpgCurrent(row);
  renderEpgSuggestions(row);
  $("epg-manual-query").value = row.tvg_id || row.name || "";
  $("epg-manual-results").innerHTML = "";
  $("epg-save-state").textContent = "";
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

  if (!suggestions.length) {
    $("epg-suggestions").innerHTML = `<p>No suggestions. Use manual search.</p>`;
    return;
  }

  $("epg-suggestions").innerHTML = suggestions
    .map((opt, idx) => renderEpgOption(opt, idx === 0 ? "recommended" : "manual"))
    .join("");
  wireEpgOptions();
}

function renderEpgOption(opt, type) {
  const pending = epgState.pending;
  const selected = pending?.xmltv_id === opt.xmltv_id && pending?.source_key === opt.source_key;

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
      epgState.pending = {
        channel_id: row.channel_id,
        xmltv_id: el.dataset.xmltvId,
        source_key: el.dataset.sourceKey,
        mapping_type: el.dataset.type || "manual",
        confidence: Number(el.dataset.confidence || 1),
      };
      renderEpgDetail();
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

  $("epg-save-state").textContent = "Saved";
  await loadEpgReview();
}

async function manualEpgSearch() {
  const q = $("epg-manual-query").value.trim();
  $("epg-manual-results").innerHTML = `<p>Searching...</p>`;

  const body = await api(`/api/epgshare/search?q=${encodeURIComponent(q)}&limit=30`);
  $("epg-manual-results").innerHTML = (body.results || [])
    .map((result) => renderEpgOption({
      xmltv_id: result.xmltv_id,
      source_key: result.source_key,
      confidence: 1,
      reason: "manual search result",
    }, "manual"))
    .join("") || `<p>No results.</p>`;

  wireEpgOptions();
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
  $("epg-channel-filter").addEventListener("input", renderEpgChannelList);
  $("epg-save-current").addEventListener("click", () => saveCurrentEpgMapping().catch((err) => alert(err.message)));
  $("epg-ignore-current").addEventListener("click", () => ignoreCurrentEpgMapping().catch((err) => alert(err.message)));
  $("epg-manual-search").addEventListener("click", () => manualEpgSearch().catch((err) => alert(err.message)));
  $("epg-import-index").addEventListener("click", () => importEpgIndex().catch((err) => alert(err.message)));
  $("epg-generate").addEventListener("click", () => generateEpgFromMappings().catch((err) => alert(err.message)));
}

// Start the app after every tab module has been declared.
init().catch((err) => {
  console.error(err);
  const status = document.getElementById("header-status") || document.getElementById("epg-job-status");
  if (status) status.textContent = `Startup failed: ${err.message || err}`;
});
