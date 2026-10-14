#!/usr/bin/env bash
#
# First-time install of Kvasir on the Unraid box, and the redeploy path afterwards.
#
#   ./deploy/install-unraid.sh            update the container the way the Docker tab does
#   ./deploy/install-unraid.sh --template first copy the Unraid template + SWAG site conf
#
# Every setting (image, port, env) lives in unraid/my-Kvasir.xml; change it there and deploy
# with --template.
#
# The container itself is stateless; everything worth keeping is the SQLite archive in
# /mnt/user/appdata/kvasir, which is why the volume is bind-mounted rather than named.

set -euo pipefail

# Every override is KV_-prefixed on purpose: plain NAME, APPDATA and PORT already exist in
# a WSL shell (NAME carries the Windows machine name), and inheriting one of those silently
# named the container after the laptop.
KV_SERVER="${KV_SERVER:-root@192.168.88.98}"
KV_NAME="${KV_NAME:-kvasir}"
KV_PORT="${KV_PORT:-8688}"
KV_APPDATA="${KV_APPDATA:-/mnt/user/appdata/kvasir}"
# The AI Stupid Level key is a secret: it lives in a root-only file on the server and never
# in this repo, in the Unraid template, or in a container label. When given in the
# environment, it is written to that file; the deploy itself never passes it. Inside the data
# volume on purpose: the container reads it from there when no environment variable is set,
# so the key survives every rebuild, whoever does it.
KV_SECRETS="${KV_SECRETS:-${KV_APPDATA:-/mnt/user/appdata/kvasir}/secrets.env}"
KV_ASL_KEY="${KVASIR_STUPIDLEVEL_API_KEY:-}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--template" ]; then
  scp -q "$here/unraid/my-Kvasir.xml" \
    "$KV_SERVER:/boot/config/plugins/dockerMan/templates-user/my-Kvasir.xml"
  scp -q "$here/deploy/kvasir.blinkneuron.eu.conf" \
    "$KV_SERVER:/mnt/user/appdata/swag/nginx/site-confs/kvasir.blinkneuron.eu.conf"
  echo "template + swag conf copied"
fi

if [ -n "$KV_ASL_KEY" ]; then
  ssh "$KV_SERVER" "install -d -m 750 -o 99 -g 100 \"$(dirname "$KV_SECRETS")\" \
    && printf 'KVASIR_STUPIDLEVEL_API_KEY=%s\n' \"$KV_ASL_KEY\" > \"$KV_SECRETS\" \
    && chown 99:100 \"$KV_SECRETS\" && chmod 600 \"$KV_SECRETS\""
  echo "api key stored on the server"
fi

# The container is built by Unraid itself, from the template, exactly as the Docker tab's
# "Apply update" builds it. A plain `docker pull` + `docker run` from here left Unraid's own
# record of the image digest stale, so the tab offered an update that was already running,
# and two recipes for one container drifted apart (the API key went missing that way).
ssh "$KV_SERVER" bash -s <<REMOTE
set -euo pipefail
mkdir -p "$KV_APPDATA"
chown 99:100 "$KV_APPDATA"
[ -f /boot/config/plugins/dockerMan/templates-user/my-Kvasir.xml ] \
  || { echo "no Unraid template on the server: run with --template first" >&2; exit 1; }
/usr/local/emhttp/plugins/dynamix.docker.manager/scripts/update_container "$KV_NAME" >/dev/null
sleep 6
curl -sf "http://127.0.0.1:${KV_PORT}/api/health" || { docker logs --tail 40 "$KV_NAME"; exit 1; }
echo
REMOTE

echo "kvasir is up: http://192.168.88.98:${KV_PORT}/"
