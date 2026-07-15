from __future__ import annotations

import html
import socket
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque
from urllib.parse import unquote, urljoin
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from .db import get_setting, set_setting
from .hdhr import (
    ffmpeg_stream_iterator,
    get_hdhr_settings,
    reserve_stream_session,
    selected_catalogue_channels,
    selected_catalogue_groups,
    selected_channel_row,
    stop_stream_session,
    stream_selected_channel,
)


router = APIRouter(tags=["dlna"])

CONTENT_DIRECTORY_SERVICE = "urn:schemas-upnp-org:service:ContentDirectory:1"
CONNECTION_MANAGER_SERVICE = "urn:schemas-upnp-org:service:ConnectionManager:1"
DLNA_STREAM_MEDIA_TYPE = "video/mpeg"
DLNA_CONTENT_FEATURES = "DLNA.ORG_PN=MPEG_TS_SD_EU_ISO;DLNA.ORG_FLAGS=8D100000000000000000000000000000"
DLNA_VIDEO_PROTOCOL = f"http-get:*:{DLNA_STREAM_MEDIA_TYPE}:{DLNA_CONTENT_FEATURES}"
DLNA_STREAM_HEADERS = {
    "Accept-Ranges": "bytes",
    "Cache-Control": "no-store",
    "Connection": "close",
    "contentFeatures.dlna.org": DLNA_CONTENT_FEATURES,
    "transferMode.dlna.org": "Streaming",
    "X-Accel-Buffering": "no",
}
DLNA_REQUEST_LOG_LIMIT = 100
DLNA_REQUEST_LOG: Deque[dict[str, Any]] = deque(maxlen=DLNA_REQUEST_LOG_LIMIT)
DLNA_REQUEST_LOG_LOCK = threading.Lock()


class DlnaSettingsIn(BaseModel):
    enabled: bool = True
    device_name: str = "iptv-epg DLNA"
    public_base_url: str = ""
    stream_mode: str = "copy"


class DlnaInspectLocationIn(BaseModel):
    location: str


class DlnaInspectBrowseIn(BaseModel):
    location: str
    object_id: str = "0"
    browse_flag: str = "BrowseDirectChildren"
    starting_index: int = 0
    requested_count: int = 0


@dataclass
class DlnaSettings:
    enabled: bool
    device_name: str
    public_base_url: str
    stream_mode: str


def bool_setting(key: str, default: bool) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalise_base_url(value: str | None) -> str:
    return (value or "").strip().rstrip("/")


def interesting_headers(request: Request) -> dict[str, str]:
    names = [
        "user-agent",
        "range",
        "accept",
        "transfermode.dlna.org",
        "getcontentfeatures.dlna.org",
        "soapaction",
    ]
    return {name: request.headers[name] for name in names if name in request.headers}


def log_dlna_request(request: Request, event: str, **extra: Any) -> None:
    client = f"{request.client.host}:{request.client.port}" if request.client else None
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "method": request.method,
        "path": request.url.path,
        "query": request.url.query,
        "client": client,
        "headers": interesting_headers(request),
        **extra,
    }
    with DLNA_REQUEST_LOG_LOCK:
        DLNA_REQUEST_LOG.appendleft(entry)


def recent_dlna_requests() -> list[dict[str, Any]]:
    with DLNA_REQUEST_LOG_LOCK:
        return list(DLNA_REQUEST_LOG)


def clear_dlna_requests() -> None:
    with DLNA_REQUEST_LOG_LOCK:
        DLNA_REQUEST_LOG.clear()


def get_dlna_settings() -> DlnaSettings:
    hdhr_settings = get_hdhr_settings()
    stream_mode = (get_setting("dlna_stream_mode", "copy") or "copy").strip().lower()
    if stream_mode not in {"copy", "transcode"}:
        stream_mode = "copy"
    return DlnaSettings(
        enabled=bool_setting("dlna_enabled", True),
        device_name=(get_setting("dlna_device_name", "iptv-epg DLNA") or "iptv-epg DLNA").strip() or "iptv-epg DLNA",
        public_base_url=normalise_base_url(get_setting("dlna_public_base_url") or hdhr_settings.public_base_url),
        stream_mode=stream_mode,
    )


