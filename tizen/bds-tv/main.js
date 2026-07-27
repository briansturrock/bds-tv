const DEFAULT_SERVER = "http://192.168.0.185:8088";
const SERVER_KEY = "bdsTvServerUrl";
const statusEl = document.getElementById("status");
const retryEl = document.getElementById("retry");

function serverBaseUrl() {
  return (localStorage.getItem(SERVER_KEY) || DEFAULT_SERVER).replace(/\/$/, "");
}

function setStatus(message, failed = false) {
  statusEl.textContent = message;
  retryEl.classList.toggle("hidden", !failed);
}

async function openHostedApp() {
  const base = serverBaseUrl();
  setStatus("Connecting to bds-tv...");

  try {
    const response = await fetch(`${base}/health`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Health check returned ${response.status}`);
    }
    window.location.replace(`${base}/tv`);
  } catch (err) {
    setStatus(`Could not reach ${base}. Check bds-tv is running, then retry.`, true);
  }
}

function handleKey(event) {
  const keyCode = event.keyCode || event.which || 0;
  if (keyCode === 13 && !retryEl.classList.contains("hidden")) {
    event.preventDefault();
    openHostedApp();
  }
}

retryEl.addEventListener("click", openHostedApp);
document.addEventListener("keydown", handleKey);
openHostedApp();
