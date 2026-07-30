#!/usr/bin/env bash
set -e

cd /docker/bds-tv/repo
branch="$(git branch --show-current)"
git pull origin "$branch"
docker compose -p bds_tv build
docker stop bds-tv 2>/dev/null || true
docker rm bds-tv 2>/dev/null || true
docker compose -p bds_tv up -d --force-recreate
sleep 3
curl http://localhost:8088/health
