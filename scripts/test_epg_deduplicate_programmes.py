from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from iptv_epg import epgshare


def test_generate_filtered_epgshare_deduplicates_upstream_programmes(tmp_path: Path) -> None:
    source_xml = tmp_path / "source.xml.gz"
    output_xml = tmp_path / "bds-tv.xml"

    duplicate_programme = """
    <programme channel="Global.Toronto.HD.ca2" start="20260730130000 +0000" stop="20260730140000 +0000">
      <title lang="en">The Morning Show</title>
    </programme>
    """
    with gzip.open(source_xml, "wt", encoding="utf-8") as handle:
        handle.write(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Global.Toronto.HD.ca2"><display-name>Global Toronto</display-name></channel>
  {duplicate_programme}
  {duplicate_programme}
</tv>
"""
        )

    mappings = [
        {
            "channel_id": "channel-1",
            "xmltv_id": "Global.Toronto.HD.ca2",
            "source_key": "epg_ripper_CA2",
            "mapping_type": "manual",
            "confidence": 100,
            "updated_at": "2026-07-30 12:00:00",
            "name": "CA| GLOBAL EAST HD",
            "tvg_name": "CA| GLOBAL EAST HD",
            "tvg_id": "ca.Global (CIII-DT-41) Toronto",
            "group_name": "CA| ENGLISH",
            "xml_url": "http://example.test/epg.xml.gz",
            "txt_url": "http://example.test/epg.txt",
        }
    ]
    selected_channels = [
        {
            "channel_id": "channel-1",
            "name": "CA| GLOBAL EAST HD",
            "tvg_name": "CA| GLOBAL EAST HD",
            "tvg_id": "ca.Global (CIII-DT-41) Toronto",
            "logo_url": "",
            "effective_logo_url": "",
        }
    ]

    with patch.object(epgshare, "FILTERED_EPG", output_xml), patch.object(
        epgshare, "ensure_epgshare_tables"
    ), patch.object(epgshare, "epgshare_active_mappings", return_value=mappings), patch.object(
        epgshare, "selected_channels_for_epgshare", return_value=selected_channels
    ), patch.object(epgshare, "download_to_tempfile", return_value=source_xml):
        result = epgshare.generate_filtered_epgshare(days=1)

    assert result["programme_count"] == 1

    root = ET.parse(output_xml).getroot()
    programmes = root.findall("programme")
    assert len(programmes) == 1
    assert programmes[0].attrib["channel"] == "ca.Global (CIII-DT-41) Toronto"
    assert programmes[0].findtext("title") == "The Morning Show"
