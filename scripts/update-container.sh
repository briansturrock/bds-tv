#!/usr/bin/env sh
set -eu

IMAGE_TAG="${1:-bds_tv:dev}"
APP_ROOT="${BDS_TV_ROOT:-/docker/bds-tv}"
if [ ! -d "$APP_ROOT" ] && [ -d /docker/iptv_epg ]; then
  APP_ROOT="/docker/iptv_epg"
fi

mkdir -p "$APP_ROOT/config" "$APP_ROOT/data" "$APP_ROOT/db" "$APP_ROOT/logs"

docker stop bds-tv iptv-epg iptv_epg 2>/dev/null || true
docker rm bds-tv iptv-epg iptv_epg 2>/dev/null || true

docker run -d \
  --name bds-tv \
  --restart unless-stopped \
  -p 8088:8080 \
  -e TZ=UTC \
  -v "$APP_ROOT/config:/config" \
  -v "$APP_ROOT/data:/data" \
  -v "$APP_ROOT/db:/db" \
  -v "$APP_ROOT/logs:/logs" \
  "$IMAGE_TAG"
