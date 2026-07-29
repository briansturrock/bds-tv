var GUIDE_WINDOW_HOURS = 2;
var GUIDE_SHIFT_HOURS = 1;

var tvState = {
  groups: [],
  channels: [],
  activeGroupIndex: 0,
  focusedPane: "groups",
  focusBeforeDays: "groups",
  focusedGroupIndex: 0,
  focusedChannelIndex: 0,
  focusedProgrammeIndex: 0,
  focusedDayIndex: 0,
  windowStart: null,
  selectedDate: null,
  guideDates: [],
  visibleGuideDays: 4,
  loading: false,
  contextOpen: false,
  contextChannel: null,
  contextProgramme: null,
  exitConfirmOpen: false,
  exitConfirmYes: true
};

function $(id) {
  return document.getElementById(id);
}

function api(path, callback) {
  setStatus("Requesting " + path);

  var xhr = new XMLHttpRequest();
  var finished = false;
  var timer = setTimeout(function() {
    if (finished) return;
    finished = true;
    try {
      xhr.abort();
    } catch (_err) {
      // Ignore abort errors on older TV runtimes.
    }
    callback(new Error("Timed out loading " + path));
  }, 15000);

  xhr.onreadystatechange = function() {
    if (xhr.readyState !== 4 || finished) return;
    finished = true;
    clearTimeout(timer);

    var body = null;
    try {
      body = JSON.parse(xhr.responseText || "{}");
    } catch (err) {
      callback(new Error("Invalid JSON from " + path));
      return;
    }

    if (xhr.status < 200 || xhr.status >= 300) {
      callback(new Error((body && body.detail) || xhr.statusText || ("HTTP " + xhr.status)));
      return;
    }

    callback(null, body);
  };

  xhr.onerror = function() {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    callback(new Error("Network error loading " + path));
  };

  xhr.open("GET", path, true);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.send();
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, "&#039;");
}

function formatTime(value) {
  if (!value) return "";
  var date = new Date(value);
  if (isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function floorDateToHalfHour(date) {
  var copy = new Date(date);
  copy.setMinutes(copy.getMinutes() >= 30 ? 30 : 0, 0, 0);
  return copy;
}

function addHours(date, hours) {
  return new Date(date.getTime() + hours * 3600000);
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function todayDate() {
  return isoDate(new Date());
}

function earliestWindowStart() {
  var now = new Date();
  var today = todayDate();
  var selected = tvState.selectedDate || today;
  if (selected === today) {
    return floorDateToHalfHour(now);
  }

  var parts = selected.split("-");
  if (parts.length !== 3) return floorDateToHalfHour(now);
  return new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 0, 0, 0, 0));
}

function normaliseWindowStart(date) {
  var start = floorDateToHalfHour(date);
  var earliest = earliestWindowStart();
  return start < earliest ? earliest : start;
}

function currentWindowStart() {
  var current = tvState.windowStart ? new Date(tvState.windowStart) : null;
  if (current && !isNaN(current.getTime())) {
    return normaliseWindowStart(current);
  }
  return normaliseWindowStart(new Date());
}

function currentWindowEnd() {
  return addHours(currentWindowStart(), GUIDE_WINDOW_HOURS);
}

function dateWithPreservedClock(dateValue, current) {
  current = current || currentWindowStart();
  var parts = String(dateValue || "").split("-");
  if (parts.length !== 3) return currentWindowStart();
  return normaliseWindowStart(new Date(Date.UTC(
    Number(parts[0]),
    Number(parts[1]) - 1,
    Number(parts[2]),
    current.getUTCHours(),
    current.getUTCMinutes(),
    0,
    0
  )));
}

function setStatus(message) {
  $("tv-status").textContent = message;
}

function setLastKey(event, normalisedKey) {
  var el = $("tv-last-key");
  if (!el) return;
  var code = event.keyCode || event.which || 0;
  var name = normalisedKey || event.key || event.code || "";
  el.textContent = "Last key: " + code + (name ? " " + name : "");
}

function updateClock() {
  $("tv-clock").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit"
  });
}

