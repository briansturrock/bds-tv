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


def main() -> None:
    original = hdhr.get_selected_channels
    try:
        hdhr.get_selected_channels = lambda: [
            {"id": "a", "name": "A", "tvg_id": "A.tv", "group_id": "g1", "group_name": "Group 1", "stream_url": "http://a"},
            {"id": "b", "name": "B", "tvg_id": "B.tv", "group_id": "skip", "group_name": "Skip", "stream_url": "http://b"},
            {"id": "c", "name": "C", "tvg_id": "C.tv", "group_id": "g2", "group_name": "Group 2", "stream_url": "http://c"},
            {"id": "d", "name": "D", "tvg_id": "D.tv", "group_id": "g2", "group_name": "Group 2", "stream_url": "http://d"},
        ]
        channels = hdhr.selected_catalogue_channels(limit=2)
        check([channel["number"] for channel in channels] == [1, 2], "limited channel numbers should be contiguous")
        check([channel["channel_id"] for channel in channels] == ["a", "b"], "channel limit should keep the first selected channels")
        filtered = hdhr.selected_catalogue_channels(limit=2, excluded_group_ids={"skip"})
        check([channel["channel_id"] for channel in filtered] == ["a", "c"], "excluded groups should be removed before HDHR limit")
        check([channel["number"] for channel in filtered] == [1, 2], "filtered channel numbers should stay contiguous")
        rows = hdhr.lineup_rows("http://example", types.SimpleNamespace(channel_limit=2, excluded_group_ids=["skip"]))
        check([row["GuideNumber"] for row in rows] == ["1", "2"], "lineup should respect the channel limit")
        check(rows[-1]["URL"] == "http://example/auto/v2", "lineup URL should use limited numbering")
    finally:
        hdhr.get_selected_channels = original


if __name__ == "__main__":
    main()
