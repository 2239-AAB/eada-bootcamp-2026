#!/usr/bin/env bash
# Install or update Ownly on an Ubuntu 24.04 server. Run as root, from your own computer:
#
#   ssh root@SERVER 'bash -s' -- SITE < deploy/setup.sh
#
# SITE is the name Caddy gets an HTTPS certificate for: your own domain pointed at the server,
# or, without one, the server's IP written with dashes plus .sslip.io (203-0-113-5.sslip.io).
# Running it again updates the code and packages and restarts the app; data is kept.
set -euo pipefail

SITE="${1:?Usage: setup.sh SITE   (for example 203-0-113-5.sslip.io)}"
REPO="https://github.com/2239-AAB/eada-bootcamp-2026.git"
APP=/srv/ownly             # code and its virtualenv
DATA=/var/lib/ownly        # database, photos, session secret
PYTHONS=/opt/ownly-python  # Python 3.13, installed by uv
CACHE=/var/cache/ownly-uv
UV_VERSION=0.12.20
export DEBIAN_FRONTEND=noninteractive

echo "== System packages, security updates, firewall"
apt-get update -q
apt-get install -y -q git curl ufw unattended-upgrades libgomp1 debian-keyring debian-archive-keyring \
  apt-transport-https gpg >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy >/dev/null
fi
echo 'APT::Periodic::Update-Package-Lists "1"; APT::Periodic::Unattended-Upgrade "1";' \
  > /etc/apt/apt.conf.d/20auto-upgrades
ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== Swap (installing the model's packages needs more than 1 GB at peak)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== App user and folders"
id ownly >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin ownly
install -d -o ownly -g ownly -m 755 "$APP"
install -d -o ownly -g ownly -m 700 "$DATA"
install -d -o ownly -g ownly -m 700 "$CACHE"
install -d -m 755 "$PYTHONS"

echo "== Code"
if [ -d "$APP/.git" ]; then
  sudo -u ownly git -C "$APP" pull --ff-only -q
else
  sudo -u ownly git clone -q --depth 1 "$REPO" "$APP"
fi

echo "== Python 3.13 and packages"
command -v uv >/dev/null || curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
  | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
UV_PYTHON_INSTALL_DIR="$PYTHONS" uv python install -q 3.13
as_app() { sudo -u ownly env UV_PYTHON_INSTALL_DIR="$PYTHONS" UV_CACHE_DIR="$CACHE" "$@"; }
[ -x "$APP/.venv/bin/python" ] || as_app uv venv -q --python 3.13 "$APP/.venv"
# The CPU-only XGBoost build: the standard Linux wheel pulls in about 300 MB of GPU libraries.
XGB_VERSION=$(sed -n 's/^xgboost==//p' "$APP/requirements.txt")
grep -v '^xgboost==' "$APP/requirements.txt" > "$CACHE/requirements-server.txt"
as_app uv pip install -q --python "$APP/.venv/bin/python" -r "$CACHE/requirements-server.txt" "xgboost-cpu==$XGB_VERSION"

echo "== Example listings (first install only)"
if [ ! -f "$DATA/ownly.sqlite3" ]; then
  sudo -u ownly bash -c "cd '$APP' && OWNLY_INSTANCE='$DATA' .venv/bin/python -m ownly seed"
fi

echo "== Service and HTTPS"
install -m 644 "$APP/deploy/ownly.service" /etc/systemd/system/ownly.service
sed "s/{SITE}/$SITE/" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable -q ownly caddy
systemctl restart ownly
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "== Waiting for Ownly to answer (the model takes a few seconds to load)"
for _ in $(seq 1 45); do
  if curl -fsS -o /dev/null http://127.0.0.1:8000/; then
    echo "Ownly is running: https://$SITE"
    exit 0
  fi
  sleep 2
done
echo "Ownly did not answer. Look at: journalctl -u ownly -n 50" >&2
exit 1
