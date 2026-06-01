const state = {
  review: null,
  rows: [],
  activeChannelId: null,
  pending: null,
  jobsTimer: null,
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function statusFor(row) {
  if (row.saved_mapping?.ignored) return "ignored";
  if (row.saved_mapping) return "saved";
  return row.status || "unmatched";
}

function mappingFromSaved(row) {
  if (!row.saved_mapping || row.saved_mapping.ignored) return null;
  return {
    channel_id: row.channel_id,
    xmltv_id: row.saved_mapping.xmltv_id,
    source_key: row.saved_mapping.source_key,
    mapping_type: row.saved_mapping.mapping_type || "manual",
    confidence: row.saved_mapping.confidence ?? null,
  };
}

function mappingFromOption(row, opt, mappingType = "manual") {
  return {
    channel_id: row.channel_id,
    xmltv_id: opt.xmltv_id,
    source_key: opt.source_key,
    mapping_type: mappingType,
    confidence: opt.confidence ?? 1,
  };
}

async function refreshAll() {
  await loadReview();
  await loadJobs();
}

async function loadReview() {
  const res = await fetch("/api/epgshare/mapping-review");
  const body = await res.json();
  if (!res.ok || !body.ok) throw new Error(JSON.stringify(body));
  state.review = body;
  state.rows = body.rows || [];

  if (!state.activeChannelId && state.rows.length) {
    state.activeChannelId = state.rows[0].channel_id;
  }

  if (!state.rows.some(r => r.channel_id === state.activeChannelId)) {
    state.activeChannelId = state.rows[0]?.channel_id || null;
  }

  state.pending = null;
  render();
}

function render() {
  renderSummary();
  renderChannelList();
  renderDetail();
}

function renderSummary() {
  const s = state.review.summary;
  $("summary").innerHTML = `
    <span class="pill">Selected <strong>${s.selected_channel_count}</strong></span>
    <span class="pill">Exact <strong>${s.exact_match_count}</strong></span>
    <span class="pill">Suggested <strong>${s.suggested_match_count}</strong></span>
    <span class="pill">Unmatched <strong>${s.unmatched_count}</strong></span>
    <span class="pill">Saved <strong>${s.saved_mapping_count}</strong></span>
    <span class="pill">Required XML <strong>${s.required_source_count}</strong></span>
  `;
}

function renderChannelList() {
  const filter = $("channel-filter").value.trim().toLowerCase();
  const rows = state.rows.filter(row => {
    const haystack = `${row.name} ${row.tvg_id} ${row.group_name} ${statusFor(row)}`.toLowerCase();
    return !filter || haystack.includes(filter);
  });

  $("channel-list").innerHTML = rows.map(row => `
    <div class="channel-card ${row.channel_id === state.activeChannelId ? "active" : ""}" data-channel-id="${esc(row.channel_id)}">
      <strong>${esc(row.name)}</strong>
      <div class="meta">${esc(row.group_name)} · ${esc(row.tvg_id)}</div>
      <div class="badges">
        <span class="status ${esc(statusFor(row))}">${esc(statusFor(row))}</span>
        ${row.recommended ? `<span class="status">${esc(row.recommended.source_key)}</span>` : ""}
      </div>
    </div>
  `).join("");

  for (const el of document.querySelectorAll(".channel-card")) {
    el.addEventListener("click", () => {
      state.activeChannelId = el.dataset.channelId;
      state.pending = null;
      render();
    });
  }
}

function activeRow() {
  return state.rows.find(row => row.channel_id === state.activeChannelId) || null;
}

function renderDetail() {
  const row = activeRow();
  if (!row) {
    $("detail").classList.add("hidden");
    $("detail-empty").classList.remove("hidden");
    return;
  }

  $("detail-empty").classList.add("hidden");
  $("detail").classList.remove("hidden");

  $("detail-title").textContent = row.name || "";
  $("detail-meta").textContent = `${row.group_name || ""} · tvg-id: ${row.tvg_id || ""}`;
  $("detail-status").textContent = statusFor(row);
  $("detail-status").className = `status ${statusFor(row)}`;

  renderCurrent(row);
  renderSuggestions(row);
  $("manual-query").value = row.tvg_id || row.name || "";
  $("manual-results").innerHTML = "";
  $("save-state").textContent = "";
}

function renderCurrent(row) {
  const saved = row.saved_mapping;
  if (!saved) {
    $("current-mapping").innerHTML = `<p>No saved mapping yet.</p>`;
    return;
  }

  if (saved.ignored) {
    $("current-mapping").innerHTML = `<div class="option selected"><strong>No EPG / ignored</strong><div class="meta">Saved ${esc(saved.updated_at)}</div></div>`;
    return;
  }

  $("current-mapping").innerHTML = `
    <div class="option selected">
      <strong>${esc(saved.xmltv_id)}</strong>
      <div class="meta">${esc(saved.source_key)} · ${esc(saved.mapping_type)} · saved ${esc(saved.updated_at)}</div>
    </div>
  `;
}

function renderSuggestions(row) {
  const suggestions = row.suggestions || [];

  if (!suggestions.length) {
    $("suggestions").innerHTML = `<p>No suggestions. Use manual search.</p>`;
    return;
  }

  $("suggestions").innerHTML = suggestions.map((opt, idx) => renderOption(row, opt, idx === 0 ? "recommended" : "manual")).join("");
  wireOptions();
}

function renderOption(row, opt, type) {
  const pending = state.pending;
  const selected =
    pending?.xmltv_id === opt.xmltv_id &&
    pending?.source_key === opt.source_key;

  return `
    <div class="option ${selected ? "selected" : ""}"
      data-xmltv-id="${esc(opt.xmltv_id)}"
      data-source-key="${esc(opt.source_key)}"
      data-confidence="${esc(opt.confidence ?? 1)}"
      data-type="${esc(type)}">
      <strong>${esc(opt.xmltv_id)}</strong>
      <div class="meta">${esc(opt.source_key)} · confidence ${esc(opt.confidence ?? "exact")}</div>
      <div class="reason">${esc(opt.reason || "exact/manual")} ${opt.country_match ? "· country match" : ""}</div>
    </div>
  `;
}

function wireOptions() {
  for (const el of document.querySelectorAll("#suggestions .option, #manual-results .option")) {
    el.addEventListener("click", () => {
      const row = activeRow();
      state.pending = {
        channel_id: row.channel_id,
        xmltv_id: el.dataset.xmltvId,
        source_key: el.dataset.sourceKey,
        mapping_type: el.dataset.type || "manual",
        confidence: Number(el.dataset.confidence || 1),
      };
      renderDetail();
      $("save-state").textContent = "Unsaved selection";
    });
  }
}

async function saveCurrent() {
  const row = activeRow();
  const mapping = state.pending || mappingFromSaved(row) || (row.recommended ? mappingFromOption(row, row.recommended, row.status === "exact" ? "exact" : "suggested") : null);

  if (!mapping) {
    alert("Choose a mapping first.");
    return;
  }

  await saveMappings([mapping]);
}

async function ignoreCurrent() {
  const row = activeRow();
  await saveMappings([{ channel_id: row.channel_id, ignored: true, mapping_type: "ignored" }]);
}

async function saveMappings(mappings) {
  $("save-state").textContent = "Saving...";
  const res = await fetch("/api/epgshare/mappings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ mappings }),
  });
  const body = await res.json();

  if (!res.ok || !body.ok) {
    $("save-state").textContent = "Save failed";
    alert(JSON.stringify(body));
    return;
  }

  $("save-state").textContent = "Saved";
  await loadReview();
}

