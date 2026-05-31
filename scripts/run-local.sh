#!/usr/bin/env sh
set -eu

mkdir -p config data db logs
docker compose up --build
