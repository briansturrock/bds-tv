#!/usr/bin/env sh
set -eu

if [ $# -ne 1 ]; then
  echo "Usage: $0 /path/to/bds-tv-image.tar"
  exit 1
fi

docker load -i "$1"
docker images | grep -E 'bds_tv|iptv_epg' || true