async function manualSearch() {
  const q = $("manual-query").value.trim();
  const resultsEl = $("manual-results");
  resultsEl.innerHTML = `<p>Searching...</p>`;

  const res = await fetch(`/api/epgshare/search?q=${encodeURIComponent(q)}&limit=30`);
  const body = await res.json();

  const row = activeRow();
  resultsEl.innerHTML = (body.results || []).map(result => renderOption(row, {
    xmltv_id: result.xmltv_id,
    source_key: result.source_key,
    confidence: 1,
    reason: "manual search result",
  }, "manual")).join("") || `<p>No results.</p>`;

  wireOptions();
}

async function importIndex() {
  const ok = confirm("Start EPGShare index import/update?");
  if (!ok) return;
  const res = await fetch("/api/epgshare/index", { method: "POST" });
  const body = await res.json();
  if (!res.ok || !body.ok) {
    alert(JSON.stringify(body));
    return;
  }
  alert(`Index job started: ${body.job_id}`);
  await loadJobs();
}

async function generateEpg() {
  const ok = confirm("Generate filtered_epg.xml from saved mappings only?");
  if (!ok) return;
  const res = await fetch("/api/epgshare/generate-filtered?days=3", { method: "POST" });
  const body = await res.json();
  if (!res.ok || !body.ok) {
    alert(JSON.stringify(body));
    return;
  }
  alert(`Generation job started: ${body.job_id}`);
  await loadJobs();
}

async function loadJobs() {
  try {
    const res = await fetch("/api/jobs");
    const body = await res.json();
    const jobs = (body.jobs || []).filter(job =>
      String(job.job_type || "").startsWith("epgshare")
    );

    const latest = jobs[0];
    $("job-status").innerHTML = latest
      ? `Latest EPGShare job: <strong>${esc(latest.status)}</strong> — ${esc(latest.message || latest.job_type || "")}`
      : "No EPGShare jobs yet.";
  } catch (err) {
    $("job-status").textContent = `Could not load jobs: ${err.message || err}`;
  }
}

$("refresh").addEventListener("click", refreshAll);
$("channel-filter").addEventListener("input", renderChannelList);
$("save-current").addEventListener("click", saveCurrent);
$("ignore-current").addEventListener("click", ignoreCurrent);
$("manual-search").addEventListener("click", manualSearch);
$("import-index").addEventListener("click", importIndex);
$("generate-epg").addEventListener("click", generateEpg);

refreshAll().catch(err => {
  $("job-status").textContent = err.message || String(err);
});

state.jobsTimer = setInterval(loadJobs, 8000);
