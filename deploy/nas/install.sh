#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
docker load -i shengjian-z2pro-arm64.tar
if docker compose version >/dev/null 2>&1; then
    docker compose up -d
elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose up -d
else
    echo 'Docker Compose is unavailable. Import the image and use the GUI settings in README.md.'
    exit 1
fi
echo 'Container started. Wait for a healthy status, then open the NAS IP on port 18088.'
