const state = {
  review: null,
  selected: {},
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function key(row) {
  return row.channel_id;
}

async function loadReview() {
  const res = await fetch("/api/epgshare/mapping-review");
  const body = await res.json();
  if (!res.ok || !body.ok) throw new Error(JSON.stringify(body));
  state.review = body;
  seedSelections();
  render();
}

function seedSelections() {
  state.selected = {};
  for (const row of state.review.rows) {
    if (row.saved_mapping) {
      if (row.saved_mapping.ignored) {
        state.selected[key(row)] = { channel_id: row.channel_id, ignored: true, mapping_type: "ignored" };
      } else {
        state.selected[key(row)] = {
          channel_id: row.channel_id,
          xmltv_id: row.saved_mapping.xmltv_id,
          source_key: row.saved_mapping.source_key,
          mapping_type: row.saved_mapping.mapping_type || "manual",
          confidence: row.saved_mapping.confidence,
        };
      }
    } else if (row.recommended) {
      state.selected[key(row)] = {
        channel_id: row.channel_id,
        xmltv_id: row.recommended.xmltv_id,
        source_key: row.recommended.source_key,
        mapping_type: row.status === "exact" ? "exact" : "suggested",
        confidence: row.recommended.confidence ?? 1.0,
      };
    }
  }
}

function render() {
  renderSummary();
  renderSources();
  renderRows();
}

function renderSummary() {
  const s = state.review.summary;
  $("summary").innerHTML = `
    <span class="pill">Selected: <strong>${s.selected_channel_count}</strong></span>
    <span class="pill">Exact: <strong>${s.exact_match_count}</strong></span>
    <span class="pill">Suggested: <strong>${s.suggested_match_count}</strong></span>
    <span class="pill">Unmatched: <strong>${s.unmatched_count}</strong></span>
    <span class="pill">Saved: <strong>${s.saved_mapping_count}</strong></span>
    <span class="pill">Required XML files: <strong>${s.required_source_count}</strong></span>
  `;
}

function renderSources() {
  $("sources").innerHTML = state.review.required_sources.map(src => `
    <span class="pill">${esc(src.source_key)} · ${src.matched_channel_count}</span>
  `).join("");
}

function renderRows() {
  $("rows").innerHTML = state.review.rows.map(renderRow).join("");
  wireRows();
}

function renderRow(row) {
  const options = [
    ...row.suggestions.map(opt => renderOption(row, opt)),
    renderIgnoreOption(row)
  ].join("");

  return `
    <article class="row" data-channel-id="${esc(row.channel_id)}">
      <div class="row-header">
        <div class="channel">
          <strong>${esc(row.name)}</strong>
          <div><code>${esc(row.tvg_id)}</code> · ${esc(row.group_name)}</div>
        </div>
        <span class="status ${esc(row.status)}">${esc(row.status)}</span>
      </div>
      <div class="options">${options || "<p>No suggestions.</p>"}</div>
      <div class="search">
        <input class="search-box" placeholder="Manual search EPGShare index..." value="${esc(row.tvg_id || row.name || "")}" />
        <button class="search-button">Search</button>
        <div class="search-results"></div>
      </div>
    </article>
  `;
}

function renderOption(row, opt) {
  const current = state.selected[key(row)] || {};
  const checked = current.xmltv_id === opt.xmltv_id && current.source_key === opt.source_key;
  return `
    <label class="option">
      <input type="radio" name="map-${esc(row.channel_id)}" data-kind="map"
        data-xmltv-id="${esc(opt.xmltv_id)}"
        data-source-key="${esc(opt.source_key)}"
        data-confidence="${esc(opt.confidence ?? 1)}"
        ${checked ? "checked" : ""} />
      <span>
        <strong>${esc(opt.xmltv_id)}</strong>
        <div class="meta">${esc(opt.source_key)} · confidence ${esc(opt.confidence ?? "exact")} · ${esc(opt.reason || "exact")}</div>
      </span>
    </label>
  `;
}

function renderIgnoreOption(row) {
  const current = state.selected[key(row)] || {};
  return `
    <label class="option">
      <input type="radio" name="map-${esc(row.channel_id)}" data-kind="ignore" ${current.ignored ? "checked" : ""} />
      <span>
        <strong>No EPG / ignore this channel</strong>
        <div class="meta">This channel will not be included in generated EPG mappings.</div>
      </span>
    </label>
  `;
}

function wireRows() {
  for (const rowEl of document.querySelectorAll(".row")) {
    const channelId = rowEl.dataset.channelId;
    for (const radio of rowEl.querySelectorAll("input[type=radio]")) {
      radio.addEventListener("change", () => {
        if (radio.dataset.kind === "ignore") {
          state.selected[channelId] = { channel_id: channelId, ignored: true, mapping_type: "ignored" };
        } else {
          state.selected[channelId] = {
            channel_id: channelId,
            xmltv_id: radio.dataset.xmltvId,
            source_key: radio.dataset.sourceKey,
            mapping_type: "manual",
            confidence: Number(radio.dataset.confidence || 1),
          };
        }
      });
    }

    rowEl.querySelector(".search-button").addEventListener("click", async () => {
      const q = rowEl.querySelector(".search-box").value;
      const resultsEl = rowEl.querySelector(".search-results");
      resultsEl.innerHTML = "Searching...";
      const res = await fetch(`/api/epgshare/search?q=${encodeURIComponent(q)}&limit=25`);
      const body = await res.json();
      resultsEl.innerHTML = (body.results || []).map(result => `
        <label class="option">
          <input type="radio" name="map-${esc(channelId)}" data-kind="map"
            data-xmltv-id="${esc(result.xmltv_id)}"
            data-source-key="${esc(result.source_key)}"
            data-confidence="1" />
          <span>
            <strong>${esc(result.xmltv_id)}</strong>
            <div class="meta">${esc(result.source_key)}</div>
          </span>
        </label>
      `).join("") || "No results.";
      wireRows();
    });
  }
}

async function saveMappings() {
  const mappings = Object.values(state.selected);
  const res = await fetch("/api/epgshare/mappings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ mappings }),
  });
  const body = await res.json();
  if (!res.ok || !body.ok) {
    alert(`Save failed: ${JSON.stringify(body)}`);
    return;
  }
  alert(`Saved ${body.saved}, ignored ${body.ignored}`);
  await loadReview();
}

function exportReview() {
  const data = {
    exported_at: new Date().toISOString(),
    review: state.review,
    selected: Object.values(state.selected),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `epgshare-mapping-review-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

$("refresh").addEventListener("click", loadReview);
$("save").addEventListener("click", saveMappings);
$("export").addEventListener("click", exportReview);

loadReview().catch(err => {
  $("rows").innerHTML = `<pre>${esc(err.message || err)}</pre>`;
});