def save_dlna_settings(payload: DlnaSettingsIn) -> DlnaSettings:
    stream_mode = payload.stream_mode.strip().lower()
    if stream_mode not in {"copy", "transcode"}:
        stream_mode = "copy"
    values = {
        "dlna_enabled": "true" if payload.enabled else "false",
        "dlna_device_name": payload.device_name.strip() or "iptv-epg DLNA",
        "dlna_public_base_url": normalise_base_url(payload.public_base_url),
        "dlna_stream_mode": stream_mode,
    }
    for key, value in values.items():
        set_setting(key, value)
    return get_dlna_settings()


def base_url_for_request(request: Request, settings: DlnaSettings | None = None) -> str:
    settings = settings or get_dlna_settings()
    if settings.public_base_url:
        return settings.public_base_url
    return str(request.base_url).rstrip("/")


def device_uuid() -> str:
    return f"uuid:iptv-epg-dlna-{get_hdhr_settings().device_id}"


def dlna_location(base_url: str) -> str:
    return urljoin(f"{base_url}/", "dlna/device.xml")


def dlna_ssdp_targets() -> list[str]:
    return [
        "upnp:rootdevice",
        "urn:schemas-upnp-org:device:MediaServer:1",
        CONTENT_DIRECTORY_SERVICE,
        CONNECTION_MANAGER_SERVICE,
    ]


def dlna_ssdp_response(location: str, search_target: str) -> bytes:
    st = search_target or "upnp:rootdevice"
    usn = device_uuid()
    if st.lower() != "upnp:rootdevice":
        usn = f"{usn}::{st}"
    lines = [
        "HTTP/1.1 200 OK",
        "CACHE-CONTROL: max-age=1800",
        "EXT:",
        f"LOCATION: {location}",
        "SERVER: iptv-epg/1.0 UPnP/1.0 DLNADOC/1.50",
        f"ST: {st}",
        f"USN: {usn}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")


def dlna_ssdp_notify_messages(location: str) -> list[bytes]:
    messages = []
    for target in dlna_ssdp_targets():
        usn = device_uuid()
        if target != "upnp:rootdevice":
            usn = f"{usn}::{target}"
        lines = [
            "NOTIFY * HTTP/1.1",
            "HOST: 239.255.255.250:1900",
            "CACHE-CONTROL: max-age=1800",
            f"LOCATION: {location}",
            "SERVER: iptv-epg/1.0 UPnP/1.0 DLNADOC/1.50",
            f"NT: {target}",
            "NTS: ssdp:alive",
            f"USN: {usn}",
            "",
            "",
        ]
        messages.append("\r\n".join(lines).encode("utf-8"))
    return messages


def service_xml(service_type: str, service_id: str, scpd_url: str, control_url: str, event_url: str) -> ET.Element:
    service = ET.Element("service")
    ET.SubElement(service, "serviceType").text = service_type
    ET.SubElement(service, "serviceId").text = service_id
    ET.SubElement(service, "SCPDURL").text = scpd_url
    ET.SubElement(service, "controlURL").text = control_url
    ET.SubElement(service, "eventSubURL").text = event_url
    return service


def device_description_xml(base_url: str, settings: DlnaSettings) -> str:
    root = ET.Element("root", {"xmlns": "urn:schemas-upnp-org:device-1-0"})
    spec = ET.SubElement(root, "specVersion")
    ET.SubElement(spec, "major").text = "1"
    ET.SubElement(spec, "minor").text = "0"
    device = ET.SubElement(root, "device")
    ET.SubElement(device, "deviceType").text = "urn:schemas-upnp-org:device:MediaServer:1"
    ET.SubElement(device, "friendlyName").text = settings.device_name
    ET.SubElement(device, "manufacturer").text = "iptv-epg"
    ET.SubElement(device, "modelName").text = "iptv-epg DLNA"
    ET.SubElement(device, "modelNumber").text = "1"
    ET.SubElement(device, "UDN").text = device_uuid()
    ET.SubElement(device, "presentationURL").text = base_url
    services = ET.SubElement(device, "serviceList")
    services.append(service_xml(CONTENT_DIRECTORY_SERVICE, "urn:upnp-org:serviceId:ContentDirectory", "/dlna/content-directory.xml", "/dlna/control/content-directory", "/dlna/event/content-directory"))
    services.append(service_xml(CONNECTION_MANAGER_SERVICE, "urn:upnp-org:serviceId:ConnectionManager", "/dlna/connection-manager.xml", "/dlna/control/connection-manager", "/dlna/event/connection-manager"))
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")


