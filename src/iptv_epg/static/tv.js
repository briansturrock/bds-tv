var tvState = {
  groups: [],
  channels: [],
  activeGroupIndex: 0,
  focusedPane: "groups",
  focusedGroupIndex: 0,
  focusedChannelIndex: 0,
  windowStart: null,
  loading: false,
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

function setStatus(message) {
  $("tv-status").textContent = message;
}

function updateClock() {
  $("tv-clock").textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit"
  });
}

function scrollFocusedIntoView(selector) {
  var focused = document.querySelector(selector);
  if (focused && focused.scrollIntoView) {
    focused.scrollIntoView({ block: "nearest" });
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
  scrollFocusedIntoView(".tv-group.focused");
}

function programmeCard(programme, fallback) {
  if (!programme) {
    return ''
      + '<div class="tv-programme">'
      + '<strong>' + escapeHtml(fallback) + '</strong>'
      + '<span>No programme data</span>'
      + '</div>';
  }

  var time = formatTime(programme.start) + " - " + formatTime(programme.stop);
  return ''
    + '<div class="tv-programme' + (programme.is_now ? " now" : "") + '">'
    + '<strong>' + escapeHtml(programme.title || "Unknown") + '</strong>'
    + '<span>' + escapeHtml(time) + (programme.is_now ? " · Now" : "") + '</span>'
    + '</div>';
}

function firstCurrentProgramme(programmes) {
  var i;
  for (i = 0; i < programmes.length; i += 1) {
    if (programmes[i].is_now) return programmes[i];
  }
  return programmes[0] || null;
}

function firstNextProgramme(programmes, current) {
  var i;
  for (i = 0; i < programmes.length; i += 1) {
    if (!programmes[i].is_now && programmes[i].start && (!(current && current.stop) || programmes[i].start >= current.stop)) {
      return programmes[i];
    }
  }
  return null;
}

function renderChannels() {
  var guideEl = $("tv-guide");
  var group = tvState.groups[tvState.activeGroupIndex];
  var html = "";
  var i;

  $("tv-group-title").textContent = (group && group.name) || "Guide";
  $("tv-group-meta").textContent = tvState.channels.length
    ? tvState.channels.length + " channels · Enter plays highlighted channel"
    : "No channels in this group";

  if (!tvState.channels.length) {
    guideEl.innerHTML = '<div class="tv-empty">No selected channels.</div>';
    return;
  }

  for (i = 0; i < tvState.channels.length; i += 1) {
    var channel = tvState.channels[i];
    var programmes = channel.programmes || [];
    var current = firstCurrentProgramme(programmes);
    var next = firstNextProgramme(programmes, current);
    var className = "tv-channel";
    var logo;

    if (tvState.focusedPane === "channels" && i === tvState.focusedChannelIndex) className += " focused";

    logo = channel.logo_url
      ? '<img class="tv-logo" src="' + escapeAttr(channel.logo_url) + '" alt="" referrerpolicy="no-referrer" onerror="this.style.visibility=&quot;hidden&quot;" />'
      : '<div class="tv-logo-fallback">TV</div>';

    html += ''
      + '<div class="' + className + '" data-index="' + i + '">'
      + '<div>' + logo + '</div>'
      + '<div>'
      + '<div class="tv-channel-name">' + escapeHtml(channel.name) + '</div>'
      + '<div class="tv-channel-meta">' + escapeHtml(channel.tvg_id || channel.group_name || "") + '</div>'
      + '</div>'
      + '<div class="tv-programmes">'
      + programmeCard(current, "Unknown")
      + programmeCard(next, "Next")
      + '</div>'
      + '</div>';
  }

  guideEl.innerHTML = html;
  scrollFocusedIntoView(".tv-channel.focused");
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

function loadActiveGroup() {
  if (tvState.loading) return;

  var group = tvState.groups[tvState.activeGroupIndex];
  if (!group) return;

  tvState.loading = true;
  setStatus("Loading " + group.name + "...");

  var start = floorDateToHalfHour(new Date()).toISOString();
  var path = "/api/guide?group_id=" + encodeURIComponent(group.id)
    + "&start=" + encodeURIComponent(start)
    + "&hours=6";

  api(path, function(err, body) {
    tvState.loading = false;
    if (err) {
      setStatus("Guide failed: " + err.message);
      return;
    }

    tvState.channels = body.channels || [];
    tvState.focusedChannelIndex = Math.min(tvState.focusedChannelIndex, Math.max(0, tvState.channels.length - 1));
    tvState.windowStart = body.window_start;
    renderGroups();
    renderChannels();
    setStatus("Ready");
  });
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

function activateFocused() {
  if (tvState.exitConfirmOpen) {
    confirmExitChoice();
    return;
  }

  if (tvState.focusedPane === "groups") {
    tvState.activeGroupIndex = tvState.focusedGroupIndex;
    tvState.focusedChannelIndex = 0;
    loadActiveGroup();
    return;
  }

  var channel = tvState.channels[tvState.focusedChannelIndex];
  if (channel) {
    playChannel(channel);
  }
}

function playChannel(channel) {
  var playerShell = $("tv-player-shell");
  var player = $("tv-player");
  $("tv-player-title").textContent = channel.name || "Channel";
  playerShell.classList.remove("hidden");
  player.src = "/dlna/channel/" + encodeURIComponent(channel.channel_id) + ".mpg";

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
}

function playerOpen() {
  return !$("tv-player-shell").classList.contains("hidden");
}

function renderExitConfirm() {
  $("tv-exit-yes").className = "tv-exit-choice" + (tvState.exitConfirmYes ? " focused" : "");
  $("tv-exit-no").className = "tv-exit-choice" + (!tvState.exitConfirmYes ? " focused" : "");
}

function showExitConfirm() {
  tvState.exitConfirmOpen = true;
  tvState.exitConfirmYes = true;
  $("tv-exit-shell").classList.remove("hidden");
  renderExitConfirm();
}

function hideExitConfirm() {
  tvState.exitConfirmOpen = false;
  $("tv-exit-shell").classList.add("hidden");
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
    return;
  }

  if (tvState.exitConfirmOpen) {
    hideExitConfirm();
    return;
  }

  showExitConfirm();
}

function handleKey(event) {
  var key = event.key || event.code;
  var code = event.keyCode || event.which || 0;
  var normalisedKey = ({
    13: "Enter",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    10009: "Backspace"
  })[code] || key;

  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Backspace", "Escape"].indexOf(normalisedKey) >= 0) {
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
    activateFocused();
  }
}

function handleShellMessage(event) {
  var data = event.data || {};
  if (data && data.type === "bds-tv-back") {
    handleBack();
  }
}

document.addEventListener("keydown", handleKey);
window.addEventListener("message", handleShellMessage);
setInterval(updateClock, 15000);
updateClock();
setStatus("TV script loaded");
loadGroups();
