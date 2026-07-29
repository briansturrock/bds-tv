from pathlib import Path
import sys
import types
from tempfile import TemporaryDirectory

sys.modules.setdefault("requests", types.SimpleNamespace())

from iptv_epg.m3u import InvalidM3UError, parse_m3u_file, validate_m3u_file


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


with TemporaryDirectory() as tmpdir:
    root = Path(tmpdir)
    good = root / "good.m3u"
    empty = root / "empty.m3u"
    invalid = root / "invalid.m3u"
    zero_channels = root / "zero_channels.m3u"

    write(
        good,
        '#EXTM3U\n#EXTINF:-1 tvg-id="BBC1.uk" group-title="UK| GENERAL",UK| BBC 1 HD\nhttp://example/stream\n',
    )
    write(empty, "")
    write(invalid, "<html>not a playlist</html>\n")
    write(zero_channels, "#EXTM3U\n#EXTGRP:Nothing\n")

    assert validate_m3u_file(good)["channel_count"] == 1
    assert len(list(parse_m3u_file(good))) == 1

    for path in (empty, invalid, zero_channels):
        try:
            validate_m3u_file(path)
        except InvalidM3UError:
            pass
        else:
            raise AssertionError(f"{path.name} should have failed validation")

print("m3u safe refresh checks passed")
