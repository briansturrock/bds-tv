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
        check('id="group:1"' in root and 'id="group:2"' in root, "DLNA root should contain TV-safe group IDs")

        metadata, returned, total = dlna.browse_result("group:1", "http://example", browse_flag="BrowseMetadata")
        check(returned == 1 and total == 1 and "UK" in metadata, "DLNA group metadata should describe the selected folder")

        uk, returned, total = dlna.browse_result("group%3A1", "http://example")
        check(returned == 2 and total == 2, "DLNA group should expose its channels")
        check("BBC One" in uk and "BBC Two" in uk, "DLNA group should include channel titles")
        check("http://example/dlna/channel/bbc1.mpg" in uk, "DLNA channel URL should look like a TV-playable MPEG file")
        check("video/vnd.dlna.mpeg-tts" in uk, "DLNA channel should advertise MPEG-TS video protocol info")

        legacy, returned, total = dlna.browse_result("group:uk", "http://example")
        check(returned == 2 and total == 2 and "BBC One" in legacy, "legacy raw group IDs should still browse")

        paged, returned, total = dlna.browse_result("group:1", "http://example", starting_index=1, requested_count=1)
        check(returned == 1 and total == 2, "DLNA browse paging should report returned and total counts")
        check("BBC Two" in paged and "BBC One" not in paged, "DLNA browse paging should return the requested slice")

        command = dlna.dlna_transcode_command("http://upstream", "ffmpeg")
        check("libx264" in command and "aac" in command, "DLNA transcode command should target TV-compatible codecs")
        check(command[-2:] == ["mpegts", "pipe:1"], "DLNA transcode command should stream MPEG-TS to stdout")
        check(dlna.DLNA_STREAM_HEADERS["Accept-Ranges"] == "none", "DLNA streams should advertise non-seekable live output")
        check(dlna.DLNA_STREAM_HEADERS["Connection"] == "close", "DLNA streams should use TV-friendly connection headers")
    finally:
        dlna.selected_catalogue_channels = original


if __name__ == "__main__":
    main()
