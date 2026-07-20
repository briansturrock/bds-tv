from __future__ import annotations

from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class _DummyRouter:
    def get(self, *_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    post = get
    head = get
    delete = get


fastapi = types.ModuleType("fastapi")
fastapi.APIRouter = lambda *args, **kwargs: _DummyRouter()
fastapi.HTTPException = Exception
fastapi.Request = object
sys.modules.setdefault("fastapi", fastapi)

responses = types.ModuleType("fastapi.responses")
responses.FileResponse = object
responses.JSONResponse = object
responses.PlainTextResponse = object
responses.Response = object
responses.StreamingResponse = object
sys.modules.setdefault("fastapi.responses", responses)

pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = object
pydantic.Field = lambda default=None, **_kwargs: default
sys.modules.setdefault("pydantic", pydantic)

sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg import dlna, hdhr  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    hdhr_settings = {
        "hdhr_enabled": "true",
        "hdhr_device_name": "Snapshot HDHR",
        "hdhr_device_id": "ABCDEF12",
        "hdhr_channel_limit": "321",
        "hdhr_excluded_group_ids": '["skip"]',
        "hdhr_tuner_count": "2",
        "hdhr_max_upstream_streams": "2",
        "hdhr_public_base_url": "http://example.test:8088/",
        "hdhr_stream_mode": "buffered",
        "hdhr_conflict_policy": "stop_existing",
        "hdhr_ffmpeg_path": "/usr/bin/ffmpeg",
        "hdhr_buffer_seconds": "12",
        "hdhr_buffer_max_mb": "64",
        "hdhr_stream_cleanup_enabled": "true",
        "hdhr_max_stream_age_minutes": "99",
        "hdhr_idle_timeout_seconds": "45",
        "hdhr_cleanup_interval_seconds": "10",
        "hdhr_scheduled_drop_enabled": "true",
        "hdhr_scheduled_drop_time": "03:30",
    }

    original_hdhr_get_settings = hdhr.get_settings
    original_hdhr_get_setting = hdhr.get_setting
    original_hdhr_set_setting = hdhr.set_setting
    hdhr_calls: list[tuple[str, ...]] = []
    try:
        hdhr.get_settings = lambda keys: hdhr_calls.append(tuple(keys)) or dict(hdhr_settings)
        hdhr.get_setting = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("HDHR used per-key get_setting"))
        hdhr.set_setting = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("HDHR unexpectedly wrote settings"))

        settings = hdhr.get_hdhr_settings()
        check(len(hdhr_calls) == 1, "HDHR settings should be loaded with one bulk read")
        check(settings.device_name == "Snapshot HDHR", "HDHR should parse device name from snapshot")
        check(settings.channel_limit == 321, "HDHR should parse integer settings from snapshot")
        check(settings.excluded_group_ids == ["skip"], "HDHR should parse list settings from snapshot")
        check(settings.public_base_url == "http://example.test:8088", "HDHR should normalise base URL from snapshot")
        check(settings.stream_mode == "buffered", "HDHR should parse stream mode from snapshot")
    finally:
        hdhr.get_settings = original_hdhr_get_settings
        hdhr.get_setting = original_hdhr_get_setting
        hdhr.set_setting = original_hdhr_set_setting

    dlna_settings = {
        **hdhr_settings,
        "dlna_enabled": "true",
        "dlna_device_name": "Snapshot DLNA",
        "dlna_public_base_url": "",
        "dlna_stream_mode": "transcode",
    }

    original_dlna_get_settings = dlna.get_settings
    original_dlna_get_setting = dlna.get_setting
    original_hdhr_get_settings = hdhr.get_settings
    dlna_calls: list[tuple[str, ...]] = []
    try:
        dlna.get_settings = lambda keys: dlna_calls.append(tuple(keys)) or dict(dlna_settings)
        dlna.get_setting = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DLNA used per-key get_setting"))
        hdhr.get_settings = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("DLNA caused HDHR to do its own bulk read"))

        settings = dlna.get_dlna_settings()
        check(len(dlna_calls) == 1, "DLNA settings should be loaded with one combined bulk read")
        check(settings.device_name == "Snapshot DLNA", "DLNA should parse device name from snapshot")
        check(settings.public_base_url == "http://example.test:8088", "DLNA should inherit HDHR base URL from same snapshot")
        check(settings.stream_mode == "transcode", "DLNA should parse stream mode from snapshot")
    finally:
        dlna.get_settings = original_dlna_get_settings
        dlna.get_setting = original_dlna_get_setting
        hdhr.get_settings = original_hdhr_get_settings


if __name__ == "__main__":
    main()
