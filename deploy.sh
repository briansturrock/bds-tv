#!/usr/bin/env bash
set -e

cd /docker/iptv_epg/repo
git pull origin main
docker compose -p iptv_epg build
docker compose -p iptv_epg up -d --force-recreate
sleep 3
curl http://localhost:8088/health
