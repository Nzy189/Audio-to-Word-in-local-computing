#!/bin/bash
set -euo pipefail
DOCKER=/opt/atow/runtime/docker/docker
if "$DOCKER" container inspect atow-app >/dev/null 2>&1; then
  echo 'atow-app already exists; use docker restart atow-app, or remove that container before recreating it.'
  exit 1
fi
mkdir -p /opt/atow/data
chown 10001:10001 /opt/atow/data
"$DOCKER" run -d --name atow-app --restart unless-stopped \
  --network host --cpus 3 --memory 4g --pids-limit 256 \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m \
  --env-file /opt/atow/app.env \
  -v /opt/atow/data:/data \
  -v /opt/atow/models:/models:ro \
  --health-cmd 'python -c "import json,urllib.request,sys; sys.exit(not json.load(urllib.request.urlopen(\"http://127.0.0.1:8787/api/health\",timeout=3))[\"ready\"])"' \
  --health-interval 30s --health-timeout 5s --health-start-period 120s \
  "${ATOW_APP_IMAGE:-atow-transcriber:1.6.2-ecs}"
