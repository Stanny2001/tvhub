#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pluto-gateway-ui"
DATA_DIR="/data"
SERVICE_USER="plutogw"

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg curl sudo iproute2

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/pluto-gateway-ui --shell /usr/sbin/nologin "$SERVICE_USER"

mkdir -p "$APP_DIR" "$DATA_DIR"
cp -r app pyproject.toml "$APP_DIR"/
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR" "$DATA_DIR"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install fastapi uvicorn[standard] httpx pydantic

install -m 0644 systemd/pluto-gateway-ui.service /etc/systemd/system/pluto-gateway-ui.service
sed "s/__SERVICE_USER__/$SERVICE_USER/g" systemd/pluto-gateway-ui.sudoers > /etc/sudoers.d/pluto-gateway-ui
chmod 0440 /etc/sudoers.d/pluto-gateway-ui

systemctl daemon-reload
systemctl enable --now pluto-gateway-ui.service

echo "Installed. UI: http://<container-ip>:8788"