def scpd_xml(_service_type: str, actions: list[str]) -> str:
    root = ET.Element("scpd", {"xmlns": "urn:schemas-upnp-org:service-1-0"})
    spec = ET.SubElement(root, "specVersion")
    ET.SubElement(spec, "major").text = "1"
    ET.SubElement(spec, "minor").text = "0"
    action_list = ET.SubElement(root, "actionList")
    for action_name in actions:
        action = ET.SubElement(action_list, "action")
        ET.SubElement(action, "name").text = action_name
    service_state_table = ET.SubElement(root, "serviceStateTable")
    variable = ET.SubElement(service_state_table, "stateVariable", {"sendEvents": "no"})
    ET.SubElement(variable, "name").text = "A_ARG_TYPE_ObjectID"
    ET.SubElement(variable, "dataType").text = "string"
    return '<?xml version="1.0"?>\n' + ET.tostring(root, encoding="unicode")


def didl_container(container_id: str, parent_id: str, title: str, child_count: int) -> str:
    return (
        f'<container id="{html.escape(container_id)}" parentID="{html.escape(parent_id)}" restricted="1" childCount="{child_count}">'
        f"<dc:title>{html.escape(title)}</dc:title>"
        "<upnp:class>object.container</upnp:class>"
        "<dlna:containerType>Tuner_1_0</dlna:containerType>"
        "</container>"
    )


def didl_channel(channel: dict[str, Any], parent_id: str, base_url: str) -> str:
    url = urljoin(f"{base_url}/", f"dlna/channel/{channel['channel_id']}.mpg")
    logo = channel.get("logo_url") or ""
    icon = f'<upnp:albumArtURI>{html.escape(logo)}</upnp:albumArtURI>' if logo else ""
    return (
        f'<item id="channel:{html.escape(channel["channel_id"])}" parentID="{html.escape(parent_id)}" restricted="1">'
        f"<dc:title>{html.escape(str(channel['number']))} {html.escape(channel['name'])}</dc:title>"
        "<upnp:class>object.item.videoItem.videoBroadcast</upnp:class>"
        f"<upnp:channelNr>{html.escape(str(channel['number']))}</upnp:channelNr>"
        f"<upnp:channelName>{html.escape(channel['name'])}</upnp:channelName>"
        f"{icon}"
        f'<res protocolInfo="{DLNA_VIDEO_PROTOCOL}">{html.escape(url)}</res>'
        "</item>"
    )


def didl_wrap(children: list[str]) -> str:
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/" '
        'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        + "".join(children)
        + "</DIDL-Lite>"
    )


