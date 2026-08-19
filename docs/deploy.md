# Deploy

Target: Unraid `Node304` (`192.168.88.98`), image from GHCR, edge via SWAG, public at
`https://kvasir.blinkneuron.eu`.

## 1. Image

CI builds `ghcr.io/morphem/kvasir:latest` on every push to `main`
(`.github/workflows/docker-publish.yml`). The GHCR package must be **public** once, so Unraid can
pull it without credentials: GitHub → Packages → `kvasir` → Package settings → Change visibility.

## 2. Container

```bash
./deploy/install-unraid.sh --template
```

That copies the Community-Applications template to
`/boot/config/plugins/dockerMan/templates-user/my-Kvasir.xml`, copies the SWAG site config, pulls
the image and (re)creates the container on port 8688 with `/mnt/user/appdata/kvasir` mounted at
`/data`.

After the first run the container is a normal Unraid app: it appears on the Docker tab with its
icon and WebUI link, and shows "update ready" whenever the image moves. **Do not enable
auto-update** — house rule.

Installing from the template instead (equivalent, click path): Docker → Add Container → select
`kvasir` from the user templates dropdown → Apply.

## 3. Domain

`kvasir.blinkneuron.eu` is a secondary domain for this SWAG instance (its primary is
`prawdzik.eu`), so it needs two things:

1. **DNS** — point `kvasir.blinkneuron.eu` at the home WAN address, the same target as
   `decks.blinkneuron.eu` (CNAME to the MikroTik DDNS name at domeny.tv).
2. **Certificate** — add the host to SWAG's `EXTRA_DOMAINS` and restart it:

   ```
   EXTRA_DOMAINS=decks.blinkneuron.eu,kvasir.blinkneuron.eu
   ```

   Unraid → Docker → swag → Edit → `EXTRA_DOMAINS` → Apply. SWAG re-runs the HTTP-01 challenge on
   start; port 80 must reach it (it already does — that is how `decks` got its cert).

The vhost itself is `deploy/kvasir.blinkneuron.eu.conf`, installed to
`/mnt/user/appdata/swag/nginx/site-confs/`. It sits in `site-confs` rather than `proxy-confs`
because those are reserved for `*.prawdzik.eu` subdomains.

## Access: deliberately open

The ecosystem default is Authelia forward-auth on every new app (`xreal/CONSTITUTION.md` §6).
Kvasir ships **without it**, on purpose: the page is meant to be handed to colleagues, and every
number on it is already public — it quotes three public sources and holds no account data, no keys
and nothing about our code. If that changes, protect it by adding the Authelia snippet to
`deploy/kvasir.blinkneuron.eu.conf` inside the `location /` block:

```nginx
include /config/nginx/authelia-server.conf;
include /config/nginx/authelia-location.conf;
```

## 4. Smoke test

```bash
curl -s https://kvasir.blinkneuron.eu/api/health | head -c 200   # {"ok":true,...}
curl -s -o /dev/null -w '%{http_code}\n' https://kvasir.blinkneuron.eu/
ssh root@192.168.88.98 'docker logs --tail 30 kvasir'
```

Done means: the page answers, all three freshness chips are green, and each verdict names a model
**with its effort**.

## Backup

Everything worth keeping is `/mnt/user/appdata/kvasir/kvasir.db` (plus its `-wal`). It is small —
a snapshot is written only when a source actually changes.

```bash
ssh root@192.168.88.98 'sqlite3 /mnt/user/appdata/kvasir/kvasir.db ".backup /mnt/user/appdata/kvasir/backup-$(date +%F).db"'
```
