from __future__ import annotations

import json
import threading
import time
from urllib.request import Request, urlopen

from fastapi import HTTPException

from . import __version__
from .db import get_setting, set_setting


PUBLIC_IP_CACHE_TTL_SECONDS = 15 * 60
PUBLIC_IP_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}
PUBLIC_IP_LOCK = threading.Lock()


def bool_setting(key: str, default: bool) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalise_country_code(value: str | None) -> str:
    code = (value or "").strip().upper()
    return code if len(code) == 2 and code.isalpha() else ""


def get_killswitch_settings() -> dict:
    return {
        "enabled": bool_setting("killswitch_enabled", False),
        "home_country_code": normalise_country_code(get_setting("killswitch_home_country_code")),
    }


def save_killswitch_settings(enabled: bool, home_country_code: str | None) -> dict:
    set_setting("killswitch_enabled", "true" if enabled else "false")
    set_setting("killswitch_home_country_code", normalise_country_code(home_country_code))
    return get_killswitch_settings()


def country_flag(country_code: str | None) -> str:
    code = normalise_country_code(country_code)
    if not code:
        return ""
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def fetch_json(url: str, timeout: float = 5.0) -> dict:
    request = Request(url, headers={"User-Agent": f"iptv-epg/{__version__}"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_text(url: str, timeout: float = 5.0) -> str:
    request = Request(url, headers={"User-Agent": f"iptv-epg/{__version__}"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace").strip()


def lookup_public_ip() -> dict:
    errors: list[str] = []
    ip_lookups = [
        (
            "checkip.amazonaws.com",
            lambda: fetch_text("https://checkip.amazonaws.com/"),
        ),
        (
            "api4.ipify.org",
            lambda: fetch_json("https://api4.ipify.org?format=json").get("ip") or "",
        ),
        (
            "ipv4.icanhazip.com",
            lambda: fetch_text("https://ipv4.icanhazip.com/"),
        ),
    ]

    ip = ""
    ip_source = ""
    for source, fetcher in ip_lookups:
        try:
            candidate = fetcher().strip()
            if not candidate:
                raise RuntimeError("lookup did not return an IP address")
            if ":" in candidate:
                raise RuntimeError("lookup returned IPv6 address")
            ip = candidate
            ip_source = source
            break
        except Exception as exc:
            errors.append(f"{source}: {exc}")

    if ip:
        country_code = ""
        country_name = ""
        for source, url, parser in [
            (
                "ip-api.com",
                f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode",
                lambda data: (data.get("countryCode") or "", data.get("country") or ""),
            ),
            (
                "ipapi.co",
                f"https://ipapi.co/{ip}/json/",
                lambda data: (data.get("country_code") or "", data.get("country_name") or ""),
            ),
        ]:
            try:
                data = fetch_json(url)
                if data.get("error") or data.get("status") == "fail":
                    raise RuntimeError(data.get("reason") or data.get("message") or "lookup failed")
                country_code, country_name = parser(data)
                break
            except Exception as exc:
                errors.append(f"{source}: {exc}")
        return {
            "ok": True,
            "source": ip_source,
            "ip": ip,
            "country_code": normalise_country_code(country_code),
            "country_name": country_name,
            "flag": country_flag(country_code),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "geo_error": "; ".join(errors) if not country_code else "",
        }

    return {
        "ok": False,
        "source": "",
        "ip": "",
        "country_code": "",
        "country_name": "",
        "flag": "",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "error": "; ".join(errors),
    }


def cached_public_ip(force_refresh: bool = False) -> dict:
    now = time.time()
    if not force_refresh:
        with PUBLIC_IP_LOCK:
            cached = PUBLIC_IP_CACHE.get("payload")
            if cached and now < float(PUBLIC_IP_CACHE.get("expires_at") or 0):
                return dict(cached)

    payload = lookup_public_ip()
    with PUBLIC_IP_LOCK:
        PUBLIC_IP_CACHE["payload"] = payload
        PUBLIC_IP_CACHE["expires_at"] = now + PUBLIC_IP_CACHE_TTL_SECONDS
    return dict(payload)


def stream_killswitch_status(force_refresh: bool = False) -> dict:
    settings = get_killswitch_settings()
    public_ip = cached_public_ip(force_refresh)
    home_country = settings["home_country_code"]
    current_country = normalise_country_code(public_ip.get("country_code"))
    blocked = bool(settings["enabled"] and home_country and current_country and home_country == current_country)
    return {
        "enabled": settings["enabled"],
        "home_country_code": home_country,
        "public_ip": public_ip,
        "blocked": blocked,
    }


def enforce_stream_killswitch() -> None:
    status = stream_killswitch_status()
    if not status["blocked"]:
        return
    public_ip = status["public_ip"]
    country = public_ip.get("country_code") or status["home_country_code"]
    raise HTTPException(
        status_code=503,
        detail=f"Streaming killswitch active: public IP geolocation is {country}.",
    )
