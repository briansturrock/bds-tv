from __future__ import annotations

from copy import deepcopy
from typing import Any


def endpoint(
    *,
    category: str,
    name: str,
    method: str,
    path: str,
    description: str,
    safe_auto_run: bool = False,
    sample_path: str | None = None,
    sample_body: dict[str, Any] | None = None,
    expected_statuses: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "name": name,
        "method": method.upper(),
        "path": path,
        "sample_path": sample_path or path,
        "description": description,
        "safe_auto_run": bool(safe_auto_run and method.upper() == "GET"),
        "sample_body": sample_body,
        "expected_statuses": expected_statuses or [200],
    }


DIAGNOSTIC_ENDPOINTS: list[dict[str, Any]] = [
    endpoint(category="Application", name="Product UI", method="GET", path="/", description="Serves the normal product UI."),
    endpoint(category="Application", name="Health", method="GET", path="/health", description="Basic app health check.", safe_auto_run=True),
    endpoint(category="Application", name="Status", method="GET", path="/api/status", description="App/source/channel status summary.", safe_auto_run=True),

    endpoint(category="Settings", name="Get settings", method="GET", path="/api/settings", description="Returns saved application settings.", safe_auto_run=True),
    endpoint(category="Settings", name="Save settings", method="POST", path="/api/settings", description="Updates application settings.", sample_body={"m3u_url": "PASTE_M3U_URL_HERE"}),

    endpoint(category="Jobs", name="List jobs", method="GET", path="/api/jobs", description="Lists recent backend jobs.", safe_auto_run=True),
    endpoint(category="Jobs", name="Get job by ID", method="GET", path="/api/jobs/{job_id}", sample_path="/api/jobs/PASTE_JOB_ID_HERE", description="Gets a single backend job.", expected_statuses=[200, 404]),

    endpoint(category="M3U", name="Get source metadata", method="GET", path="/api/source", description="Returns source M3U metadata.", safe_auto_run=True),
    endpoint(category="M3U", name="Fetch/index M3U", method="POST", path="/api/m3u/fetch", description="Starts a backend job to download and index the source M3U."),
    endpoint(category="M3U", name="Upload/import M3U", method="POST", path="/api/m3u/upload", description="Uploads a local M3U and indexes it through the same safe validation path."),
    endpoint(category="M3U", name="Generate BDS-TV M3U", method="POST", path="/api/m3u/generate-filtered", description="Starts a backend job to generate bds-tv.m3u."),
    endpoint(category="M3U", name="Open BDS-TV M3U", method="GET", path="/bds-tv.m3u", description="Returns generated bds-tv.m3u."),

    endpoint(category="Channels", name="List groups", method="GET", path="/api/groups", description="Lists channel groups.", safe_auto_run=True),
    endpoint(category="Channels", name="List channels in group", method="GET", path="/api/channels", sample_path="/api/channels?group_id=PASTE_GROUP_ID_HERE&offset=0&limit=50", description="Lists channels for one group.", expected_statuses=[200, 422]),
    endpoint(category="Channels", name="List selected channels", method="GET", path="/api/selected-channels", description="Lists currently selected channels.", safe_auto_run=True),
    endpoint(category="Channels", name="Select channels", method="POST", path="/api/channels/select", description="Selects or unselects specific channels.", sample_body={"channel_ids": ["PASTE_CHANNEL_ID_HERE"], "selected": True}),
    endpoint(category="Channels", name="Order selected channels", method="POST", path="/api/channels/order", description="Saves manual selected-channel order for one group.", sample_body={"group_id": "PASTE_GROUP_ID_HERE", "channel_ids": ["PASTE_CHANNEL_ID_HERE"]}),

    endpoint(category="Groups", name="Select group", method="POST", path="/api/groups/{group_id}/select", sample_path="/api/groups/PASTE_GROUP_ID_HERE/select", description="Selects or unselects every channel in one group.", sample_body={"selected": True}),
    endpoint(category="Groups", name="Order selected groups", method="POST", path="/api/groups/order", description="Saves manual selected-group order.", sample_body={"group_ids": ["PASTE_GROUP_ID_HERE"]}),

    endpoint(category="EPGShare", name="EPGShare status", method="GET", path="/api/epgshare/status", description="Shows EPGShare index status and indexed channel/source counts.", safe_auto_run=True),
    endpoint(category="EPGShare", name="Import EPGShare index", method="POST", path="/api/epgshare/index", description="Starts a backend job to import epg_ripper_ALL_SOURCES1.txt into SQLite."),
    endpoint(category="EPGShare", name="Search EPGShare index", method="GET", path="/api/epgshare/search", sample_path="/api/epgshare/search?q=BBC&limit=50", description="Searches the imported EPGShare channel index."),
    endpoint(category="EPGShare", name="Match selected channels against EPGShare", method="GET", path="/api/epgshare/matches", description="Matches selected IPTV channels by tvg-id against the imported EPGShare index and reports required XML.GZ files.", safe_auto_run=True),

    endpoint(category="EPGShare", name="EPGShare mapping review", method="GET", path="/api/epgshare/mapping-review", description="Returns selected IPTV channels with exact/suggested EPGShare matches and saved mapping state.", safe_auto_run=False),
    endpoint(category="EPGShare", name="List EPGShare mappings", method="GET", path="/api/epgshare/mappings", description="Lists saved EPGShare channel mappings.", safe_auto_run=False),
    endpoint(category="EPGShare", name="Save EPGShare mappings", method="POST", path="/api/epgshare/mappings", description="Saves reviewed EPGShare mappings or ignored channels.", sample_body={"mappings":[{"channel_id":"PASTE_CHANNEL_ID_HERE","xmltv_id":"PASTE_XMLTV_ID_HERE","source_key":"PASTE_SOURCE_KEY_HERE","mapping_type":"manual","confidence":1.0}]}),
    endpoint(category="EPGShare", name="EPGShare matching review UI", method="GET", path="/dev/epgshare-matching", description="Developer UI for reviewing and saving EPGShare channel mappings.", safe_auto_run=False),

    endpoint(category="EPGShare", name="Generate EPGShare XMLTV", method="POST", path="/api/epgshare/generate-filtered", sample_path="/api/epgshare/generate-filtered?days=3", description="Generates bds-tv.xml from saved EPGShare mappings only."),
    endpoint(category="EPGShare", name="Open BDS-TV XMLTV", method="GET", path="/bds-tv.xml", description="Returns generated bds-tv.xml."),

    endpoint(category="Guide", name="Guide groups", method="GET", path="/api/guide/groups", description="Lists only groups that contain selected channels.", safe_auto_run=True),
    endpoint(category="Guide", name="Guide for group", method="GET", path="/api/guide", sample_path="/api/guide?group_id=PASTE_GROUP_ID_HERE", description="Returns selected channels and programme data for one selected group.", safe_auto_run=False),
    endpoint(category="Guide", name="Guide dates", method="GET", path="/api/guide/dates", description="Lists available guide dates from the generated filtered EPG for selected channels.", safe_auto_run=True),
    endpoint(category="Guide Streaming", name="Watch channel preview", method="GET", path="/watch/{channel_id}", sample_path="/watch/PASTE_CHANNEL_ID_HERE", description="Opens the browser preview player for one selected channel.", expected_statuses=[200, 404]),
    endpoint(category="Guide Streaming", name="HLS playlist", method="GET", path="/hls/{channel_id}/{mode}/index.m3u8", sample_path="/hls/PASTE_CHANNEL_ID_HERE/copy/index.m3u8", description="Starts or returns the local HLS preview playlist.", expected_statuses=[200, 404, 504]),
    endpoint(category="Guide Streaming", name="HLS segment", method="GET", path="/hls/{channel_id}/{mode}/{segment_name}", sample_path="/hls/PASTE_CHANNEL_ID_HERE/copy/seg_00000.ts", description="Returns one generated HLS preview segment.", expected_statuses=[200, 404]),
    endpoint(category="Guide Streaming", name="Stop HLS preview", method="POST", path="/api/hls/{channel_id}/{mode}/stop", sample_path="/api/hls/PASTE_CHANNEL_ID_HERE/copy/stop", description="Stops the FFmpeg process for a channel preview.", expected_statuses=[200]),
    endpoint(category="Guide Streaming", name="Raw stream proxy", method="GET", path="/stream/{channel_id}", sample_path="/stream/PASTE_CHANNEL_ID_HERE", description="Proxies a selected channel stream directly through the app.", expected_statuses=[200, 404, 502]),

    endpoint(category="HDHR", name="HDHR settings", method="GET", path="/api/hdhr/settings", description="Returns HDHomeRun emulation settings and stream status.", safe_auto_run=True),
    endpoint(category="HDHR", name="Save HDHR settings", method="POST", path="/api/hdhr/settings", description="Saves HDHomeRun emulation settings.", sample_body={"enabled": False, "device_name": "bds-tv", "device_id": "12345678", "channel_limit": 450, "excluded_group_ids": [], "tuner_count": 1, "max_upstream_streams": 1, "public_base_url": "http://192.168.0.185:8088", "stream_mode": "direct", "conflict_policy": "reject_new", "ffmpeg_path": "ffmpeg", "buffer_seconds": 30, "buffer_max_mb": 256, "stream_cleanup_enabled": True, "max_stream_age_minutes": 240, "idle_timeout_seconds": 120, "cleanup_interval_seconds": 30, "scheduled_drop_enabled": False, "scheduled_drop_time": "04:00"}),
    endpoint(category="HDHR", name="Generate HDHR proxy M3U", method="POST", path="/api/hdhr/generate-m3u", description="Generates an optional proxy M3U with local stream URLs."),
    endpoint(category="HDHR", name="HDHR status", method="GET", path="/api/hdhr/status", description="Returns active HDHR proxy streams.", safe_auto_run=True),
    endpoint(category="HDHR", name="HDHR catalogue", method="GET", path="/api/hdhr/catalogue", description="Returns the selected channel catalogue with DLNA-ready group containers.", safe_auto_run=True),
    endpoint(category="HDHR", name="Stop HDHR streams", method="POST", path="/api/hdhr/streams/stop", description="Stops all active HDHR proxy streams."),
    endpoint(category="HDHR", name="HDHR discover.json", method="GET", path="/discover.json", description="Returns HDHomeRun discovery metadata.", safe_auto_run=True),
    endpoint(category="HDHR", name="HDHR lineup.json", method="GET", path="/lineup.json", description="Returns selected channels as an HDHomeRun lineup.", safe_auto_run=True),
    endpoint(category="HDHR", name="HDHR lineup status", method="GET", path="/lineup_status.json", description="Returns HDHomeRun lineup scan status.", safe_auto_run=True),
    endpoint(category="HDHR", name="HDHR proxy M3U", method="GET", path="/hdhr.m3u", description="Returns the optional generated proxy M3U."),
    endpoint(category="HDHR", name="HDHR XMLTV", method="GET", path="/hdhr_epg.xml", description="Returns XMLTV with channel IDs rewritten to HDHR lineup numbers."),
    endpoint(category="HDHR", name="HDHR channel stream", method="GET", path="/hdhr/channel/{channel_id}", sample_path="/hdhr/channel/PASTE_CHANNEL_ID_HERE", description="Streams one selected channel through the HDHR proxy.", expected_statuses=[200, 403, 404, 409, 502]),
    endpoint(category="HDHR", name="HDHR auto stream", method="GET", path="/auto/v{guide_number}", sample_path="/auto/v1", description="HDHomeRun channel stream URL by lineup number.", expected_statuses=[200, 403, 404, 409, 502]),

    endpoint(category="DLNA", name="DLNA settings", method="GET", path="/api/dlna/settings", description="Returns DLNA media server settings and dynamic catalogue counts.", safe_auto_run=True),
    endpoint(category="DLNA", name="Save DLNA settings", method="POST", path="/api/dlna/settings", description="Saves DLNA media server settings.", sample_body={"enabled": True, "device_name": "bds-tv DLNA", "public_base_url": "http://192.168.0.185:8088", "stream_mode": "copy"}),
    endpoint(category="DLNA", name="DLNA request log", method="GET", path="/api/dlna/requests", description="Returns recent DLNA browse and stream requests for TV troubleshooting.", safe_auto_run=True),
    endpoint(category="DLNA", name="Clear DLNA request log", method="DELETE", path="/api/dlna/requests", description="Clears the in-memory DLNA troubleshooting request log."),
    endpoint(category="DLNA", name="DLNA device description", method="GET", path="/dlna/device.xml", description="Returns the UPnP/DLNA MediaServer device description.", safe_auto_run=True),
    endpoint(category="DLNA", name="DLNA ContentDirectory SCPD", method="GET", path="/dlna/content-directory.xml", description="Returns the ContentDirectory service description.", safe_auto_run=True),
    endpoint(category="DLNA", name="DLNA ConnectionManager SCPD", method="GET", path="/dlna/connection-manager.xml", description="Returns the ConnectionManager service description.", safe_auto_run=True),
    endpoint(category="DLNA", name="DLNA channel stream", method="GET", path="/dlna/channel/{channel_id}", sample_path="/dlna/channel/PASTE_CHANNEL_ID_HERE", description="Streams one selected channel through the shared proxy for DLNA clients.", expected_statuses=[200, 404, 409, 502]),
    endpoint(category="DLNA", name="DLNA channel MPG stream", method="GET", path="/dlna/channel/{channel_id}.mpg", sample_path="/dlna/channel/PASTE_CHANNEL_ID_HERE.mpg", description="Streams one selected channel through a TV-friendly MPEG file URL.", expected_statuses=[200, 404, 409, 502]),
    endpoint(category="DLNA", name="DLNA channel stream HEAD", method="HEAD", path="/dlna/channel/{channel_id}.mpg", sample_path="/dlna/channel/PASTE_CHANNEL_ID_HERE.mpg", description="Lets strict DLNA clients validate stream headers without opening the upstream provider stream.", expected_statuses=[200, 404]),
    endpoint(category="TV App", name="TV app channel stream", method="GET", path="/tv/stream/{channel_id}.mpg", sample_path="/tv/stream/PASTE_CHANNEL_ID_HERE.mpg", description="Streams one selected channel through the bds-tv proxy for the Samsung TV app.", expected_statuses=[200, 403, 404, 409, 502]),

    endpoint(category="Scheduler", name="Scheduler settings", method="GET", path="/api/scheduler", description="Returns scheduler settings and last scheduled EPG job.", safe_auto_run=True),
    endpoint(category="Scheduler", name="Save scheduler settings", method="POST", path="/api/scheduler", description="Saves the scheduled EPG generation settings.", sample_body={"enabled": True, "days": 5, "run_time": "04:00"}),
    endpoint(category="Scheduler", name="Run scheduler now", method="POST", path="/api/scheduler/run-now", description="Starts scheduled EPG generation immediately.", expected_statuses=[200, 409]),


    endpoint(category="TV App", name="TV App settings", method="GET", path="/api/tv-app/settings", description="Returns saved Samsung TV app signing and deploy settings.", safe_auto_run=True),
    endpoint(category="TV App", name="Save TV App settings", method="POST", path="/api/tv-app/settings", description="Stores local TV app signing and deploy settings in the database.", sample_body={"author_p12_name":"author.p12","author_p12_data":"BASE64_P12","distributor_p12_name":"distributor.p12","distributor_p12_data":"BASE64_P12","cert_password":"PASSWORD","manual_tv_ip":"192.168.0.92","remove_old_version":True,"launch_after_install":False}),
    endpoint(category="TV App", name="Discover Samsung TVs", method="POST", path="/api/tv-app/discover", description="Scans the LAN and optional manual IP for Samsung TVs with TV API or Tizen developer port open.", sample_body={"manual_tv_ip":"192.168.0.92","include_manual":True}),
    endpoint(category="TV App", name="Build TV App WGT", method="POST", path="/api/tv-app/package", description="Builds the current hosted Tizen shell as a WGT package."),
    endpoint(category="TV App", name="Download TizenSDB", method="POST", path="/api/tv-app/sdb", description="Downloads or updates the Linux TizenSDB wrapper used for TV app signing and installation.", expected_statuses=[200, 502], sample_body={"force":True}),
    endpoint(category="TV App", name="Download TV App WGT", method="GET", path="/api/tv-app/package/download", description="Downloads the latest built TV App WGT package."),
    endpoint(category="TV App", name="Install TV App WGT", method="POST", path="/api/tv-app/install", description="Installs the TV App WGT on a selected developer-mode Samsung TV when SDB is available.", expected_statuses=[200, 409], sample_body={"tv_ip":"192.168.0.92","remove_old_version":True,"launch_after_install":False}),
    endpoint(category="Diagnostics", name="Diagnostics console", method="GET", path="/dev/diagnostics", description="Serves this diagnostics console."),
    endpoint(category="Diagnostics", name="Diagnostics endpoint registry", method="GET", path="/dev/diagnostics/endpoints", description="Returns registered diagnostics endpoint definitions.", safe_auto_run=True),
    endpoint(category="Diagnostics", name="Diagnostics coverage", method="GET", path="/dev/diagnostics/coverage", description="Compares actual FastAPI routes with registered diagnostics entries.", safe_auto_run=True),
]


def get_diagnostic_endpoints() -> list[dict[str, Any]]:
    return deepcopy(DIAGNOSTIC_ENDPOINTS)