def dlna_catalogue(base_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    channels = selected_catalogue_channels(limit=None)
    groups = selected_catalogue_groups(channels)
    for index, group in enumerate(groups, start=1):
        group["object_id"] = f"group:{index}"
        for channel in group["channels"]:
            channel["url"] = urljoin(f"{base_url}/", f"dlna/channel/{channel['channel_id']}")
    return channels, groups


def page_children(children: list[str], starting_index: int, requested_count: int) -> list[str]:
    starting_index = max(0, starting_index)
    if requested_count <= 0:
        return children[starting_index:]
    return children[starting_index : starting_index + requested_count]


def find_group_for_object_id(groups: list[dict[str, Any]], object_id: str) -> dict[str, Any] | None:
    decoded = unquote(object_id or "")
    if not decoded.startswith("group:"):
        return None
    group_key = decoded.split(":", 1)[1]
    if group_key.isdigit():
        index = int(group_key)
        if 1 <= index <= len(groups):
            return groups[index - 1]
    return next((item for item in groups if item["group_id"] == group_key or item.get("object_id") == decoded), None)


def browse_result(
    object_id: str,
    base_url: str,
    starting_index: int = 0,
    requested_count: int = 0,
    browse_flag: str = "BrowseDirectChildren",
) -> tuple[str, int, int]:
    channels, groups = dlna_catalogue(base_url)
    object_id = unquote(object_id or "0")
    if object_id in {"", "0"}:
        children = [
            didl_container(group["object_id"], "0", group["name"], len(group["channels"]))
            for group in groups
        ]
        if browse_flag == "BrowseMetadata":
            return didl_wrap([didl_container("0", "-1", "iptv-epg", len(children))]), 1, 1
        paged = page_children(children, starting_index, requested_count)
        return didl_wrap(paged), len(paged), len(children)

    if object_id.startswith("group:"):
        group = find_group_for_object_id(groups, object_id)
        if not group:
            return didl_wrap([]), 0, 0
        if browse_flag == "BrowseMetadata":
            return didl_wrap([didl_container(group["object_id"], "0", group["name"], len(group["channels"]))]), 1, 1
        children = [didl_channel(channel, object_id, base_url) for channel in group["channels"]]
        paged = page_children(children, starting_index, requested_count)
        return didl_wrap(paged), len(paged), len(children)

    if object_id.startswith("channel:"):
        channel_id = object_id.split(":", 1)[1]
        channel = next((item for item in channels if item["channel_id"] == channel_id), None)
        if not channel:
            return didl_wrap([]), 0, 0
        return didl_wrap([didl_channel(channel, "0", base_url)]), 1, 1

    return didl_wrap([]), 0, 0


def soap_response(action: str, service_type: str, body: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action}Response xmlns:u="{service_type}">'
        f"{body}"
        f"</u:{action}Response>"
        "</s:Body>"
        "</s:Envelope>"
    )


def xml_text(root: ET.Element, name: str, default: str = "") -> str:
    for elem in root.iter():
        if elem.tag.split("}", 1)[-1] == name:
            return elem.text or default
    return default


def xml_int(root: ET.Element, name: str, default: int = 0) -> int:
    try:
        return int(xml_text(root, name, str(default)))
    except ValueError:
        return default


def element_name(elem: ET.Element) -> str:
    return elem.tag.split("}", 1)[-1]


def child_text(elem: ET.Element, name: str, default: str = "") -> str:
    for child in elem:
        if element_name(child) == name:
            return child.text or default
    return default


def parse_ssdp_response(payload: bytes, addr: tuple[str, int]) -> dict[str, str]:
    lines = payload.decode("utf-8", errors="ignore").splitlines()
    item: dict[str, str] = {"from": f"{addr[0]}:{addr[1]}"}
    if lines:
        item["status"] = lines[0].strip()
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        item[key.strip().lower()] = value.strip()
    return item


def discover_dlna_devices(timeout_seconds: float = 3.0) -> list[dict[str, str]]:
    targets = ["urn:schemas-upnp-org:device:MediaServer:1", "ssdp:all"]
    seen: set[str] = set()
    devices: list[dict[str, str]] = []
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.settimeout(0.5)
        for target in targets:
            message = "\r\n".join(
                [
                    "M-SEARCH * HTTP/1.1",
                    "HOST: 239.255.255.250:1900",
                    'MAN: "ssdp:discover"',
                    "MX: 1",
                    f"ST: {target}",
                    "",
                    "",
                ]
            ).encode("utf-8")
            sock.sendto(message, ("239.255.255.250", 1900))
        while time.monotonic() < deadline:
            try:
                payload, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            item = parse_ssdp_response(payload, addr)
            location = item.get("location", "")
            if not location or location in seen:
                continue
            seen.add(location)
            devices.append(item)
    return devices


