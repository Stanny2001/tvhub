#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pluto-gateway-ui"
DATA_DIR="/data"

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg curl

mkdir -p "$APP_DIR" "$DATA_DIR"
cp -r app pyproject.toml "$APP_DIR"/

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install fastapi uvicorn[standard] httpx pydantic

install -m 0644 systemd/pluto-gateway-ui.service /etc/systemd/system/pluto-gateway-ui.service
install -m 0440 systemd/pluto-gateway-ui.sudoers /etc/sudoers.d/pluto-gateway-ui

systemctl daemon-reload
systemctl enable --now pluto-gateway-ui.service

echo "Installed. UI: http://<container-ip>:8788"