function scrollFocusedIntoView(selector, containerId) {
  var focused = document.querySelector(selector);
  var container = containerId ? $(containerId) : null;
  if (!focused || !container) return;

  var itemRect = focused.getBoundingClientRect();
  var containerRect = container.getBoundingClientRect();

  if (itemRect.top < containerRect.top) {
    container.scrollTop -= containerRect.top - itemRect.top;
  } else if (itemRect.bottom > containerRect.bottom) {
    container.scrollTop += itemRect.bottom - containerRect.bottom;
  }
}

function renderGroups() {
  var groupsEl = $("tv-groups");
  var html = "";
  var i;

  if (!tvState.groups.length) {
    groupsEl.innerHTML = '<div class="tv-empty">No selected channel groups.</div>';
    return;
  }

  for (i = 0; i < tvState.groups.length; i += 1) {
    var group = tvState.groups[i];
    var className = "tv-group";
    if (i === tvState.activeGroupIndex) className += " active";
    if (tvState.focusedPane === "groups" && i === tvState.focusedGroupIndex) className += " focused";
    html += ''
      + '<div class="' + className + '" data-index="' + i + '">'
      + '<strong>' + escapeHtml(group.name) + '</strong>'
      + '<span class="tv-count">' + escapeHtml(group.selected_channel_count || 0) + '</span>'
      + '</div>';
  }

  groupsEl.innerHTML = html;
  scrollFocusedIntoView(".tv-group.focused", "tv-groups");
}

function renderDays() {
  var daysEl = $("tv-days");
  var html = "";
  var i;

  if (!daysEl) return;

  for (i = 0; i < tvState.guideDates.length; i += 1) {
    var item = tvState.guideDates[i];
    var className = "tv-day";
    if (item.date === tvState.selectedDate) className += " active";
    if (tvState.focusedPane === "days" && i === tvState.focusedDayIndex) className += " focused";
    html += '<button class="' + className + '" type="button" data-date="' + escapeAttr(item.date) + '">' + escapeHtml(item.label || item.date) + '</button>';
  }

  daysEl.innerHTML = html;
  Array.prototype.forEach.call(daysEl.querySelectorAll(".tv-day"), function(button, index) {
    button.addEventListener("click", function() {
      selectGuideDate(index);
    });
  });
}

function selectGuideDate(index) {
  if (!tvState.guideDates.length) return;

  var safeIndex = Math.max(0, Math.min(index, tvState.guideDates.length - 1));
  var selected = tvState.guideDates[safeIndex];
  var preservedClock = currentWindowStart();
  if (!selected) return;
  if (selected.date === tvState.selectedDate) {
    tvState.focusedDayIndex = safeIndex;
    renderDays();
    return;
  }

  tvState.focusedDayIndex = safeIndex;
  tvState.selectedDate = selected.date;
  tvState.windowStart = dateWithPreservedClock(selected.date, preservedClock).toISOString();
  tvState.focusedChannelIndex = 0;
  tvState.focusedProgrammeIndex = 0;
  renderDays();
  loadActiveGroup();
}

function focusDays(fromPane) {
  tvState.focusBeforeDays = fromPane || tvState.focusedPane || "groups";
  tvState.focusedPane = "days";
  renderDays();
  renderGroups();
  renderChannels();
}

function leaveDays() {
  var target = tvState.focusBeforeDays === "programmes" ? "programmes" : "groups";
  tvState.focusedPane = target;
  renderDays();
  if (target === "programmes") {
    renderChannels();
  } else {
    renderGroups();
  }
}

function programmeOverlaps(programme, windowStart, windowEnd) {
  var start = new Date(programme.start);
  var stop = new Date(programme.stop);
  if (isNaN(start.getTime()) || isNaN(stop.getTime())) return false;
  return stop > windowStart && start < windowEnd;
}

function visibleProgrammes(channel) {
  var windowStart = currentWindowStart();
  var windowEnd = currentWindowEnd();
  return (channel.programmes || []).filter(function(programme) {
    return programmeOverlaps(programme, windowStart, windowEnd);
  });
}

function programmeLeft(programme, windowStart) {
  var start = new Date(programme.start);
  var leftDate = start < windowStart ? windowStart : start;
  return ((leftDate.getTime() - windowStart.getTime()) / 3600000 / GUIDE_WINDOW_HOURS) * 100;
}