def fetch_text(url: str, timeout_seconds: float = 5.0) -> str:
    request = UrlRequest(url, headers={"User-Agent": "iptv-epg-dlna-inspector/1.0"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_device_description(location: str, xml: str) -> dict[str, Any]:
    root = ET.fromstring(xml)
    device = next((elem for elem in root.iter() if element_name(elem) == "device"), root)
    services = []
    for service in root.iter():
        if element_name(service) != "service":
            continue
        service_type = child_text(service, "serviceType")
        control_url = child_text(service, "controlURL")
        services.append(
            {
                "service_type": service_type,
                "service_id": child_text(service, "serviceId"),
                "control_url": urljoin(location, control_url),
                "scpd_url": urljoin(location, child_text(service, "SCPDURL")),
                "event_url": urljoin(location, child_text(service, "eventSubURL")),
            }
        )
    return {
        "friendly_name": child_text(device, "friendlyName"),
        "manufacturer": child_text(device, "manufacturer"),
        "model_name": child_text(device, "modelName"),
        "model_number": child_text(device, "modelNumber"),
        "udn": child_text(device, "UDN"),
        "presentation_url": child_text(device, "presentationURL"),
        "services": services,
        "content_directory": next((item for item in services if item["service_type"] == CONTENT_DIRECTORY_SERVICE), None),
    }


def content_directory_control_url(location: str) -> tuple[str, dict[str, Any], str]:
    xml = fetch_text(location)
    device = parse_device_description(location, xml)
    service = device.get("content_directory")
    if not service:
        raise HTTPException(status_code=400, detail="Device has no ContentDirectory service.")
    return service["control_url"], device, xml


def inspect_browse_payload(payload: DlnaInspectBrowseIn) -> str:
    browse_flag = payload.browse_flag if payload.browse_flag in {"BrowseDirectChildren", "BrowseMetadata"} else "BrowseDirectChildren"
    return (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:Browse xmlns:u="{CONTENT_DIRECTORY_SERVICE}">'
        f"<ObjectID>{html.escape(payload.object_id)}</ObjectID>"
        f"<BrowseFlag>{browse_flag}</BrowseFlag>"
        "<Filter>*</Filter>"
        f"<StartingIndex>{max(0, payload.starting_index)}</StartingIndex>"
        f"<RequestedCount>{max(0, payload.requested_count)}</RequestedCount>"
        "<SortCriteria></SortCriteria>"
        "</u:Browse>"
        "</s:Body>"
        "</s:Envelope>"
    )


def parse_didl_items(result_xml: str) -> list[dict[str, Any]]:
    if not result_xml.strip():
        return []
    root = ET.fromstring(result_xml)
    parsed: list[dict[str, Any]] = []
    for elem in root:
        kind = element_name(elem)
        if kind not in {"container", "item"}:
            continue
        resources = []
        for child in elem:
            if element_name(child) != "res":
                continue
            resources.append(
                {
                    "url": child.text or "",
                    "protocol_info": child.attrib.get("protocolInfo", ""),
                    "size": child.attrib.get("size", ""),
                    "duration": child.attrib.get("duration", ""),
                    "bitrate": child.attrib.get("bitrate", ""),
                    "resolution": child.attrib.get("resolution", ""),
                }
            )
        parsed.append(
            {
                "type": kind,
                "id": elem.attrib.get("id", ""),
                "parent_id": elem.attrib.get("parentID", ""),
                "restricted": elem.attrib.get("restricted", ""),
                "child_count": elem.attrib.get("childCount", ""),
                "title": child_text(elem, "title"),
                "class": child_text(elem, "class"),
                "resources": resources,
            }
        )
    return parsed


def parse_browse_response(xml: str) -> dict[str, Any]:
    root = ET.fromstring(xml)
    result = xml_text(root, "Result")
    return {
        "number_returned": xml_int(root, "NumberReturned", 0),
        "total_matches": xml_int(root, "TotalMatches", 0),
        "update_id": xml_text(root, "UpdateID"),
        "result_xml": result,
        "items": parse_didl_items(result),
    }


@router.get("/api/dlna/settings")
def api_dlna_settings(request: Request) -> dict:
    settings = get_dlna_settings()
    base_url = base_url_for_request(request, settings)
    channels, groups = dlna_catalogue(base_url)
    return {
        "ok": True,
        "settings": {**settings.__dict__, "resolved_base_url": base_url},
        "status": {"channel_count": len(channels), "group_count": len(groups), "device_url": dlna_location(base_url)},
        "recent_requests": recent_dlna_requests(),
    }


@router.post("/api/dlna/settings")
def api_save_dlna_settings(payload: DlnaSettingsIn, request: Request) -> dict:
    settings = save_dlna_settings(payload)
    base_url = base_url_for_request(request, settings)
    channels, groups = dlna_catalogue(base_url)
    return {
        "ok": True,
        "settings": {**settings.__dict__, "resolved_base_url": base_url},
        "status": {"channel_count": len(channels), "group_count": len(groups), "device_url": dlna_location(base_url)},
        "recent_requests": recent_dlna_requests(),
    }


@router.get("/api/dlna/requests")
def api_dlna_requests() -> dict:
    return {"ok": True, "requests": recent_dlna_requests()}


@router.delete("/api/dlna/requests")
def api_clear_dlna_requests() -> dict:
    clear_dlna_requests()
    return {"ok": True, "requests": []}


@router.post("/api/dlna/inspect/discover")
def api_dlna_inspect_discover() -> dict:
    return {"ok": True, "devices": discover_dlna_devices()}


@router.post("/api/dlna/inspect/device")
def api_dlna_inspect_device(payload: DlnaInspectLocationIn) -> dict:
    try:
        xml = fetch_text(payload.location)
        device = parse_device_description(payload.location, xml)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not inspect DLNA device: {exc}") from exc
    return {"ok": True, "device": device, "device_xml": xml}


@router.post("/api/dlna/inspect/browse")
def api_dlna_inspect_browse(payload: DlnaInspectBrowseIn) -> dict:
    try:
        control_url, device, _device_xml = content_directory_control_url(payload.location)
        body = inspect_browse_payload(payload)
        request = UrlRequest(
            control_url,
            data=body.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"{CONTENT_DIRECTORY_SERVICE}#Browse"',
                "User-Agent": "iptv-epg-dlna-inspector/1.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=8.0) as response:
            response_xml = response.read().decode("utf-8", errors="replace")
        parsed = parse_browse_response(response_xml)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not browse DLNA device: {exc}") from exc
    return {
        "ok": True,
        "device": device,
        "control_url": control_url,
        "request": {
            "object_id": payload.object_id,
            "browse_flag": payload.browse_flag,
            "starting_index": payload.starting_index,
            "requested_count": payload.requested_count,
        },
        "browse": parsed,
        "response_xml": response_xml,
    }


@router.get("/dlna/device.xml")
def dlna_device(request: Request) -> Response:
    log_dlna_request(request, "device")
    settings = get_dlna_settings()
    return Response(device_description_xml(base_url_for_request(request, settings), settings), media_type="application/xml")


@router.get("/dlna/content-directory.xml")
def content_directory_scpd() -> Response:
    return Response(scpd_xml(CONTENT_DIRECTORY_SERVICE, ["Browse", "GetSearchCapabilities", "GetSortCapabilities", "GetSystemUpdateID"]), media_type="application/xml")


@router.get("/dlna/connection-manager.xml")
def connection_manager_scpd() -> Response:
    return Response(scpd_xml(CONNECTION_MANAGER_SERVICE, ["GetProtocolInfo"]), media_type="application/xml")


@router.post("/dlna/control/content-directory")
async def content_directory_control(request: Request) -> Response:
    body = await request.body()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        root = ET.Element("empty")
    action = (request.headers.get("SOAPACTION") or "").upper()
    if "GETSEARCHCAPABILITIES" in action:
        action_name = "GetSearchCapabilities"
        payload = "<SearchCaps></SearchCaps>"
    elif "GETSORTCAPABILITIES" in action:
        action_name = "GetSortCapabilities"
        payload = "<SortCaps></SortCaps>"
    elif "GETSYSTEMUPDATEID" in action:
        action_name = "GetSystemUpdateID"
        payload = "<Id>1</Id>"
    else:
        action_name = "Browse"
        object_id = xml_text(root, "ObjectID", "0")
        browse_flag = xml_text(root, "BrowseFlag", "BrowseDirectChildren")
        starting_index = xml_int(root, "StartingIndex", 0)
        requested_count = xml_int(root, "RequestedCount", 0)
        result, returned, total = browse_result(
            object_id,
            base_url_for_request(request),
            starting_index,
            requested_count,
            browse_flag,
        )
        log_dlna_request(
            request,
            "content_directory",
            action=action_name,
            object_id=object_id,
            browse_flag=browse_flag,
            starting_index=starting_index,
            requested_count=requested_count,
            returned=returned,
            total=total,
        )
        payload = (
            f"<Result>{html.escape(result)}</Result>"
            f"<NumberReturned>{returned}</NumberReturned>"
            f"<TotalMatches>{total}</TotalMatches>"
            "<UpdateID>1</UpdateID>"
        )
    if action_name != "Browse":
        log_dlna_request(request, "content_directory", action=action_name)
    return Response(soap_response(action_name, CONTENT_DIRECTORY_SERVICE, payload), media_type="text/xml; charset=utf-8")


@router.post("/dlna/control/connection-manager")
async def connection_manager_control(request: Request) -> Response:
    log_dlna_request(request, "connection_manager")
    payload = f"<Source>{DLNA_VIDEO_PROTOCOL}</Source><Sink></Sink>"
    return Response(soap_response("GetProtocolInfo", CONNECTION_MANAGER_SERVICE, payload), media_type="text/xml; charset=utf-8")


@router.get("/dlna/event/content-directory")
@router.get("/dlna/event/connection-manager")
def dlna_event() -> PlainTextResponse:
    return PlainTextResponse("")


@router.get("/dlna/channel/{channel_id}", response_model=None)
def dlna_stream_channel(channel_id: str, request: Request) -> StreamingResponse:
    clean_channel_id = channel_id[:-4] if channel_id.endswith(".mpg") else channel_id
    settings = get_dlna_settings()
    log_dlna_request(request, "stream_get", channel_id=clean_channel_id, stream_mode=settings.stream_mode)
    if settings.stream_mode == "transcode":
        response = dlna_transcoded_stream(clean_channel_id)
    else:
        response = stream_selected_channel(clean_channel_id, get_hdhr_settings())
    response.media_type = DLNA_STREAM_MEDIA_TYPE
    response.headers["Content-Type"] = DLNA_STREAM_MEDIA_TYPE
    response.headers["Content-Disposition"] = f'inline; filename="{clean_channel_id}.mpg"'
    for key, value in DLNA_STREAM_HEADERS.items():
        response.headers[key] = value
    return response


@router.get("/dlna/channel/{channel_id}.mpg", response_model=None)
def dlna_stream_channel_mpg(channel_id: str, request: Request) -> StreamingResponse:
    return dlna_stream_channel(channel_id, request)


@router.head("/dlna/channel/{channel_id}", response_model=None)
@router.head("/dlna/channel/{channel_id}.mpg", response_model=None)
def dlna_stream_head(channel_id: str, request: Request) -> Response:
    clean_channel_id = channel_id[:-4] if channel_id.endswith(".mpg") else channel_id
    selected_channel_row(clean_channel_id)
    headers = {
        **DLNA_STREAM_HEADERS,
        "Content-Type": DLNA_STREAM_MEDIA_TYPE,
        "Content-Disposition": f'inline; filename="{clean_channel_id}.mpg"',
    }
    log_dlna_request(request, "stream_head", channel_id=clean_channel_id, response_headers=headers)
    return Response(status_code=200, headers=headers, media_type=DLNA_STREAM_MEDIA_TYPE)


def dlna_transcode_command(stream_url: str, ffmpeg_path: str) -> list[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-user_agent",
        "VLC/3.0.0 LibVLC/3.0.0",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        stream_url,
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-f",
        "mpegts",
        "pipe:1",
    ]


def dlna_transcoded_stream(channel_id: str) -> StreamingResponse:
    hdhr_settings = get_hdhr_settings()
    channel = selected_channel_row(channel_id)
    session = reserve_stream_session(channel, hdhr_settings)
    session.mode = "dlna_transcode"

    try:
        session.process = subprocess.Popen(
            dlna_transcode_command(channel["stream_url"], hdhr_settings.ffmpeg_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        stop_stream_session(session.session_id)
        raise HTTPException(status_code=500, detail=f"Could not start ffmpeg: {exc}") from exc

    return StreamingResponse(
        ffmpeg_stream_iterator(session),
        media_type=DLNA_STREAM_MEDIA_TYPE,
        headers=DLNA_STREAM_HEADERS,
    )
