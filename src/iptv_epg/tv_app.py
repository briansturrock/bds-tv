from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import shutil
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .db import get_settings, set_setting


router = APIRouter(tags=["tv-app"])

SDB_PORT = 26101
SAMSUNG_API_PORT = 8001
SCAN_TIMEOUT_SECONDS = 0.35
SAMSUNG_API_TIMEOUT_SECONDS = 1.5
MAX_SCAN_WORKERS = 64
APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parent
TIZEN_SOURCE_DIRS = (APP_ROOT / "tizen" / "bds-tv", REPO_ROOT / "tizen" / "bds-tv")
TV_APP_BUILD_DIR = Path(os.getenv("DATA_DIR", str(REPO_ROOT / "data"))) / "tv-app"
TV_APP_PACKAGE_NAME = "bds-tv.wgt"
TV_APP_PACKAGE_ID = "bdstv00001"
TV_APP_APPLICATION_ID = "bdstv00001.shell"

TV_APP_SETTING_KEYS: tuple[str, ...] = (
    "tv_app_author_p12_name",
    "tv_app_author_p12_data",
    "tv_app_distributor_p12_name",
    "tv_app_distributor_p12_data",
    "tv_app_cert_password",
    "tv_app_manual_tv_ip",
    "tv_app_remove_old_version",
    "tv_app_launch_after_install",
)


class TvAppSettingsIn(BaseModel):
    author_p12_name: str = ""
    author_p12_data: str = ""
    distributor_p12_name: str = ""
    distributor_p12_data: str = ""
    cert_password: str = ""
    manual_tv_ip: str = ""
    remove_old_version: bool = True
    launch_after_install: bool = False


class TvAppDiscoverIn(BaseModel):
    manual_tv_ip: str = ""
    include_manual: bool = True


class TvAppInstallIn(BaseModel):
    tv_ip: str
    remove_old_version: bool = True
    launch_after_install: bool = False


@dataclass
class TvProbe:
    ip: str
    debug_port_open: bool = False
    tv_api_open: bool = False
    device_name: str = ""
    model_name: str = ""
    manufacturer: str = ""
    developer_mode: str = ""
    developer_ip: str = ""
    error: str = ""

    @property
    def install_ready(self) -> bool:
        return self.debug_port_open

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "device_name": self.device_name,
            "model_name": self.model_name,
            "manufacturer": self.manufacturer,
            "developer_mode": self.developer_mode,
            "developer_ip": self.developer_ip,
            "debug_port_open": self.debug_port_open,
            "tv_api_open": self.tv_api_open,
            "install_ready": self.install_ready,
            "error": self.error,
        }


