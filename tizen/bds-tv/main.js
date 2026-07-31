var TV_SHELL_VERSION = "1.1.0";
var DEFAULT_SERVER = "http://192.168.0.185:8088";
var SERVER_KEY = "bdsTvServerUrl";
var GUIDE_WINDOW_HOURS = 2.5;
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
  contextChoiceIndex: 0,
  sonarrOpen: false,
  sonarrMode: "results",
  sonarrResults: [],
  sonarrFocusedIndex: 0,
  sonarrPrepared: null,
  sonarrActionIndex: 0,
  playbackOpen: false,
  playbackMode: "",
  exitConfirmOpen: false,
  exitConfirmYes: true,
  infoScrollTimer: null,
  infoScrollInterval: null,
  channelNameScrollTimer: null,
  channelNameScrollInterval: null
};

function $(id) {
  return document.getElementById(id);
}

function serverBaseUrl() {
  return (localStorage.getItem(SERVER_KEY) || DEFAULT_SERVER).replace(/\/$/, "");
}

function api(path, callback) {
  setStatus("Requesting " + path);

  var xhr = new XMLHttpRequest();
  var url = serverBaseUrl() + path;
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

  xhr.open("GET", url, true);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.send();
}

function apiPost(path, payload, callback) {
  setStatus("Sending " + path);

  var xhr = new XMLHttpRequest();
  var url = serverBaseUrl() + path;
  var finished = false;
  var timer = setTimeout(function() {
    if (finished) return;
    finished = true;
    try {
      xhr.abort();
    } catch (_err) {
      // Ignore abort errors on older TV runtimes.
    }
    callback(new Error("Timed out sending " + path));
  }, 20000);

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
    callback(new Error("Network error sending " + path));
  };

  xhr.open("POST", url, true);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.send(JSON.stringify(payload || {}));
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

