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
    endpoint(category="M3U", name="Generate filtered M3U", method="POST", path="/api/m3u/generate-filtered", description="Starts a backend job to generate filtered.m3u."),
    endpoint(category="M3U", name="Open filtered M3U", method="GET", path="/filtered.m3u", description="Returns generated filtered.m3u."),

    endpoint(category="Channels", name="List groups", method="GET", path="/api/groups", description="Lists channel groups.", safe_auto_run=True),
    endpoint(category="Channels", name="List channels in group", method="GET", path="/api/channels", sample_path="/api/channels?group_id=PASTE_GROUP_ID_HERE&offset=0&limit=50", description="Lists channels for one group.", expected_statuses=[200, 422]),
    endpoint(category="Channels", name="List selected channels", method="GET", path="/api/selected-channels", description="Lists currently selected channels.", safe_auto_run=True),
    endpoint(category="Channels", name="Select channels", method="POST", path="/api/channels/select", description="Selects or unselects specific channels.", sample_body={"channel_ids": ["PASTE_CHANNEL_ID_HERE"], "selected": True}),
    endpoint(category="Channels", name="Order selected channels", method="POST", path="/api/channels/order", description="Saves manual selected-channel order for one group.", sample_body={"group_id": "PASTE_GROUP_ID_HERE", "channel_ids": ["PASTE_CHANNEL_ID_HERE"]}),

    endpoint(category="Groups", name="Select group", method="POST", path="/api/groups/{group_id}/select", sample_path="/api/groups/PASTE_GROUP_ID_HERE/select", description="Selects or unselects every channel in one group.", sample_body={"selected": True}),
    endpoint(category="Groups", name="Order selected groups", method="POST", path="/api/groups/order", description="Saves manual selected-group order.", sample_body={"group_ids": ["PASTE_GROUP_ID_HERE"]}),

    endpoint(category="EPG", name="List EPG sources", method="GET", path="/api/epg/sources", description="Lists configured EPG sources.", safe_auto_run=True),
    endpoint(category="EPG", name="Add EPG source", method="POST", path="/api/epg/sources", description="Adds an EPG source.", sample_body={"name": "Manual XMLTV", "url": "https://example.com/epg.xml", "enabled": True, "source_type": "manual"}),
    endpoint(category="EPG", name="Enable EPG source", method="POST", path="/api/epg/sources/{source_id}/enable", sample_path="/api/epg/sources/1/enable", description="Enables or disables an EPG source.", sample_body={"enabled": True}),
    endpoint(category="EPG", name="Detect EPG sources", method="POST", path="/api/epg/detect", description="Attempts to detect EPG sources from the configured M3U/source."),
    endpoint(category="EPG", name="Test EPG source", method="POST", path="/api/epg/test", description="Starts a backend EPG source test job."),
    endpoint(category="EPG", name="Search EPG channels", method="GET", path="/api/epg/channels/search", sample_path="/api/epg/channels/search?q=bbc&limit=50", description="Searches scanned EPG channels."),
    endpoint(category="EPG", name="Get EPG mappings", method="GET", path="/api/epg/mappings", description="Lists selected IPTV channels and their EPG mappings.", safe_auto_run=True),
    endpoint(category="EPG", name="Save EPG mappings", method="POST", path="/api/epg/mappings", description="Saves manual EPG mappings.", sample_body={"mappings": [{"channel_id": "PASTE_CHANNEL_ID_HERE", "source_id": 1, "xmltv_id": "PASTE_XMLTV_ID_HERE", "mapping_type": "manual"}]}),
    endpoint(category="EPG", name="Generate filtered EPG", method="POST", path="/api/epg/generate-filtered", sample_path="/api/epg/generate-filtered?days=3", description="Starts a backend job to generate filtered_epg.xml."),
    endpoint(category="EPG", name="Open filtered EPG", method="GET", path="/filtered_epg.xml", description="Returns generated filtered_epg.xml."),

    endpoint(category="EPGShare", name="EPGShare status", method="GET", path="/api/epgshare/status", description="Shows EPGShare index status and indexed channel/source counts.", safe_auto_run=True),
    endpoint(category="EPGShare", name="Import EPGShare index", method="POST", path="/api/epgshare/index", description="Starts a backend job to import epg_ripper_ALL_SOURCES1.txt into SQLite."),
    endpoint(category="EPGShare", name="Search EPGShare index", method="GET", path="/api/epgshare/search", sample_path="/api/epgshare/search?q=BBC&limit=50", description="Searches the imported EPGShare channel index."),
    endpoint(category="EPGShare", name="Match selected channels against EPGShare", method="GET", path="/api/epgshare/matches", description="Matches selected IPTV channels by tvg-id against the imported EPGShare index and reports required XML.GZ files.", safe_auto_run=True),

    endpoint(category="EPGShare", name="EPGShare mapping review", method="GET", path="/api/epgshare/mapping-review", description="Returns selected IPTV channels with exact/suggested EPGShare matches and saved mapping state.", safe_auto_run=False),
    endpoint(category="EPGShare", name="List EPGShare mappings", method="GET", path="/api/epgshare/mappings", description="Lists saved EPGShare channel mappings.", safe_auto_run=False),
    endpoint(category="EPGShare", name="Save EPGShare mappings", method="POST", path="/api/epgshare/mappings", description="Saves reviewed EPGShare mappings or ignored channels.", sample_body={"mappings":[{"channel_id":"PASTE_CHANNEL_ID_HERE","xmltv_id":"PASTE_XMLTV_ID_HERE","source_key":"PASTE_SOURCE_KEY_HERE","mapping_type":"manual","confidence":1.0}]}),
    endpoint(category="EPGShare", name="EPGShare matching review UI", method="GET", path="/dev/epgshare-matching", description="Developer UI for reviewing and saving EPGShare channel mappings.", safe_auto_run=False),

    endpoint(category="EPGShare", name="Generate EPGShare filtered EPG", method="POST", path="/api/epgshare/generate-filtered", sample_path="/api/epgshare/generate-filtered?days=3", description="Generates filtered_epg.xml from saved EPGShare mappings only."),

    endpoint(category="Guide", name="Guide groups", method="GET", path="/api/guide/groups", description="Lists only groups that contain selected channels.", safe_auto_run=True),
    endpoint(category="Guide", name="Guide for group", method="GET", path="/api/guide", sample_path="/api/guide?group_id=PASTE_GROUP_ID_HERE", description="Returns selected channels and programme data for one selected group.", safe_auto_run=False),
    endpoint(category="Guide", name="Guide dates", method="GET", path="/api/guide/dates", description="Lists available guide dates from the generated filtered EPG for selected channels.", safe_auto_run=True),
    endpoint(category="Guide Streaming", name="Watch channel preview", method="GET", path="/watch/{channel_id}", sample_path="/watch/PASTE_CHANNEL_ID_HERE", description="Opens the browser preview player for one selected channel.", expected_statuses=[200, 404]),
    endpoint(category="Guide Streaming", name="HLS playlist", method="GET", path="/hls/{channel_id}/{mode}/index.m3u8", sample_path="/hls/PASTE_CHANNEL_ID_HERE/copy/index.m3u8", description="Starts or returns the local HLS preview playlist.", expected_statuses=[200, 404, 504]),
    endpoint(category="Guide Streaming", name="HLS segment", method="GET", path="/hls/{channel_id}/{mode}/{segment_name}", sample_path="/hls/PASTE_CHANNEL_ID_HERE/copy/seg_00000.ts", description="Returns one generated HLS preview segment.", expected_statuses=[200, 404]),
    endpoint(category="Guide Streaming", name="Stop HLS preview", method="POST", path="/api/hls/{channel_id}/{mode}/stop", sample_path="/api/hls/PASTE_CHANNEL_ID_HERE/copy/stop", description="Stops the FFmpeg process for a channel preview.", expected_statuses=[200]),
    endpoint(category="Guide Streaming", name="Raw stream proxy", method="GET", path="/stream/{channel_id}", sample_path="/stream/PASTE_CHANNEL_ID_HERE", description="Proxies a selected channel stream directly through the app.", expected_statuses=[200, 404, 502]),

    endpoint(category="Scheduler", name="Scheduler settings", method="GET", path="/api/scheduler", description="Returns scheduler settings and last scheduled EPG job.", safe_auto_run=True),
    endpoint(category="Scheduler", name="Save scheduler settings", method="POST", path="/api/scheduler", description="Saves the scheduled EPG generation settings.", sample_body={"enabled": True, "days": 5, "run_time": "04:00"}),
    endpoint(category="Scheduler", name="Run scheduler now", method="POST", path="/api/scheduler/run-now", description="Starts scheduled EPG generation immediately.", expected_statuses=[200, 409]),

    endpoint(category="Diagnostics", name="Diagnostics console", method="GET", path="/dev/diagnostics", description="Serves this diagnostics console."),
    endpoint(category="Diagnostics", name="Diagnostics endpoint registry", method="GET", path="/dev/diagnostics/endpoints", description="Returns registered diagnostics endpoint definitions.", safe_auto_run=True),
    endpoint(category="Diagnostics", name="Diagnostics coverage", method="GET", path="/dev/diagnostics/coverage", description="Compares actual FastAPI routes with registered diagnostics entries.", safe_auto_run=True),
]


def get_diagnostic_endpoints() -> list[dict[str, Any]]:
    return deepcopy(DIAGNOSTIC_ENDPOINTS)