function programmeWidth(programme, windowStart, windowEnd) {
  var start = new Date(programme.start);
  var stop = new Date(programme.stop);
  var leftDate = start < windowStart ? windowStart : start;
  var rightDate = stop > windowEnd ? windowEnd : stop;
  return Math.max(12, ((rightDate.getTime() - leftDate.getTime()) / 3600000 / GUIDE_WINDOW_HOURS) * 100);
}

function programmeCard(programme, channel, index, windowStart, windowEnd) {
  if (!programme) {
    return ''
      + '<div class="tv-programme">'
      + '<strong>Unknown</strong>'
      + '<span>No programme data</span>'
      + '</div>';
  }

  var time = formatTime(programme.start) + " - " + formatTime(programme.stop);
  var className = "tv-programme";
  var left = programmeLeft(programme, windowStart);
  var width = programmeWidth(programme, windowStart, windowEnd);
  if (programme.is_now) className += " now";
  if (tvState.focusedPane === "programmes"
    && tvState.channels[tvState.focusedChannelIndex] === channel
    && tvState.focusedProgrammeIndex === index) {
    className += " focused";
  }
  return ''
    + '<div class="' + className + '" style="left:' + left + '%;width:calc(' + width + '% - 6px)">'
    + '<strong>' + escapeHtml(programme.title || "Unknown") + '</strong>'
    + '<span>' + escapeHtml(time) + (programme.is_now ? " · Now" : "") + '</span>'
    + '</div>';
}

function renderChannels() {
  var guideEl = $("tv-guide");
  var group = tvState.groups[tvState.activeGroupIndex];
  var html = "";
  var i;
  var windowStart = currentWindowStart();
  var windowEnd = currentWindowEnd();

  $("tv-group-title").textContent = (group && group.name) || "Guide";
  $("tv-group-meta").textContent = tvState.channels.length
    ? tvState.channels.length + " channels · " + formatTime(windowStart.toISOString()) + " - " + formatTime(windowEnd.toISOString())
    : "No channels in this group";

  if (!tvState.channels.length) {
    guideEl.innerHTML = '<div class="tv-empty">No selected channels.</div>';
    return;
  }

  html += ''
    + '<div class="tv-time-axis">'
    + '<span>' + escapeHtml(formatTime(windowStart.toISOString())) + '</span>'
    + '<span>' + escapeHtml(formatTime(addHours(windowStart, 0.5).toISOString())) + '</span>'
    + '<span>' + escapeHtml(formatTime(addHours(windowStart, 1).toISOString())) + '</span>'
    + '<span>' + escapeHtml(formatTime(addHours(windowStart, 1.5).toISOString())) + '</span>'
    + '<span>' + escapeHtml(formatTime(windowEnd.toISOString())) + '</span>'
    + '</div>';

  for (i = 0; i < tvState.channels.length; i += 1) {
    var channel = tvState.channels[i];
    var programmes = visibleProgrammes(channel);
    var logo;

    logo = channel.logo_url
      ? '<img class="tv-logo" src="' + escapeAttr(channel.logo_url) + '" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility=&quot;hidden&quot;" />'
      : '<div class="tv-logo-fallback">TV</div>';

    html += ''
      + '<div class="tv-channel" data-index="' + i + '">'
      + '<div>' + logo + '</div>'
      + '<div>'
      + '<div class="tv-channel-name">' + escapeHtml(channel.name) + '</div>'
      + '<div class="tv-channel-meta">' + escapeHtml(channel.tvg_id || channel.group_name || "") + '</div>'
      + '</div>'
      + '<div class="tv-programmes">'
      + (programmes.length
        ? programmes.map(function(programme, programmeIndex) {
            return programmeCard(programme, channel, programmeIndex, windowStart, windowEnd);
          }).join("")
        : '<div class="tv-programme tv-programme-empty"><strong>Unknown</strong><span>No programme data</span></div>')
      + '</div>'
      + '</div>';
  }

  guideEl.innerHTML = html;
  scrollFocusedIntoView(".tv-programme.focused", "tv-guide");
}

function loadGroups() {
  setStatus("Loading groups...");
  api("/api/guide/groups", function(err, body) {
    if (err) {
      setStatus("Groups failed: " + err.message);
      return;
    }

    tvState.groups = body.groups || [];
    setStatus("Loaded " + tvState.groups.length + " groups");
    tvState.activeGroupIndex = 0;
    tvState.focusedGroupIndex = 0;
    renderGroups();

    if (tvState.groups.length) {
      loadActiveGroup();
    } else {
      setStatus("No selected channels");
    }
  });
}

