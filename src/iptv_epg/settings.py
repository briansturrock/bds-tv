from __future__ import annotations

import os
from pathlib import Path


CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/config"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DB_PATH = Path(os.getenv("DB_PATH", "/db/iptv_epg.db"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/logs"))

SOURCE_DIR = DATA_DIR / "source"
EPG_CACHE_DIR = DATA_DIR / "epg_cache"
HLS_DIR = DATA_DIR / "hls"

SOURCE_M3U = SOURCE_DIR / "source.m3u"
FILTERED_M3U = DATA_DIR / "filtered.m3u"
FILTERED_EPG = DATA_DIR / "filtered_epg.xml"


def ensure_runtime_dirs() -> None:
    for path in [
        CONFIG_DIR,
        DATA_DIR,
        DB_PATH.parent,
        LOG_DIR,
        SOURCE_DIR,
        EPG_CACHE_DIR,
        HLS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
