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


class FakeStdout:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def read(self, _size: int) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class FakeProcess:
    def __init__(self, chunks: list[bytes]):
        self.stdout = FakeStdout(chunks)
        self.stopped = False

    def poll(self):
        return None if not self.stopped else 0

    def terminate(self) -> None:
        self.stopped = True

    def wait(self, timeout=None) -> int:
        self.stopped = True
        return 0

    def kill(self) -> None:
        self.stopped = True


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    now = hdhr.time.time()
    session = hdhr.StreamSession(
        session_id="buffered",
        channel_id="abc",
        channel_name="ABC",
        mode="buffered",
        started_at=now,
        last_activity_at=now,
        buffer_target_seconds=0,
        process=FakeProcess([b"one", b"two", b"three"]),
    )

    original_streams = hdhr.ACTIVE_STREAMS
    try:
        hdhr.ACTIVE_STREAMS = {session.session_id: session}
        output = b"".join(hdhr.buffered_ffmpeg_stream_iterator(session, buffer_seconds=0, buffer_max_mb=16))
        check(output == b"onetwothree", "buffered iterator should yield all ffmpeg chunks")
        check(hdhr.ACTIVE_STREAMS == {}, "buffered iterator should release the stream session")
        check(session.bytes_sent == 11, "buffered iterator should record bytes sent")
        check(session.buffer_bytes == 0, "buffer should be empty after stream ends")
    finally:
        hdhr.ACTIVE_STREAMS = original_streams


if __name__ == "__main__":
    main()
