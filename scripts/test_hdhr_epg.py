from __future__ import annotations

from datetime import datetime, timezone
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
responses.PlainTextResponse = object
responses.StreamingResponse = object
sys.modules.setdefault("fastapi.responses", responses)

pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = object
pydantic.Field = lambda default=None, **_kwargs: default
sys.modules.setdefault("pydantic", pydantic)

sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg.hdhr import unknown_programmes_for_channel, xmltv_time  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    timestamp = datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc)
    check(xmltv_time(timestamp) == "20260714123000 +0000", "XMLTV timestamp formatting failed")

    programmes = list(unknown_programmes_for_channel(124, days=1))
    check(len(programmes) == 4, "expected four six-hour Unknown blocks for one day")
    check(all(programme.get("channel") == "124" for programme in programmes), "channel number not preserved")
    check(all(programme.findtext("title") == "Unknown" for programme in programmes), "Unknown title missing")
    check(programmes[0].get("stop") == programmes[1].get("start"), "Unknown blocks are not contiguous")


if __name__ == "__main__":
    main()
