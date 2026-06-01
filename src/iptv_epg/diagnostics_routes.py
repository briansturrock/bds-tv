from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from .diagnostics_registry import get_diagnostic_endpoints


router = APIRouter(prefix="/dev/diagnostics", tags=["diagnostics"])
STATIC_DIR = Path(__file__).parent / "static"


def route_methods(route: Any) -> set[str]:
    methods = getattr(route, "methods", set()) or set()
    return {m for m in methods if m not in {"HEAD", "OPTIONS"}}


def route_path(route: Any) -> str | None:
    path = getattr(route, "path", None)
    return str(path) if path else None


def should_ignore_route(path: str) -> bool:
    if path in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}:
        return True
    return path.startswith("/static")


@router.get("", response_model=None)
def diagnostics_console() -> FileResponse:
    return FileResponse(STATIC_DIR / "diagnostics.html", media_type="text/html")


@router.get("/endpoints")
def diagnostics_endpoints() -> dict:
    return {"ok": True, "endpoints": get_diagnostic_endpoints()}


@router.get("/coverage")
def diagnostics_coverage(request: Request) -> dict:
    registered_entries = get_diagnostic_endpoints()
    registered = {(entry["method"].upper(), entry["path"]) for entry in registered_entries}

    actual = set()
    actual_details = []
    for route in request.app.routes:
        path = route_path(route)
        if not path or should_ignore_route(path):
            continue
        for method in route_methods(route):
            item = (method.upper(), path)
            actual.add(item)
            actual_details.append({"method": method.upper(), "path": path, "name": getattr(route, "name", None)})

    missing = sorted(actual - registered)
    stale = sorted(registered - actual)

    return {
        "ok": len(missing) == 0,
        "actual_count": len(actual),
        "registered_count": len(registered),
        "missing_registered_diagnostics": [{"method": method, "path": path} for method, path in missing],
        "stale_registered_diagnostics": [{"method": method, "path": path} for method, path in stale],
        "actual_routes": sorted(actual_details, key=lambda r: (r["path"], r["method"])),
        "registered_endpoints": registered_entries,
    }