function loadTvOptions(callback) {
  api("/api/tv-app/settings", function(err, body) {
    if (!err && body && body.settings) {
      tvState.visibleGuideDays = Math.max(1, Math.min(7, Number(body.settings.visible_guide_days || 4)));
    }
    callback();
  });
}

function loadGuideDates(callback) {
  api("/api/guide/dates", function(err, body) {
    var today = todayDate();
    var dates = (!err && body && body.dates && body.dates.length)
      ? body.dates.slice(0, tvState.visibleGuideDays)
      : [{ date: today, label: "Today" }];
    var todayIndex;

    tvState.guideDates = dates;
    todayIndex = dates.map(function(item) { return item.date; }).indexOf(today);
    tvState.focusedDayIndex = todayIndex >= 0 ? todayIndex : 0;
    tvState.selectedDate = dates[tvState.focusedDayIndex] ? dates[tvState.focusedDayIndex].date : today;
    renderDays();
    callback();
  });
}

function startTvGuide() {
  loadTvOptions(function() {
    loadGuideDates(function() {
      loadGroups();
    });
  });
}

function loadActiveGroup() {
  if (tvState.loading) return;

  var group = tvState.groups[tvState.activeGroupIndex];
  if (!group) return;

  tvState.loading = true;
  setStatus("Loading " + group.name + "...");

  var start = currentWindowStart().toISOString();
  var path = "/api/guide?group_id=" + encodeURIComponent(group.id)
    + "&date=" + encodeURIComponent(tvState.selectedDate || todayDate())
    + "&start=" + encodeURIComponent(start)
    + "&hours=" + GUIDE_WINDOW_HOURS;

  api(path, function(err, body) {
    tvState.loading = false;
    if (err) {
      setStatus("Guide failed: " + err.message);
      return;
    }

    tvState.channels = body.channels || [];
    tvState.focusedChannelIndex = Math.min(tvState.focusedChannelIndex, Math.max(0, tvState.channels.length - 1));
    clampProgrammeFocus();
    tvState.windowStart = body.window_start;
    renderGroups();
    renderChannels();
    setStatus("Ready");
  });
}

function clampProgrammeFocus() {
  var channel = tvState.channels[tvState.focusedChannelIndex];
  var count = channel ? visibleProgrammes(channel).length : 0;
  tvState.focusedProgrammeIndex = Math.max(0, Math.min(tvState.focusedProgrammeIndex, Math.max(0, count - 1)));
}

function moveFocus(delta) {
  if (tvState.focusedPane === "groups") {
    if (delta < 0 && tvState.focusedGroupIndex === 0 && tvState.guideDates.length) {
      focusDays("groups");
      return;
    }
    tvState.focusedGroupIndex = Math.max(0, Math.min(tvState.groups.length - 1, tvState.focusedGroupIndex + delta));
    renderGroups();
    return;
  }

  if (delta < 0 && tvState.focusedChannelIndex === 0 && tvState.guideDates.length) {
    focusDays("programmes");
    return;
  }

  tvState.focusedChannelIndex = Math.max(0, Math.min(tvState.channels.length - 1, tvState.focusedChannelIndex + delta));
  clampProgrammeFocus();
  renderChannels();
}

function shiftGuideWindow(deltaHours) {
  var current = currentWindowStart();
  var next = normaliseWindowStart(addHours(current, deltaHours));
  if (next.getTime() === current.getTime()) {
    setStatus("Start of guide reached.");
    return false;
  }
  tvState.windowStart = next.toISOString();
  loadActiveGroup();
  return true;
}

function moveProgramme(delta) {
  var channel = tvState.channels[tvState.focusedChannelIndex];
  var programmes = channel ? visibleProgrammes(channel) : [];
  var nextIndex = tvState.focusedProgrammeIndex + delta;

  if (delta > 0 && nextIndex >= programmes.length) {
    shiftGuideWindow(GUIDE_SHIFT_HOURS);
    return;
  }

  if (delta < 0 && nextIndex < 0) {
    if (!shiftGuideWindow(-GUIDE_SHIFT_HOURS)) {
      tvState.focusedPane = "groups";
      renderGroups();
      renderChannels();
    }
    return;
  }

  tvState.focusedProgrammeIndex = Math.max(0, Math.min(nextIndex, Math.max(0, programmes.length - 1)));
  renderChannels();
}

