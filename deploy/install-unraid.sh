#!/usr/bin/env bash
#
# First-time install of Kvasir on the Unraid box, and the redeploy path afterwards.
#
#   ./deploy/install-unraid.sh            pull :latest and (re)create the container
#   ./deploy/install-unraid.sh --template also copy the CA template + SWAG site conf
#
# The container itself is stateless; everything worth keeping is the SQLite archive in
# /mnt/user/appdata/kvasir, which is why the volume is bind-mounted rather than named.

set -euo pipefail

SERVER="${SERVER:-root@192.168.88.98}"
IMAGE="${IMAGE:-ghcr.io/morphem/kvasir:latest}"
NAME="${NAME:-kvasir}"
PORT="${PORT:-8688}"
APPDATA="${APPDATA:-/mnt/user/appdata/kvasir}"
HIDDEN="${HIDDEN:-grok-4.5,grok-4.6,fable-5,gpt-5.6-sol,kimi-k3,kimi-k2.7-code,glm-5.2}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--template" ]; then
  scp -q "$here/unraid/my-Kvasir.xml" \
    "$SERVER:/boot/config/plugins/dockerMan/templates-user/my-Kvasir.xml"
  scp -q "$here/deploy/kvasir.blinkneuron.eu.conf" \
    "$SERVER:/mnt/user/appdata/swag/nginx/site-confs/kvasir.blinkneuron.eu.conf"
  echo "template + swag conf copied"
fi

ssh "$SERVER" bash -s <<REMOTE
set -euo pipefail
mkdir -p "$APPDATA"
chown 99:100 "$APPDATA"
docker pull "$IMAGE"
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" \
  --restart unless-stopped \
  -p ${PORT}:8688 \
  -v "${APPDATA}:/data" \
  -e KVASIR_HIDDEN_MODELS="$HIDDEN" \
  -e TZ=Europe/Warsaw \
  -l net.unraid.docker.managed=dockerman \
  -l net.unraid.docker.webui="http://[IP]:[PORT:8688]/" \
  -l net.unraid.docker.icon="https://raw.githubusercontent.com/morphem/kvasir/main/assets/icon.png" \
  "$IMAGE"
sleep 6
curl -sf "http://127.0.0.1:${PORT}/api/health" || { docker logs --tail 40 "$NAME"; exit 1; }
echo
REMOTE

echo "kvasir is up: http://192.168.88.98:${PORT}/"
