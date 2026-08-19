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

# Every override is KV_-prefixed on purpose: plain NAME, APPDATA and PORT already exist in
# a WSL shell (NAME carries the Windows machine name), and inheriting one of those silently
# named the container after the laptop.
KV_SERVER="${KV_SERVER:-root@192.168.88.98}"
KV_IMAGE="${KV_IMAGE:-ghcr.io/morphem/kvasir:latest}"
KV_NAME="${KV_NAME:-kvasir}"
KV_PORT="${KV_PORT:-8688}"
KV_APPDATA="${KV_APPDATA:-/mnt/user/appdata/kvasir}"
KV_HIDDEN="${KV_HIDDEN:-grok-4.5,grok-4.6,fable-5,gpt-5.6-sol,kimi-k3,kimi-k2.7-code,glm-5.2}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--template" ]; then
  scp -q "$here/unraid/my-Kvasir.xml" \
    "$KV_SERVER:/boot/config/plugins/dockerMan/templates-user/my-Kvasir.xml"
  scp -q "$here/deploy/kvasir.blinkneuron.eu.conf" \
    "$KV_SERVER:/mnt/user/appdata/swag/nginx/site-confs/kvasir.blinkneuron.eu.conf"
  echo "template + swag conf copied"
fi

ssh "$KV_SERVER" bash -s <<REMOTE
set -euo pipefail
mkdir -p "$KV_APPDATA"
chown 99:100 "$KV_APPDATA"
docker pull "$KV_IMAGE"
docker rm -f "$KV_NAME" 2>/dev/null || true
docker run -d --name "$KV_NAME" \
  --restart unless-stopped \
  -p ${KV_PORT}:8688 \
  -v "${KV_APPDATA}:/data" \
  -e KVASIR_HIDDEN_MODELS="$KV_HIDDEN" \
  -e TZ=Europe/Warsaw \
  -l net.unraid.docker.managed=dockerman \
  -l net.unraid.docker.webui="http://[IP]:[PORT:8688]/" \
  -l net.unraid.docker.icon="https://raw.githubusercontent.com/morphem/kvasir/main/assets/icon.png" \
  "$KV_IMAGE"
sleep 6
curl -sf "http://127.0.0.1:${KV_PORT}/api/health" || { docker logs --tail 40 "$KV_NAME"; exit 1; }
echo
REMOTE

echo "kvasir is up: http://192.168.88.98:${KV_PORT}/"