def bool_value(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def decoded_size(value: str | None) -> int:
    if not value:
        return 0
    try:
        return len(base64.b64decode(value, validate=True))
    except Exception:
        return len(value.encode("utf-8"))


def settings_payload() -> dict[str, Any]:
    settings = get_settings(TV_APP_SETTING_KEYS)
    author_data = settings.get("tv_app_author_p12_data", "")
    distributor_data = settings.get("tv_app_distributor_p12_data", "")
    package = package_path()
    return {
        "author_p12_name": settings.get("tv_app_author_p12_name", ""),
        "author_p12_saved": bool(author_data),
        "author_p12_size": decoded_size(author_data),
        "distributor_p12_name": settings.get("tv_app_distributor_p12_name", ""),
        "distributor_p12_saved": bool(distributor_data),
        "distributor_p12_size": decoded_size(distributor_data),
        "cert_password_saved": bool(settings.get("tv_app_cert_password", "")),
        "manual_tv_ip": settings.get("tv_app_manual_tv_ip", ""),
        "remove_old_version": bool_value(settings.get("tv_app_remove_old_version"), True),
        "launch_after_install": bool_value(settings.get("tv_app_launch_after_install"), False),
        "package_built": package.exists(),
        "package_name": package.name,
        "package_size": package.stat().st_size if package.exists() else 0,
        "package_updated_at": datetime.fromtimestamp(package.stat().st_mtime, UTC).isoformat() if package.exists() else "",
        "sdb_available": bool(resolve_executable("sdb")),
    }


def clean_ip(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return ""


def local_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None


def add_scan_network(candidates: set[str], ip_text: str | None) -> None:
    ip = clean_ip(ip_text)
    if not ip:
        return
    try:
        network = ipaddress.ip_network(f"{ip}/24", strict=False)
        candidates.update(str(host) for host in network.hosts())
    except ValueError:
        candidates.add(ip)


def configured_lan_ips() -> list[str]:
    settings = get_settings(("hdhr_public_base_url", "dlna_public_base_url"))
    ips: list[str] = []
    for value in settings.values():
        if not value:
            continue
        host = urlparse(value).hostname or ""
        if clean_ip(host):
            ips.append(host)
    return ips


def scan_candidates(manual_ip: str = "") -> list[str]:
    candidates: set[str] = set()
    add_scan_network(candidates, local_ipv4())
    for ip in configured_lan_ips():
        add_scan_network(candidates, ip)

    manual = clean_ip(manual_ip)
    if manual:
        candidates.add(manual)

    return sorted(candidates, key=lambda value: tuple(int(part) for part in value.split(".")))


def is_port_open(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=SCAN_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def fetch_samsung_info(probe: TvProbe) -> None:
    if not probe.tv_api_open:
        return

    url = f"http://{probe.ip}:{SAMSUNG_API_PORT}/api/v2/"
    try:
        request = Request(url, headers={"User-Agent": "bds-tv-tv-app/1.0"})
        with urlopen(request, timeout=SAMSUNG_API_TIMEOUT_SECONDS) as response:
            raw = response.read(65536).decode("utf-8", errors="replace")
        data = json.loads(raw)
        device = data.get("device") if isinstance(data, dict) else None
        if not isinstance(device, dict):
            return
        probe.device_name = str(device.get("name") or "")
        probe.model_name = str(device.get("modelName") or "")
        probe.manufacturer = str(device.get("type") or "")
        probe.developer_mode = str(device.get("developerMode") or "")
        probe.developer_ip = str(device.get("developerIP") or "")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        probe.error = str(exc)


def probe_tv(ip: str) -> TvProbe | None:
    probe = TvProbe(ip=ip)
    probe.debug_port_open = is_port_open(ip, SDB_PORT)
    probe.tv_api_open = is_port_open(ip, SAMSUNG_API_PORT)
    if not probe.debug_port_open and not probe.tv_api_open:
        return None
    fetch_samsung_info(probe)
    return probe


def discover_tvs(manual_ip: str = "") -> list[dict[str, Any]]:
    candidates = scan_candidates(manual_ip)
    results: list[TvProbe] = []
    with ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS) as executor:
        futures = {executor.submit(probe_tv, ip): ip for ip in candidates}
        for future in as_completed(futures):
            try:
                probe = future.result()
            except Exception:
                probe = None
            if probe:
                results.append(probe)

    results.sort(key=lambda probe: (not probe.install_ready, probe.device_name or probe.ip, probe.ip))
    return [probe.to_dict() for probe in results]


def tizen_source_dir() -> Path:
    for path in TIZEN_SOURCE_DIRS:
        if (path / "config.xml").exists():
            return path
    raise HTTPException(status_code=500, detail="Tizen source folder was not found in this build.")


def package_path() -> Path:
    return TV_APP_BUILD_DIR / TV_APP_PACKAGE_NAME


def build_wgt() -> dict[str, Any]:
    source_dir = tizen_source_dir()
    TV_APP_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    output = package_path()
    with tempfile.TemporaryDirectory(prefix="bds-tv-wgt-") as tmp:
        staging = Path(tmp) / "bds-tv"
        shutil.copytree(source_dir, staging)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
    return package_payload(output)


def package_payload(path: Path | None = None) -> dict[str, Any]:
    candidate = path or package_path()
    exists = candidate.exists()
    return {
        "built": exists,
        "name": candidate.name,
        "path": str(candidate),
        "size": candidate.stat().st_size if exists else 0,
        "updated_at": datetime.fromtimestamp(candidate.stat().st_mtime, UTC).isoformat() if exists else "",
    }


def resolve_executable(name: str) -> str:
    return shutil.which(name) or ""


def run_sdb(args: list[str], timeout: int = 45) -> dict[str, Any]:
    sdb = resolve_executable("sdb")
    if not sdb:
        raise HTTPException(
            status_code=409,
            detail="sdb is not installed in the bds-tv runtime, so direct TV install is not available yet.",
        )
    completed = subprocess.run(
        [sdb, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": "sdb " + " ".join(args),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def install_wgt(payload: TvAppInstallIn) -> dict[str, Any]:
    tv_ip = clean_ip(payload.tv_ip)
    if not tv_ip:
        raise HTTPException(status_code=400, detail="A valid TV IP address is required.")
    package = package_path()
    if not package.exists():
        build_wgt()

    steps: list[dict[str, Any]] = []
    steps.append(run_sdb(["connect", tv_ip], timeout=20))
    if payload.remove_old_version:
        steps.append(run_sdb(["uninstall", TV_APP_PACKAGE_ID], timeout=30))
    steps.append(run_sdb(["install", str(package)], timeout=90))
    if payload.launch_after_install:
        steps.append(run_sdb(["shell", "0", "was_execute", TV_APP_APPLICATION_ID], timeout=20))

    ok = bool(steps and steps[-1]["returncode"] == 0)
    return {"ok": ok, "tv_ip": tv_ip, "package": package_payload(package), "steps": steps}


@router.get("/api/tv-app/settings")
def api_tv_app_settings() -> dict[str, Any]:
    return {"ok": True, "settings": settings_payload()}


@router.post("/api/tv-app/settings")
def api_save_tv_app_settings(payload: TvAppSettingsIn) -> dict[str, Any]:
    if payload.author_p12_data:
        set_setting("tv_app_author_p12_name", payload.author_p12_name.strip() or "author.p12")
        set_setting("tv_app_author_p12_data", payload.author_p12_data.strip())
    if payload.distributor_p12_data:
        set_setting("tv_app_distributor_p12_name", payload.distributor_p12_name.strip() or "distributor.p12")
        set_setting("tv_app_distributor_p12_data", payload.distributor_p12_data.strip())
    if payload.cert_password:
        set_setting("tv_app_cert_password", payload.cert_password)
    set_setting("tv_app_manual_tv_ip", clean_ip(payload.manual_tv_ip))
    set_setting("tv_app_remove_old_version", "true" if payload.remove_old_version else "false")
    set_setting("tv_app_launch_after_install", "true" if payload.launch_after_install else "false")
    return {"ok": True, "settings": settings_payload()}


@router.post("/api/tv-app/discover")
def api_discover_tv_app_devices(payload: TvAppDiscoverIn) -> dict[str, Any]:
    manual_ip = payload.manual_tv_ip if payload.include_manual else ""
    return {"ok": True, "devices": discover_tvs(manual_ip)}


@router.post("/api/tv-app/package")
def api_build_tv_app_package() -> dict[str, Any]:
    return {"ok": True, "package": build_wgt(), "settings": settings_payload()}


@router.get("/api/tv-app/package/download")
def api_download_tv_app_package() -> FileResponse:
    package = package_path()
    if not package.exists():
        build_wgt()
    return FileResponse(package, media_type="application/widget", filename=package.name)


@router.post("/api/tv-app/install")
def api_install_tv_app_package(payload: TvAppInstallIn) -> dict[str, Any]:
    result = install_wgt(payload)
    return {"ok": result["ok"], "install": result, "settings": settings_payload()}
