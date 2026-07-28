from __future__ import annotations

import base64
import ipaddress
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .db import get_settings, set_setting


router = APIRouter(tags=["tv-app"])

SDB_PORT = 26101
SAMSUNG_API_PORT = 8001
SCAN_TIMEOUT_SECONDS = 0.35
SAMSUNG_API_TIMEOUT_SECONDS = 1.5
MAX_SCAN_WORKERS = 64

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
