#!/usr/bin/env bash
# Yoola one-shot server setup. Run as root on a fresh Ubuntu 24.04 box:
#   DOMAIN=api.yoola.example LLM_KEY=rp_xxx bash server-setup.sh
# Idempotent: safe to re-run for updates (it git-pulls and restarts).
set -euo pipefail

DOMAIN="${DOMAIN:-}"            # empty = HTTP-only on :80 (testing before DNS is ready)
LLM_KEY="${LLM_KEY:?set LLM_KEY=<modelgate key>}"
REPO="${REPO:-https://github.com/aleksanderborodin/yoola_explain.git}"
APP_DIR=/srv/yoola

echo "== packages =="
apt-get update -q
apt-get install -yq git ufw
command -v caddy >/dev/null || {
  apt-get install -yq debian-keyring debian-archive-keyring apt-transport-https curl
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -yq caddy
}
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "== app =="
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull --ff-only; else git clone "$REPO" "$APP_DIR"; fi
cd "$APP_DIR/server"
uv sync --no-dev

cat > "$APP_DIR/server/.env" <<EOF
YOOLA_LLM_API_KEY=$LLM_KEY
YOOLA_LLM_BASE_URL=https://api.modelgate.ru/v1
YOOLA_GENERATOR_MODEL=gemma-4-31b
YOOLA_VERIFIER_MODEL=gemma-4-31b
YOOLA_DB_PATH=$APP_DIR/yoola.db
YOOLA_TRUSTED_PROXY_HOPS=1
YOOLA_REPORT_SALT=$(head -c16 /dev/urandom | xxd -p)
EOF
chmod 600 "$APP_DIR/server/.env"

echo "== systemd =="
cat > /etc/systemd/system/yoola.service <<EOF
[Unit]
Description=Yoola API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR/server
# ONE worker only: SQLite store + budgets are single-process (docs/gotchas.md #6)
ExecStart=$HOME/.local/bin/uv run uvicorn --factory yoola.app:create_app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
# hardening
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now yoola
systemctl restart yoola

echo "== caddy =="
if [ -n "$DOMAIN" ]; then
  SITE="$DOMAIN"
else
  SITE=":80"   # pre-DNS testing; switch to the domain for real HTTPS
fi
cat > /etc/caddy/Caddyfile <<EOF
$SITE {
    # Caddy appends the client IP to X-Forwarded-For -> YOOLA_TRUSTED_PROXY_HOPS=1
    reverse_proxy 127.0.0.1:8000
}
EOF
systemctl restart caddy

echo "== firewall =="
ufw allow OpenSSH >/dev/null
ufw allow 80,443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== smoke =="
sleep 2
curl -fsS http://127.0.0.1:8000/healthz && echo " api ok"
echo "DONE. $([ -n "$DOMAIN" ] && echo "https://$DOMAIN" || echo "http://<server-ip>") -> Yoola"
echo "NEXT: switch extension/background.js API_BASE and site/site.js YOOLA_API to this origin."
