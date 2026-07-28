const SHELL_VERSION = "0.1.5";
const DEFAULT_SERVER = "http://192.168.0.185:8088";
const SERVER_KEY = "bdsTvServerUrl";

const shellEl = document.querySelector(".shell");
const hostedEl = document.getElementById("hosted-app");
const statusEl = document.getElementById("status");
const retryEl = document.getElementById("retry");
const versionEl = document.getElementById("version");

function serverBaseUrl() {
  return (localStorage.getItem(SERVER_KEY) || DEFAULT_SERVER).replace(/\/$/, "");
}

function setStatus(message, failed = false) {
  statusEl.textContent = message;
  retryEl.classList.toggle("hidden", !failed);
}

function showHostedApp(url) {
  hostedEl.src = url;
  hostedEl.classList.remove("hidden");
  shellEl.classList.add("hidden");
}

function closeNativeApp() {
  setStatus("Closing bds-tv...");
  hostedEl.src = "about:blank";
  hostedEl.classList.add("hidden");
  shellEl.classList.remove("hidden");

  try {
    if (window.tizen && tizen.application && tizen.application.getCurrentApplication) {
      tizen.application.getCurrentApplication().exit();
      return;
    }
  } catch (err) {
    setStatus(`Native close failed: ${err.message}`, true);
  }

  try {
    window.close();
    return;
  } catch (_err) {
    // Some TV runtimes block window.close().
  }

  hostedEl.classList.add("hidden");
  shellEl.classList.remove("hidden");
  setStatus("Use Home to leave bds-tv.", true);
}

async function openHostedApp() {
  const base = serverBaseUrl();
  hostedEl.classList.add("hidden");
  shellEl.classList.remove("hidden");
  setStatus("Connecting to bds-tv...");

  try {
    const response = await fetch(`${base}/health`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Health check returned ${response.status}`);
    }
    showHostedApp(`${base}/tv`);
  } catch (err) {
    setStatus(`Could not reach ${base}. Check bds-tv is running, then retry.`, true);
  }
}

function handleKey(event) {
  const keyCode = event.keyCode || event.which || 0;
  if (keyCode === 13 && !retryEl.classList.contains("hidden")) {
    event.preventDefault();
    openHostedApp();
    return;
  }

  if (keyCode === 10009 && !hostedEl.classList.contains("hidden")) {
    event.preventDefault();
    hostedEl.contentWindow.postMessage({ type: "bds-tv-back" }, "*");
    return;
  }

  if (keyCode === 10009) {
    event.preventDefault();
    closeNativeApp();
  }
}

function handleMessage(event) {
  const data = event.data || {};
  if (data && data.type === "bds-tv-exit") {
    closeNativeApp();
  }
}

function handleTizenHardwareKey(event) {
  if (event.keyName === "back" && !hostedEl.classList.contains("hidden")) {
    hostedEl.contentWindow.postMessage({ type: "bds-tv-back" }, "*");
    return;
  }

  if (event.keyName === "back") {
    closeNativeApp();
  }
}

versionEl.textContent = `TV shell ${SHELL_VERSION}`;
retryEl.addEventListener("click", openHostedApp);
document.addEventListener("keydown", handleKey);
window.addEventListener("message", handleMessage);
document.addEventListener("tizenhwkey", handleTizenHardwareKey);
openHostedApp();