function activateFocused() {
  if (tvState.exitConfirmOpen) {
    confirmExitChoice();
    return;
  }

  if (tvState.focusedPane === "groups") {
    tvState.activeGroupIndex = tvState.focusedGroupIndex;
    tvState.focusedChannelIndex = 0;
    tvState.focusedProgrammeIndex = 0;
    tvState.windowStart = null;
    tvState.selectedDate = todayDate();
    tvState.focusedDayIndex = Math.max(0, tvState.guideDates.map(function(item) { return item.date; }).indexOf(tvState.selectedDate));
    renderDays();
    loadActiveGroup();
    return;
  }

  var channel = tvState.channels[tvState.focusedChannelIndex];
  var programme = focusedProgramme();
  if (channel && programme) {
    showContextMenu(channel, programme);
  } else if (programme) {
    setStatus("No channel selected.");
  } else {
    setStatus("No programme selected.");
  }
}

function focusedProgramme() {
  var channel = tvState.channels[tvState.focusedChannelIndex];
  var programmes = channel ? visibleProgrammes(channel) : [];
  return programmes[tvState.focusedProgrammeIndex] || null;
}

function showContextMenu(channel, programme) {
  var shell = $("tv-context-shell");
  tvState.contextOpen = true;
  tvState.contextChannel = channel;
  tvState.contextProgramme = programme;
  $("tv-context-title").textContent = programme.title || "Programme";
  $("tv-context-subtitle").textContent = channel.name || "Channel";
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  setStatus("Programme actions open.");
}

function hideContextMenu() {
  var shell = $("tv-context-shell");
  tvState.contextOpen = false;
  shell.classList.add("hidden");
  shell.style.display = "none";
  shell.setAttribute("aria-hidden", "true");
}

function startContextStream() {
  var channel = tvState.contextChannel;
  if (!channel) {
    hideContextMenu();
    setStatus("No channel selected.");
    return;
  }
  hideContextMenu();
  playChannel(channel);
}

function playChannel(channel) {
  var playerShell = $("tv-player-shell");
  var player = $("tv-player");
  $("tv-player-title").textContent = channel.name || "Channel";
  playerShell.classList.remove("hidden");
  playerShell.style.display = "block";
  player.src = "/tv/stream/" + encodeURIComponent(channel.channel_id) + ".mpg";

  try {
    var playPromise = player.play();
    if (playPromise && playPromise.catch) {
      playPromise.catch(function(err) {
        setStatus("Playback failed: " + err.message);
      });
    }
  } catch (err) {
    setStatus("Playback failed: " + err.message);
  }
}

function stopPlayback() {
  var playerShell = $("tv-player-shell");
  var player = $("tv-player");
  player.pause();
  player.removeAttribute("src");
  player.load();
  playerShell.classList.add("hidden");
  playerShell.style.display = "none";
}

function playerOpen() {
  var player = $("tv-player");
  return !!(player && (player.currentSrc || player.getAttribute("src")));
}

function renderExitConfirm() {
  $("tv-exit-yes").className = "tv-exit-choice" + (tvState.exitConfirmYes ? " focused" : "");
  $("tv-exit-no").className = "tv-exit-choice" + (!tvState.exitConfirmYes ? " focused" : "");
}

function showExitConfirm() {
  var shell = $("tv-exit-shell");
  tvState.exitConfirmOpen = true;
  tvState.exitConfirmYes = true;
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  renderExitConfirm();
  setStatus("Back pressed. Close confirmation open.");
  try {
    $("tv-exit-yes").focus();
  } catch (_err) {
    // Older TV runtimes may not expose focus on button elements.
  }
}

function hideExitConfirm() {
  var shell = $("tv-exit-shell");
  tvState.exitConfirmOpen = false;
  shell.classList.add("hidden");
  shell.style.display = "none";
  shell.setAttribute("aria-hidden", "true");
}

