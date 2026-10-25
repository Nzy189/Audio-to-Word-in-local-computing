#!/bin/bash
set -euo pipefail
DOCKER=/opt/atow/runtime/docker/docker
if "$DOCKER" container inspect atow-web >/dev/null 2>&1; then
  echo 'atow-web already exists; stop and remove that container before recreating it.'
  exit 1
fi
mkdir -p /opt/atow/deploy/nginx-conf /opt/atow/logs
cp /opt/atow/deploy/nginx-https.conf /opt/atow/deploy/nginx-conf/default.conf
"$DOCKER" run -d --name atow-web --restart unless-stopped \
  --network host --memory 256m --pids-limit 128 \
  -v /opt/atow/deploy/nginx-conf:/etc/nginx/conf.d:ro \
  -v /opt/atow/acme:/var/www/acme:ro \
  -v /opt/atow/letsencrypt:/etc/letsencrypt:ro \
  -v /opt/atow/logs:/var/log/nginx \
  nginx:1.28-alpine
