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
responses.Response = object
responses.StreamingResponse = object
sys.modules.setdefault("fastapi.responses", responses)

pydantic = types.ModuleType("pydantic")
pydantic.BaseModel = object
pydantic.Field = lambda default=None, **_kwargs: default
sys.modules.setdefault("pydantic", pydantic)

sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg import dlna  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    original = dlna.selected_catalogue_channels
    try:
        dlna.selected_catalogue_channels = lambda limit=None: [
            {"channel_id": "bbc1", "name": "BBC One", "group_id": "uk", "group_name": "UK", "logo_url": ""},
            {"channel_id": "bbc2", "name": "BBC Two", "group_id": "uk", "group_name": "UK", "logo_url": ""},
            {"channel_id": "cnn", "name": "CNN", "group_id": "news", "group_name": "News", "logo_url": ""},
        ]

        root, returned, total = dlna.browse_result("0", "http://example")
        check(returned == 2 and total == 2, "DLNA root should expose group containers")
        check('id="group:uk"' in root and 'id="group:news"' in root, "DLNA root should contain group IDs")

        uk, returned, total = dlna.browse_result("group:uk", "http://example")
        check(returned == 2 and total == 2, "DLNA group should expose its channels")
        check("BBC One" in uk and "BBC Two" in uk, "DLNA group should include channel titles")
        check("http://example/dlna/channel/bbc1" in uk, "DLNA channel URL should use the local stream endpoint")

        paged, returned, total = dlna.browse_result("group:uk", "http://example", starting_index=1, requested_count=1)
        check(returned == 1 and total == 2, "DLNA browse paging should report returned and total counts")
        check("BBC Two" in paged and "BBC One" not in paged, "DLNA browse paging should return the requested slice")
    finally:
        dlna.selected_catalogue_channels = original


if __name__ == "__main__":
    main()