function exitApp() {
  setStatus("Closing bds-tv...");

  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: "bds-tv-exit" }, "*");
      return;
    }
  } catch (_err) {
    // Continue to native/browser fallbacks below.
  }

  try {
    if (window.tizen && tizen.application && tizen.application.getCurrentApplication) {
      tizen.application.getCurrentApplication().exit();
      return;
    }
  } catch (err) {
    setStatus("Close failed: " + err.message);
  }

  try {
    window.close();
  } catch (_err) {
    // Ignore; some TV runtimes block window.close().
  }

  hideExitConfirm();
  setStatus("Use Home to leave bds-tv.");
}

function confirmExitChoice() {
  if (tvState.exitConfirmYes) {
    exitApp();
  } else {
    hideExitConfirm();
  }
}

function handleBack() {
  if (playerOpen()) {
    stopPlayback();
    setStatus("Back pressed. Playback stopped.");
    return;
  }

  if (tvState.exitConfirmOpen) {
    hideExitConfirm();
    setStatus("Close cancelled.");
    return;
  }

  if (tvState.contextOpen) {
    hideContextMenu();
    setStatus("Programme actions closed.");
    return;
  }

  if (tvState.focusedPane === "programmes") {
    tvState.focusedPane = "groups";
    tvState.focusedGroupIndex = tvState.activeGroupIndex;
    renderGroups();
    renderChannels();
    setStatus("Group list focused.");
    return;
  }

  if (tvState.focusedPane === "days") {
    leaveDays();
    setStatus(tvState.focusedPane === "programmes" ? "Guide focused." : "Group list focused.");
    return;
  }

  showExitConfirm();
}

function handleKey(event) {
  if (event.__bdsTvHandled) return;
  event.__bdsTvHandled = true;

  var key = event.key || event.code;
  var code = event.keyCode || event.which || 0;
  var normalisedKey = ({
    13: "Enter",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    461: "Backspace",
    10009: "Backspace"
  })[code] || key;

  if (normalisedKey === "Back" || normalisedKey === "XF86Back") {
    normalisedKey = "Backspace";
  }

  setLastKey(event, normalisedKey);

  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Backspace", "Escape", "BrowserBack", "GoBack"].indexOf(normalisedKey) >= 0) {
    event.preventDefault();
  }

  if (normalisedKey === "Backspace" || normalisedKey === "Escape" || normalisedKey === "BrowserBack" || normalisedKey === "GoBack") {
    handleBack();
    return;
  }

  if (tvState.exitConfirmOpen) {
    if (normalisedKey === "ArrowLeft" || normalisedKey === "ArrowRight") {
      tvState.exitConfirmYes = !tvState.exitConfirmYes;
      renderExitConfirm();
    }
    if (normalisedKey === "Enter") {
      confirmExitChoice();
    }
    return;
  }

  if (tvState.contextOpen) {
    if (normalisedKey === "Enter") {
      startContextStream();
    }
    return;
  }

  if (normalisedKey === "ArrowUp") moveFocus(-1);
  if (normalisedKey === "ArrowDown") {
    if (tvState.focusedPane === "days") {
      leaveDays();
    } else {
      moveFocus(1);
    }
  }
  if (normalisedKey === "ArrowRight") {
    if (tvState.focusedPane === "days") {
      selectGuideDate(tvState.focusedDayIndex + 1);
    } else if (tvState.focusedPane === "groups") {
      tvState.focusedPane = "programmes";
      clampProgrammeFocus();
      renderGroups();
      renderChannels();
    } else {
      moveProgramme(1);
    }
  }
  if (normalisedKey === "ArrowLeft") {
    if (tvState.focusedPane === "days") {
      selectGuideDate(tvState.focusedDayIndex - 1);
    } else if (tvState.focusedPane === "programmes") {
      moveProgramme(-1);
    }
  }
  if (normalisedKey === "Enter") {
    activateFocused();
  }
}

function handleShellMessage(event) {
  var data = event.data || {};
  if (data && data.type === "bds-tv-back") {
    handleBack();
  }
}

document.addEventListener("keydown", handleKey, true);
window.addEventListener("keydown", handleKey, true);
$("tv-exit-yes").addEventListener("click", exitApp);
$("tv-exit-no").addEventListener("click", hideExitConfirm);
$("tv-context-start").addEventListener("click", startContextStream);
window.addEventListener("message", handleShellMessage);
setInterval(updateClock, 15000);
updateClock();
setStatus("TV script loaded");
startTvGuide();
