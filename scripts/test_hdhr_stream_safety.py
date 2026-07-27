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


fastapi = types.ModuleType("fastapi")
fastapi.APIRouter = lambda *args, **kwargs: _DummyRouter()
fastapi.HTTPException = Exception
fastapi.Request = object
sys.modules.setdefault("fastapi", fastapi)

responses = types.ModuleType("fastapi.responses")
responses.FileResponse = object
responses.JSONResponse = object
responses.PlainTextResponse = object
responses.StreamingResponse = object
sys.modules.setdefault("fastapi.responses", responses)

pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = object
pydantic.Field = lambda default=None, **_kwargs: default
sys.modules.setdefault("pydantic", pydantic)

sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg import hdhr  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def settings(**overrides):
    values = {
        "enabled": True,
        "device_name": "bds-tv",
        "device_id": "12345678",
        "channel_limit": 450,
        "tuner_count": 1,
        "max_upstream_streams": 1,
        "public_base_url": "http://example",
        "stream_mode": "ffmpeg",
        "conflict_policy": "reject_new",
        "ffmpeg_path": "ffmpeg",
        "stream_cleanup_enabled": True,
        "max_stream_age_minutes": 240,
        "idle_timeout_seconds": 120,
        "cleanup_interval_seconds": 30,
        "scheduled_drop_enabled": False,
        "scheduled_drop_time": "04:00",
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


def session(session_id: str, started_at: float, last_activity_at: float):
    return hdhr.StreamSession(
        session_id=session_id,
        channel_id="abc",
        channel_name="ABC",
        mode="ffmpeg",
        started_at=started_at,
        last_activity_at=last_activity_at,
    )


def main() -> None:
    original_time = hdhr.time.time
    original_localtime = hdhr.time.localtime
    original_strftime = hdhr.time.strftime
    original_streams = hdhr.ACTIVE_STREAMS
    try:
        hdhr.ACTIVE_STREAMS = {"idle": session("idle", 1_000, 1_000)}
        hdhr.time.time = lambda: 1_200
        hdhr.stream_safety_cleanup(settings(idle_timeout_seconds=120))
        check(hdhr.ACTIVE_STREAMS == {}, "idle stream should be stopped")

        hdhr.ACTIVE_STREAMS = {"old": session("old", 1_000, 1_100)}
        hdhr.time.time = lambda: 1_301
        hdhr.stream_safety_cleanup(settings(max_stream_age_minutes=5, idle_timeout_seconds=0))
        check(hdhr.ACTIVE_STREAMS == {}, "over-age stream should be stopped")

        fake_now = types.SimpleNamespace(tm_hour=4, tm_min=0)
        hdhr.time.localtime = lambda: fake_now

        def fake_strftime(fmt, _value=None):
            if fmt == "%Y-%m-%d":
                return "2026-07-14"
            if fmt == "%H:%M":
                return "04:00"
            return "2026-07-14T04:00:00Z"

        hdhr.time.strftime = fake_strftime
        due, day = hdhr.scheduled_drop_due(settings(scheduled_drop_enabled=True), None)
        check(due and day == "2026-07-14", "scheduled drop should fire at configured time")
        due_again, _day_again = hdhr.scheduled_drop_due(settings(scheduled_drop_enabled=True), day)
        check(not due_again, "scheduled drop should only fire once per day")
    finally:
        hdhr.ACTIVE_STREAMS = original_streams
        hdhr.time.time = original_time
        hdhr.time.localtime = original_localtime
        hdhr.time.strftime = original_strftime


if __name__ == "__main__":
    main()