function setShellVersion() {
  var el = $("tv-shell-version");
  if (el) el.textContent = "v" + TV_SHELL_VERSION;
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
  var topBoundary = containerRect.top;
  var stickyAxis = containerId === "tv-guide" ? container.querySelector(".tv-time-axis") : null;
  if (stickyAxis) {
    topBoundary += stickyAxis.getBoundingClientRect().height + 8;
  }

  if (itemRect.top < topBoundary) {
    container.scrollTop -= topBoundary - itemRect.top;
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

function clearProgrammeInfoScroll() {
  if (tvState.infoScrollTimer) {
    clearTimeout(tvState.infoScrollTimer);
    tvState.infoScrollTimer = null;
  }
  if (tvState.infoScrollInterval) {
    clearInterval(tvState.infoScrollInterval);
    tvState.infoScrollInterval = null;
  }
}

function scheduleProgrammeInfoScroll() {
  var descEl = document.querySelector(".tv-programme-info-desc");

  clearProgrammeInfoScroll();
  if (!descEl) return;

  tvState.infoScrollTimer = setTimeout(function() {
    var maxScroll = descEl.scrollHeight - descEl.clientHeight;
    if (maxScroll <= 2) return;

    function scrollDown() {
      descEl.scrollTop = 0;
      tvState.infoScrollInterval = setInterval(function() {
        descEl.scrollTop += 1;
        if (descEl.scrollTop >= maxScroll) {
          clearInterval(tvState.infoScrollInterval);
          tvState.infoScrollInterval = null;
          tvState.infoScrollTimer = setTimeout(function() {
            descEl.scrollTop = 0;
            tvState.infoScrollTimer = setTimeout(scrollDown, 2500);
          }, 2000);
        }
      }, 90);
    }

    scrollDown();
  }, 3000);
}

function clearChannelNameScroll() {
  if (tvState.channelNameScrollTimer) {
    clearTimeout(tvState.channelNameScrollTimer);
    tvState.channelNameScrollTimer = null;
  }
  if (tvState.channelNameScrollInterval) {
    clearInterval(tvState.channelNameScrollInterval);
    tvState.channelNameScrollInterval = null;
  }
}

function scheduleChannelNameScroll() {
  var nameEl = document.querySelector(".tv-channel-name.focused-title span");

  clearChannelNameScroll();
  if (!nameEl || !nameEl.parentNode) return;

  nameEl.style.transform = "translateX(0px)";
  tvState.channelNameScrollTimer = setTimeout(function() {
    var parent = nameEl.parentNode;
    var maxScroll = parent ? nameEl.scrollWidth - parent.clientWidth : 0;
    if (maxScroll <= 2) return;

    function scrollLeft() {
      var offset = 0;
      nameEl.style.transform = "translateX(0px)";
      tvState.channelNameScrollInterval = setInterval(function() {
        offset += 1;
        nameEl.style.transform = "translateX(-" + offset + "px)";
        if (offset >= maxScroll) {
          clearInterval(tvState.channelNameScrollInterval);
          tvState.channelNameScrollInterval = null;
          tvState.channelNameScrollTimer = setTimeout(function() {
            nameEl.style.transform = "translateX(0px)";
            tvState.channelNameScrollTimer = setTimeout(scrollLeft, 1000);
          }, 1000);
        }
      }, 30);
    }

    scrollLeft();
  }, 1000);
}

function renderProgrammeInfo() {
  var infoEl = $("tv-programme-info");
  var channel = tvState.channels[tvState.focusedChannelIndex];
  var programme = tvState.focusedPane === "programmes" ? focusedProgramme() : null;
  var meta = [];
  var desc;
  var image = "";

  if (!infoEl) return;
  clearProgrammeInfoScroll();

  if (!channel || !programme) {
    infoEl.innerHTML = '<div class="tv-programme-info-empty">Select a programme for details.</div>';
    return;
  }

  if (programme.start || programme.stop) {
    meta.push(formatTime(programme.start) + " - " + formatTime(programme.stop));
  }
  if (programme.category) meta.push(programme.category);
  if (channel.name) meta.push(channel.name);

  desc = programme.desc || "No programme information available.";
  if (programme.icon) {
    image = '<img class="tv-programme-info-image" src="' + escapeAttr(programme.icon) + '" alt="" referrerpolicy="no-referrer" onerror="this.style.display=&quot;none&quot;" />';
  }

  infoEl.innerHTML = ''
    + image
    + '<div class="tv-programme-info-copy">'
    + '<div class="tv-programme-info-title">' + escapeHtml(programme.title || "Unknown") + '</div>'
    + '<div class="tv-programme-info-meta">' + escapeHtml(meta.join(" · ")) + '</div>'
    + '<div class="tv-programme-info-desc">' + escapeHtml(desc) + '</div>'
    + '</div>';
  scheduleProgrammeInfoScroll();
}

function renderChannels() {
  var guideEl = $("tv-guide");
  var axisEl = $("tv-time-axis");
  var group = tvState.groups[tvState.activeGroupIndex];
  var html = "";
  var i;
  var windowStart = currentWindowStart();
  var windowEnd = currentWindowEnd();

  clearChannelNameScroll();
  $("tv-group-title").textContent = (group && group.name) || "Guide";
  $("tv-group-meta").textContent = tvState.channels.length
    ? tvState.channels.length + " channels · " + formatTime(windowStart.toISOString()) + " - " + formatTime(windowEnd.toISOString())
    : "No channels in this group";

  if (!tvState.channels.length) {
    if (axisEl) axisEl.innerHTML = "";
    guideEl.innerHTML = '<div class="tv-empty">No selected channels.</div>';
    renderProgrammeInfo();
    return;
  }

  if (axisEl) {
    axisEl.innerHTML = ''
    + '<span style="left:0%">' + escapeHtml(formatTime(windowStart.toISOString())) + '</span>'
    + '<span style="left:20%">' + escapeHtml(formatTime(addHours(windowStart, 0.5).toISOString())) + '</span>'
    + '<span style="left:40%">' + escapeHtml(formatTime(addHours(windowStart, 1).toISOString())) + '</span>'
    + '<span style="left:60%">' + escapeHtml(formatTime(addHours(windowStart, 1.5).toISOString())) + '</span>'
    + '<span style="left:80%">' + escapeHtml(formatTime(addHours(windowStart, 2).toISOString())) + '</span>'
    + '<span style="left:100%">' + escapeHtml(formatTime(windowEnd.toISOString())) + '</span>';
  }

  for (i = 0; i < tvState.channels.length; i += 1) {
    var channel = tvState.channels[i];
    var programmes = visibleProgrammes(channel);
    var channelClass = "tv-channel";
    var nameClass = "tv-channel-name";
    var logo;

    if (tvState.focusedPane === "programmes" && i === tvState.focusedChannelIndex) {
      channelClass += " focused-channel";
      nameClass += " focused-title";
    }

    logo = channel.logo_url
      ? '<img class="tv-logo" src="' + escapeAttr(channel.logo_url) + '" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility=&quot;hidden&quot;" />'
      : '<div class="tv-logo-fallback">TV</div>';

    html += ''
      + '<div class="' + channelClass + '" data-index="' + i + '">'
      + '<div>' + logo + '</div>'
      + '<div>'
      + '<div class="' + nameClass + '"><span>' + escapeHtml(channel.name) + '</span></div>'
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
  renderProgrammeInfo();
  scheduleChannelNameScroll();
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
    var guideEl = $("tv-guide");
    tvState.activeGroupIndex = tvState.focusedGroupIndex;
    tvState.focusedChannelIndex = 0;
    tvState.focusedProgrammeIndex = 0;
    tvState.windowStart = null;
    tvState.selectedDate = todayDate();
    tvState.focusedDayIndex = Math.max(0, tvState.guideDates.map(function(item) { return item.date; }).indexOf(tvState.selectedDate));
    if (guideEl) guideEl.scrollTop = 0;
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
  tvState.contextChoiceIndex = 0;
  $("tv-context-title").textContent = programme.title || "Programme";
  $("tv-context-subtitle").textContent = channel.name || "Channel";
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  renderContextChoices();
  setStatus("Programme actions open.");
  try {
    $("tv-context-start").focus();
  } catch (_err) {
    // Older TV runtimes may not expose focus on button elements.
  }
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

function renderContextChoices() {
  var start = $("tv-context-start");
  var match = $("tv-context-match");
  if (start) start.className = "tv-context-choice" + (tvState.contextChoiceIndex === 0 ? " focused" : "");
  if (match) match.className = "tv-context-choice" + (tvState.contextChoiceIndex === 1 ? " focused" : "");
}

function posterForSeries(series) {
  var images = series && series.images ? series.images : [];
  var i;
  for (i = 0; i < images.length; i += 1) {
    if (String(images[i].coverType || "").toLowerCase() === "poster" && images[i].remoteUrl) {
      return images[i].remoteUrl;
    }
  }
  return (series && series.remotePoster) || "";
}

function renderSonarrResults() {
  var resultsEl = $("tv-sonarr-results");
  var html = "";
  var i;

  if (!resultsEl) return;
  if (!tvState.sonarrResults.length) {
    resultsEl.innerHTML = '<div class="tv-sonarr-empty">No Sonarr matches returned.</div>';
    return;
  }

  for (i = 0; i < tvState.sonarrResults.length; i += 1) {
    var series = tvState.sonarrResults[i] || {};
    var title = series.title || "Unknown";
    var year = series.year ? " (" + series.year + ")" : "";
    var poster = posterForSeries(series);
    var tags = [];
    var className = "tv-sonarr-result";
    if (i === tvState.sonarrFocusedIndex) className += " focused";
    if (series.network) tags.push(series.network);
    if (series.genres && series.genres.length) tags = tags.concat(series.genres.slice(0, 2));
    if (series.seasonCount != null) tags.push(series.seasonCount + " season" + (series.seasonCount === 1 ? "" : "s"));
    if (series.status) tags.push(series.status);

    html += ''
      + '<div class="' + className + '">'
      + (poster
        ? '<img class="tv-sonarr-poster" src="' + escapeAttr(poster) + '" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility=&quot;hidden&quot;" />'
        : '<div class="tv-sonarr-poster tv-sonarr-poster-empty">TV</div>')
      + '<div class="tv-sonarr-copy">'
      + '<h3>' + escapeHtml(title + year) + '</h3>'
      + '<div class="tv-sonarr-tags">' + escapeHtml(tags.join(" · ")) + '</div>'
      + '<p>' + escapeHtml(series.overview || "No overview available.") + '</p>'
      + '</div>'
      + '</div>';
  }

  resultsEl.innerHTML = html;
}

function showSonarrResults(term, results) {
  var shell = $("tv-sonarr-shell");
  tvState.sonarrOpen = true;
  tvState.sonarrMode = "results";
  tvState.sonarrResults = results || [];
  tvState.sonarrFocusedIndex = 0;
  tvState.sonarrPrepared = null;
  tvState.sonarrActionIndex = 0;
  $("tv-sonarr-title").textContent = 'Sonarr matches for "' + term + '"';
  $("tv-sonarr-status").textContent = tvState.sonarrResults.length
    ? tvState.sonarrResults.length + " possible matches. Select one to continue."
    : "No matches returned by Sonarr.";
  renderSonarrResults();
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  setStatus("Sonarr matches open.");
}

function renderSonarrActions() {
  var resultsEl = $("tv-sonarr-results");
  var prepared = tvState.sonarrPrepared || {};
  var options = prepared.options || [];
  var html = "";
  var i;

  if (!resultsEl) return;
  if (!options.length) {
    resultsEl.innerHTML = '<div class="tv-sonarr-empty">No download options are available.</div>';
    return;
  }

  for (i = 0; i < options.length; i += 1) {
    var option = options[i] || {};
    var className = "tv-sonarr-action";
    if (i === tvState.sonarrActionIndex) className += " focused";
    html += ''
      + '<div class="' + className + '">'
      + '<strong>' + escapeHtml(option.label || "Download option") + '</strong>'
      + '<span>' + escapeHtml(option.description || "") + '</span>'
      + '</div>';
  }
  resultsEl.innerHTML = html;
}

function showSonarrActions(prepared) {
  var shell = $("tv-sonarr-shell");
  var episode = prepared && prepared.matched_episode ? prepared.matched_episode : {};
  var title = prepared && prepared.title ? prepared.title : "Unknown";
  var year = prepared && prepared.year ? " (" + prepared.year + ")" : "";
  var label = episode.seasonNumber != null && episode.episodeNumber != null
    ? "S" + episode.seasonNumber + " E" + episode.episodeNumber
    : "Selected episode";
  tvState.sonarrOpen = true;
  tvState.sonarrMode = "actions";
  tvState.sonarrResults = [];
  tvState.sonarrFocusedIndex = 0;
  tvState.sonarrPrepared = prepared || null;
  tvState.sonarrActionIndex = 0;
  $("tv-sonarr-title").textContent = "Download " + title + year;
  $("tv-sonarr-status").textContent = label + ". Choose what bds-tv should ask Sonarr to monitor and search.";
  renderSonarrActions();
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  setStatus("Sonarr download options open.");
}

function showSonarrDiagnostic(result, error) {
  var shell = $("tv-sonarr-shell");
  var resultsEl = $("tv-sonarr-results");
  var title = result && result.title ? result.title : "Unknown";
  var year = result && result.year ? " (" + result.year + ")" : "";
  tvState.sonarrOpen = true;
  tvState.sonarrMode = "diagnostic";
  tvState.sonarrResults = [];
  tvState.sonarrFocusedIndex = 0;
  tvState.sonarrPrepared = null;
  tvState.sonarrActionIndex = 0;
  $("tv-sonarr-title").textContent = error ? "Sonarr download failed" : "Download sent to Sonarr";
  $("tv-sonarr-status").textContent = error ? error : (result.action_label || "Download request") + ": " + title + year;
  resultsEl.innerHTML = error
    ? '<div class="tv-sonarr-diagnostic"><strong>Unable to update Sonarr</strong><span>' + escapeHtml(error) + '</span></div>'
    : result.accepted
      ? '<div class="tv-sonarr-diagnostic">'
        + '<strong>' + escapeHtml(result.action_label || "Download request accepted") + '</strong>'
        + '<span>Selected: S' + escapeHtml(result.selected_season || "?") + ' E' + escapeHtml(result.selected_episode || "?") + '</span>'
        + '<span>bds-tv will update Sonarr monitoring and start the search.</span>'
        + '<span>Job ID: ' + escapeHtml(result.job_id || "unknown") + '</span>'
        + '</div>'
    : '<div class="tv-sonarr-diagnostic">'
      + '<strong>' + escapeHtml(result.action_label || "Download request sent") + '</strong>'
      + '<span>Selected: S' + escapeHtml(result.selected_season || "?") + ' E' + escapeHtml(result.selected_episode || "?") + '</span>'
      + '<span>Monitored episodes: ' + escapeHtml(result.monitored_episode_count || 0) + '</span>'
      + '<span>Monitored seasons: ' + escapeHtml(result.monitored_season_count || 0) + '</span>'
      + '<span>Series monitored: ' + escapeHtml(result.series_monitored ? "yes" : "no") + '</span>'
      + '</div>';
  shell.classList.remove("hidden");
  shell.style.display = "block";
  shell.setAttribute("aria-hidden", "false");
  setStatus(error ? "Sonarr update failed." : "Download sent to Sonarr.");
}

function hideSonarrResults() {
  var shell = $("tv-sonarr-shell");
  tvState.sonarrOpen = false;
  tvState.sonarrMode = "results";
  tvState.sonarrResults = [];
  tvState.sonarrFocusedIndex = 0;
  tvState.sonarrPrepared = null;
  tvState.sonarrActionIndex = 0;
  shell.classList.add("hidden");
  shell.style.display = "none";
  shell.setAttribute("aria-hidden", "true");
}

function matchContextShow() {
  var programme = tvState.contextProgramme;
  var title = programme ? String(programme.title || "").trim() : "";
  if (!title) {
    hideContextMenu();
    showSonarrResults("Unknown", []);
    $("tv-sonarr-status").textContent = "No programme title was available to search.";
    return;
  }

  hideContextMenu();
  setStatus("Searching Sonarr for " + title + "...");
  api("/api/sonarr/series/lookup?term=" + encodeURIComponent(title), function(err, body) {
    if (err) {
      showSonarrResults(title, []);
      $("tv-sonarr-status").textContent = "Sonarr lookup failed: " + err.message;
      return;
    }
    showSonarrResults(title, (body && body.results) || []);
  });
}

function moveSonarrFocus(delta) {
  if (!tvState.sonarrResults.length) return;
  tvState.sonarrFocusedIndex = Math.max(0, Math.min(tvState.sonarrResults.length - 1, tvState.sonarrFocusedIndex + delta));
  renderSonarrResults();
  scrollFocusedIntoView(".tv-sonarr-result.focused", "tv-sonarr-results");
}

function moveSonarrAction(delta) {
  var prepared = tvState.sonarrPrepared || {};
  var options = prepared.options || [];
  if (!options.length) return;
  tvState.sonarrActionIndex = Math.max(0, Math.min(options.length - 1, tvState.sonarrActionIndex + delta));
  renderSonarrActions();
  scrollFocusedIntoView(".tv-sonarr-action.focused", "tv-sonarr-results");
}

function resolveSelectedSonarrSeries() {
  var selectedSeries = tvState.sonarrResults[tvState.sonarrFocusedIndex];
  var programme = tvState.contextProgramme;
  if (!selectedSeries) {
    setStatus("No Sonarr match selected.");
    return;
  }
  if (!programme || programme.season == null || programme.episode == null) {
    showSonarrDiagnostic(null, "This programme does not include a season and episode number.");
    return;
  }

  $("tv-sonarr-status").textContent = "Preparing " + (selectedSeries.title || "show") + " in Sonarr...";
  setStatus("Preparing Sonarr show...");
  apiPost("/api/sonarr/series/resolve", selectedSeries, function(err, body) {
    if (err) {
      showSonarrDiagnostic(null, err.message);
      return;
    }
    apiPost("/api/sonarr/series/download-options", {
      series_id: body.series_id,
      title: body.title,
      year: body.year,
      programme: programme
    }, function(optionsErr, optionsBody) {
      if (optionsErr) {
        showSonarrDiagnostic(null, optionsErr.message);
        return;
      }
      showSonarrActions(optionsBody);
    });
  });
}

function applySelectedSonarrAction() {
  var prepared = tvState.sonarrPrepared || {};
  var options = prepared.options || [];
  var option = options[tvState.sonarrActionIndex];
  if (!option) {
    setStatus("No download option selected.");
    return;
  }

  $("tv-sonarr-status").textContent = "Sending " + (option.label || "download option") + " to Sonarr...";
  setStatus("Updating Sonarr monitoring...");
  apiPost("/api/sonarr/series/download", {
    series_id: prepared.series_id,
    title: prepared.title,
    year: prepared.year,
    programme: prepared.programme,
    action: option.id
  }, function(err, body) {
    if (err) {
      showSonarrDiagnostic(null, err.message);
      return;
    }
    showSonarrDiagnostic(body, null);
  });
}

function hasNativePlayer() {
  return !!(window.webapis && webapis.avplay);
}

function prepareNativePlayerSurface() {
  var avObject = $("av-player");
  if (!avObject) return;
  avObject.style.left = "0px";
  avObject.style.top = "0px";
  avObject.style.width = "1920px";
  avObject.style.height = "1080px";
}

function playChannel(channel) {
  var playerShell = $("tv-player-shell");
  var player = $("tv-player");
  var url = serverBaseUrl() + "/tv/stream/" + encodeURIComponent(channel.channel_id) + ".mpg";
  $("tv-player-title").textContent = channel.name || "Channel";
  playerShell.classList.remove("hidden");
  playerShell.style.display = "block";
  tvState.playbackOpen = true;

  if (hasNativePlayer()) {
    tvState.playbackMode = "avplay";
    playerShell.classList.add("native");
    prepareNativePlayerSurface();
    player.removeAttribute("src");
    player.style.display = "none";
    try {
      try {
        webapis.avplay.close();
      } catch (_closeErr) {
        // Close can fail if AVPlay has not been opened yet.
      }
      webapis.avplay.open(url);
      webapis.avplay.setListener({
        onbufferingstart: function() { setStatus("Buffering stream..."); },
        onbufferingcomplete: function() { setStatus("Playing " + (channel.name || "channel") + "."); },
        onstreamcompleted: function() { stopPlayback(); },
        onerror: function(eventType) { setStatus("Playback failed: " + eventType); }
      });
      webapis.avplay.setDisplayRect(0, 0, 1920, 1080);
      try {
        webapis.avplay.setDisplayMethod("PLAYER_DISPLAY_MODE_FULL_SCREEN");
      } catch (_displayErr) {
        // Some runtimes do not expose display method control.
      }
      webapis.avplay.prepareAsync(
        function() {
          webapis.avplay.play();
          setStatus("Playing " + (channel.name || "channel") + ".");
        },
        function(err) {
          setStatus("Playback failed: " + (err && err.message ? err.message : err));
          stopPlayback();
        }
      );
      return;
    } catch (err) {
      setStatus("Native playback failed: " + err.message);
      tvState.playbackMode = "html5";
      playerShell.classList.remove("native");
      player.style.display = "block";
    }
  } else {
    tvState.playbackMode = "html5";
    playerShell.classList.remove("native");
    player.style.display = "block";
  }

  player.src = url;

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
  if (tvState.playbackMode === "avplay" && hasNativePlayer()) {
    try {
      webapis.avplay.stop();
    } catch (_stopErr) {
      // Ignore invalid-state errors while closing.
    }
    try {
      webapis.avplay.close();
    } catch (_closeErr) {
      // Ignore invalid-state errors while closing.
    }
  }
  player.pause();
  player.removeAttribute("src");
  player.load();
  playerShell.classList.remove("native");
  player.style.display = "block";
  playerShell.classList.add("hidden");
  playerShell.style.display = "none";
  tvState.playbackOpen = false;
  tvState.playbackMode = "";
}

function playerOpen() {
  var player = $("tv-player");
  return tvState.playbackOpen || !!(player && (player.currentSrc || player.getAttribute("src")));
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

  if (tvState.sonarrOpen) {
    hideSonarrResults();
    setStatus("Sonarr matches closed.");
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

  if (tvState.sonarrOpen) {
    if (normalisedKey === "ArrowUp") {
      if (tvState.sonarrMode === "actions") {
        moveSonarrAction(-1);
      } else {
        moveSonarrFocus(-1);
      }
    }
    if (normalisedKey === "ArrowDown") {
      if (tvState.sonarrMode === "actions") {
        moveSonarrAction(1);
      } else {
        moveSonarrFocus(1);
      }
    }
    if (normalisedKey === "Enter") {
      if (tvState.sonarrMode === "actions") {
        applySelectedSonarrAction();
      } else if (tvState.sonarrMode === "results") {
        resolveSelectedSonarrSeries();
      }
    }
    return;
  }

  if (tvState.contextOpen) {
    if (normalisedKey === "ArrowUp" || normalisedKey === "ArrowDown") {
      tvState.contextChoiceIndex = tvState.contextChoiceIndex === 0 ? 1 : 0;
      renderContextChoices();
    }
    if (normalisedKey === "Enter") {
      if (tvState.contextChoiceIndex === 0) {
        startContextStream();
      } else {
        matchContextShow();
      }
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

document.addEventListener("keydown", handleKey, true);
window.addEventListener("keydown", handleKey, true);
$("tv-exit-yes").addEventListener("click", exitApp);
$("tv-exit-no").addEventListener("click", hideExitConfirm);
$("tv-context-start").addEventListener("click", startContextStream);
$("tv-context-match").addEventListener("click", matchContextShow);
setInterval(updateClock, 15000);
setShellVersion();
updateClock();
setStatus("TV script loaded");
startTvGuide();
