#!/bin/bash
set -euo pipefail
DOCKER=/opt/atow/runtime/docker/docker
exec 9>/opt/atow/deploy/renew.lock
flock -n 9 || exit 0
"$DOCKER" run --rm --network host --name atow-certbot-renew \
  -v /opt/atow/letsencrypt:/etc/letsencrypt \
  -v /opt/atow/acme:/var/www/acme \
  certbot/certbot:v5.4.0 renew --quiet --webroot -w /var/www/acme
"$DOCKER" exec atow-web nginx -s reload
