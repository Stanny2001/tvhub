#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Bitte als root ausführen." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="/opt/pluto-gateway-ui"
PLUTO_DIR="/opt/plutotv-tvheadend"
DATA_DIR="/data"
SERVICE_USER="plutogw"
PLUTO_REPO_URL="https://github.com/mclenburg/plutoTV-tvheadend.git"

apt-get update
apt-get install -y \
  git perl cpanminus openssl ffmpeg curl ca-certificates \
  python3 python3-venv python3-pip sudo iproute2

# Prefer apt Perl deps
PERL_APT_PKGS=(
  libhttp-daemon-perl
  libhttp-request-params-perl
  libdatetime-perl
  libjson-parse-perl
  libuuid-tiny-perl
  libfile-which-perl
  libnet-address-ip-local-perl
  libcrypt-cbc-perl
  libipc-run-perl
)
apt-get install -y "${PERL_APT_PKGS[@]}" || true

# CPAN fallback for missing modules
cpanm_install_if_missing() {
  local module="$1"
  perl -M"$module" -e1 >/dev/null 2>&1 || cpanm --notest "$module"
}
cpanm_install_if_missing HTTP::Daemon
cpanm_install_if_missing HTTP::Request::Params
cpanm_install_if_missing DateTime
cpanm_install_if_missing JSON::Parse
cpanm_install_if_missing UUID::Tiny
cpanm_install_if_missing File::Which
cpanm_install_if_missing Net::Address::IP::Local
cpanm_install_if_missing Crypt::CBC
cpanm_install_if_missing IPC::Run

# Install/update PlutoTV localserver
if [[ -d "$PLUTO_DIR/.git" ]]; then
  git -C "$PLUTO_DIR" pull --ff-only
else
  rm -rf "$PLUTO_DIR"
  git clone "$PLUTO_REPO_URL" "$PLUTO_DIR"
fi

# service user for UI
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/pluto-gateway-ui --shell /usr/sbin/nologin "$SERVICE_USER"

mkdir -p "$APP_DIR" "$DATA_DIR"
cp -r "$REPO_DIR"/app "$REPO_DIR"/pyproject.toml "$APP_DIR"/
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR" "$DATA_DIR"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install fastapi uvicorn[standard] httpx pydantic

# Systemd units
install -m 0644 "$REPO_DIR/systemd/plutotv.service" /etc/systemd/system/plutotv.service
install -m 0644 "$REPO_DIR/systemd/pluto-gateway-ui.service" /etc/systemd/system/pluto-gateway-ui.service
sed "s/__SERVICE_USER__/$SERVICE_USER/g" "$REPO_DIR/systemd/pluto-gateway-ui.sudoers" > /etc/sudoers.d/pluto-gateway-ui
chmod 0440 /etc/sudoers.d/pluto-gateway-ui

systemctl daemon-reload
systemctl enable --now plutotv.service
systemctl enable --now pluto-gateway-ui.service

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
IP_ADDR="${IP_ADDR:-CONTAINER_IP}"

cat <<MSG

Installation abgeschlossen.

Services prüfen:
  systemctl status plutotv --no-pager
  systemctl status pluto-gateway-ui --no-pager

Tests im Container:
  curl -I http://127.0.0.1:9000/tvheadend?region=DE
  curl -I http://127.0.0.1:9000/epg
  curl -s http://127.0.0.1:8080/api/health

TVHeadend Einträge:
  IPTV M3U:  http://${IP_ADDR}:9000/tvheadend?region=DE
  EPG XMLTV: http://${IP_ADDR}:9000/epg
  Stable:    http://${IP_ADDR}:8080/pluto_stable.m3u
  WebUI:     http://${IP_ADDR}:8080
MSG
