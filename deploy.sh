#!/usr/bin/env bash
set -e

if [ -d /docker/bds-tv/repo ]; then
  cd /docker/bds-tv/repo
else
  cd /docker/iptv_epg/repo
fi
git pull origin main
docker compose -p bds_tv build
docker stop iptv-epg iptv_epg 2>/dev/null || true
docker rm iptv-epg iptv_epg 2>/dev/null || true
docker compose -p bds_tv up -d --force-recreate
sleep 3
curl http://localhost:8088/health
