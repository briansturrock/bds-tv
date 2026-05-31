#!/usr/bin/env sh
set -eu

IMAGE_TAG="${1:-iptv_epg:dev}"

mkdir -p /docker/iptv_epg/config /docker/iptv_epg/data /docker/iptv_epg/db /docker/iptv_epg/logs

docker stop iptv_epg 2>/dev/null || true
docker rm iptv_epg 2>/dev/null || true

docker run -d \
  --name iptv_epg \
  --restart unless-stopped \
  -p 8088:8080 \
  -e TZ=UTC \
  -v /docker/iptv_epg/config:/config \
  -v /docker/iptv_epg/data:/data \
  -v /docker/iptv_epg/db:/db \
  -v /docker/iptv_epg/logs:/logs \
  "$IMAGE_TAG"
