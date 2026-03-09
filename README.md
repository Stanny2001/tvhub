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

Empfohlen (robust, auch wenn `/opt/tvhub` bereits existiert):

```bash
apt-get update && apt-get install -y git curl
bash -c 'set -e; if [ -d /opt/tvhub/.git ]; then git -C /opt/tvhub fetch --all --prune; git -C /opt/tvhub checkout main || true; git -C /opt/tvhub reset --hard origin/main || true; else rm -rf /opt/tvhub; git clone https://github.com/Stanny2001/tvhub.git /opt/tvhub; fi; if [ ! -x /opt/tvhub/bootstrap.sh ] && [ ! -x /opt/tvhub/setup.sh ]; then CANDIDATE=$(git -C /opt/tvhub for-each-ref --format="%(refname:short)" refs/remotes/origin | sed "s#^origin/##" | while read -r b; do git -C /opt/tvhub ls-tree -r --name-only "origin/$b" -- setup.sh bootstrap.sh | grep -Eq "^(setup.sh|bootstrap.sh)$" && { echo "$b"; break; }; done); [ -n "$CANDIDATE" ] && git -C /opt/tvhub checkout "$CANDIDATE"; fi; cd /opt/tvhub; [ -x ./bootstrap.sh ] && exec ./bootstrap.sh; [ -x ./setup.sh ] && exec ./setup.sh; [ -x ./install.sh ] && exec ./install.sh; exec ./scripts/install.sh'
```

Klassisch (frischer Host ohne vorhandenes `/opt/tvhub`):

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
- **`fatal: destination path 'tvhub' already exists` + `./setup.sh: No such file`**
  - Das passiert, wenn `git clone` fehlschlägt und du danach in einem alten/unvollständigen Ordner landest.
  - Zusätzlich kann `origin/main` noch auf einem Minimal-Commit stehen, in dem `setup.sh/bootstrap.sh` fehlen.
  - Fix (holt zuerst alles und wechselt bei Bedarf automatisch auf einen Branch mit Installer-Dateien):
    ```bash
    apt-get update && apt-get install -y git curl
    bash -c 'set -e; if [ -d /opt/tvhub/.git ]; then git -C /opt/tvhub fetch --all --prune; git -C /opt/tvhub checkout main || true; git -C /opt/tvhub reset --hard origin/main || true; else rm -rf /opt/tvhub; git clone https://github.com/Stanny2001/tvhub.git /opt/tvhub; fi; if [ ! -x /opt/tvhub/bootstrap.sh ] && [ ! -x /opt/tvhub/setup.sh ]; then CANDIDATE=$(git -C /opt/tvhub for-each-ref --format="%(refname:short)" refs/remotes/origin | sed "s#^origin/##" | while read -r b; do git -C /opt/tvhub ls-tree -r --name-only "origin/$b" -- setup.sh bootstrap.sh | grep -Eq "^(setup.sh|bootstrap.sh)$" && { echo "$b"; break; }; done); [ -n "$CANDIDATE" ] && git -C /opt/tvhub checkout "$CANDIDATE"; fi; cd /opt/tvhub; [ -x ./bootstrap.sh ] && exec ./bootstrap.sh; [ -x ./setup.sh ] && exec ./setup.sh; [ -x ./install.sh ] && exec ./install.sh; exec ./scripts/install.sh'
    ```

## Update

```bash
cd /opt/tvhub
git pull
./setup.sh
```

## Dateien
- Pluto service: `systemd/plutotv.service`
- WebUI service: `systemd/pluto-gateway-ui.service`
- Installer: `bootstrap.sh`, `setup.sh`, `install.sh`, `scripts/install.sh`
