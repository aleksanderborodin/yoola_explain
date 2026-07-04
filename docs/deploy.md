# Deploy

**Stack: uv + systemd + Caddy. No Docker, no nginx.** One small Python service
on a 2 GB box gains nothing from containers; Caddy does automatic Let's Encrypt
HTTPS (nginx would need certbot + config for zero benefit at this size).

**Production origin: `https://yoola-explain.aleksanderbor.ru`** (A record →
the box in the gitignored `server.md`). This origin is baked into
`extension/background.js` (`API_BASE`), `extension/manifest.json`
(host_permissions), and `site/site.js` (`YOOLA_API`) — change all four together.

## One-shot setup / update

On the server (access + inventory in the gitignored `server.md`):

```bash
ssh root@<server-ip>
LLM_KEY=rp_xxx bash <(curl -fsSL \
  https://raw.githubusercontent.com/aleksanderborodin/yoola_explain/master/deploy/server-setup.sh)
```

Or copy `deploy/server-setup.sh` over and run it. `DOMAIN` defaults to the
production domain above; `DOMAIN=` (empty) serves plain HTTP on :80. Re-running
= update (git pull + restart).

What it does: installs Caddy + uv, clones to `/srv/yoola`, writes
`server/.env` (key, `YOOLA_TRUSTED_PROXY_HOPS=1`, random report salt), installs
a **single-worker** systemd unit (`yoola.service` — SQLite is single-process,
gotcha #6), a 3-line Caddyfile reverse proxy with auto-TLS, and ufw
(22/80/443 only).

## Follow-ups

- The script sets `YOOLA_ALLOWED_ORIGINS=["https://aleksanderborodin.github.io"]`
  so the GitHub Pages directory can query `/v1/directory` from the browser.
- Before real public exposure: switch SSH to keys + disable password auth,
  `unattended-upgrades`, fail2ban.

## Ops

```bash
systemctl status yoola          # service state
journalctl -u yoola -f          # logs
curl -s localhost:8000/metrics  # hit rate, spend counters
systemctl restart yoola         # after config change
```

The database is a single file (`/srv/yoola/yoola.db`); back it up with
`sqlite3 yoola.db ".backup backup.db"` on a cron if the cache becomes valuable.
