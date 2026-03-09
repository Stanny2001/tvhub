# PlutoTV → TVHeadend Gateway

One-command Setup für einen **frischen Ubuntu-Container**:
- installiert PlutoTV Localserver (Perl) + systemd Service (`plutotv`)
- installiert FastAPI WebUI + API + systemd Service (`pluto-gateway-ui`)
- persistente Daten unter `/data`

## Architektur
- Pluto Service: `http://CONTAINER_IP:9000`
  - M3U: `/tvheadend?region=DE`
  - EPG: `/epg`
  - Streams: `/stream/<channel-id>.m3u8`
- WebUI/API Service: `http://CONTAINER_IP:8080`
  - Stable Playlist: `/pluto_stable.m3u`
  - API: `/api/*`

## One-command Installation (frischer Container)

```bash
apt-get update && apt-get install -y git
cd /opt
git clone https://github.com/Stanny2001/tvhub.git
cd tvhub
./setup.sh
```

`setup.sh` ruft automatisch den Installer auf und installiert komplett:
- Systempakete: `git perl cpanminus openssl ffmpeg curl ca-certificates python3 python3-venv`
- PlutoTV Repo: `https://github.com/mclenburg/plutoTV-tvheadend.git` nach `/opt/plutotv-tvheadend`
- Perl-Dependencies via apt, Fallback via `cpanm`
- systemd Unit: `/etc/systemd/system/plutotv.service`
- WebUI in `/opt/pluto-gateway-ui` + systemd Unit `/etc/systemd/system/pluto-gateway-ui.service`
- sudoers Drop-in: `/etc/sudoers.d/pluto-gateway-ui`
- Persistenzordner: `/data`

## Services prüfen

```bash
systemctl status plutotv --no-pager
systemctl status pluto-gateway-ui --no-pager
```

## Funktion prüfen (curl)

```bash
# Pluto direkt
curl -I http://127.0.0.1:9000/tvheadend?region=DE
curl -I http://127.0.0.1:9000/epg

# Gateway API
curl -s http://127.0.0.1:8080/api/health
curl -s http://127.0.0.1:8080/api/status

# Stable playlist (nach Generierung)
curl -I http://127.0.0.1:8080/pluto_stable.m3u
```

## TVHeadend Einträge

- IPTV M3U: `http://CONTAINER_IP:9000/tvheadend?region=DE`
- EPG XMLTV: `http://CONTAINER_IP:9000/epg`
- Optional stabile M3U: `http://CONTAINER_IP:8080/pluto_stable.m3u`

## WebUI Funktionen
- Dashboard: Pluto up/down, M3U/EPG Checks, Ports/Uptime
- Settings: Region/Port/Bind etc. in `/data/config.json`
- Logs: `journalctl -u plutotv` (paginiert/filterbar)
- Diagnostics: Channel testen (HTTP+ffprobe), Stable Playlist erzeugen

## Troubleshooting

- **Falscher Port (8787 vs 9000 vs 8080)**
  - Pluto immer auf `9000`, WebUI auf `8080`.
- **Nur localhost bind / localonly**
  - Prüfen, ob Port offen ist: `ss -ltnp | grep -E ':9000|:8080'`
- **"device not available" Overlay**
  - Diagnostics ausführen und Stable Playlist verwenden.
- **TVHeadend cached alte Playlist**
  - In TVHeadend Muxes/Networks rescan, ggf. IPTV Auto-Refresh anstoßen.

## Update

```bash
cd /opt/tvhub
git pull
./setup.sh
```

## Dateien
- Pluto service: `systemd/plutotv.service`
- WebUI service: `systemd/pluto-gateway-ui.service`
- Installer: `setup.sh`, `install.sh`, `scripts/install.sh`
