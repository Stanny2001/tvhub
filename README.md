# PlutoTV → TVHeadend Gateway UI

Robustes FastAPI-WebUI für einen PlutoTV-Localserver (Perl/systemd) im Ubuntu-Container.

## Was das Projekt liefert
- Persistente Konfiguration in `/data/config.json`
- Status/Health-Endpunkte für Pluto M3U + EPG
- Restart/Status/Journal-Integration für `plutotv` systemd-Service
- Kanalliste aus `/tvheadend` M3U parsen
- Kanaldiagnose per HTTP + `ffprobe` (Audio/Video vorhanden?)
- Stabile Playlist mit nur funktionsfähigen Kanälen (`/pluto_stable.m3u`)
- Tägliche automatische Stable-Playlist-Neugenerierung
- WebUI: Dashboard, Settings, Logs (mit Paging/Filter), Diagnostics

## API Übersicht
- `GET /api/status` – Service/Ports/Uptime/Checks
- `GET /api/config` / `PUT /api/config`
- `POST /api/restart`
- `GET /api/logs?since=...&page=1&page_size=120&q=error`
- `GET /api/health`
- `GET /api/channels`
- `POST /api/channels/{id}/test`
- `POST /api/stable-playlist/generate`
- `GET /pluto_stable.m3u`

---

## Komplette Installationsanweisung (Ubuntu 22.04/24.04)

### 0) Voraussetzungen prüfen
Der Container sollte haben:
- laufenden Pluto-Dienst (`plutotv`) auf Port `9000`
- Netzwerkzugriff vom TVHeadend-Host auf den Container
- root-Rechte für Installation

Schnellcheck:
```bash
systemctl status plutotv
curl -I http://127.0.0.1:9000/tvheadend?region=DE
curl -I http://127.0.0.1:9000/epg
```

### 1) Pakete installieren
```bash
apt-get update
apt-get install -y git curl
```

### 2) Projekt von GitHub holen
```bash
cd /opt
git clone https://github.com/Stanny2001/tvhub.git
cd tvhub
```

Optional auf bestimmten Branch wechseln:
```bash
git checkout <branch-name>
```

### 3) Gateway installieren
```bash
./scripts/install.sh
```

Das Script macht automatisch:
- installiert Python/venv/ffmpeg/sudo/iproute2
- erstellt Service-User `plutogw`
- installiert App nach `/opt/pluto-gateway-ui`
- erstellt Python-venv und installiert Dependencies
- installiert systemd Unit + sudoers-Regel
- startet und aktiviert `pluto-gateway-ui.service`

### 4) Installation verifizieren
```bash
systemctl status pluto-gateway-ui --no-pager
journalctl -u pluto-gateway-ui -n 50 --no-pager
curl -s http://127.0.0.1:8788/api/health
curl -s http://127.0.0.1:8788/api/status
```

### 5) WebUI aufrufen
- Im Browser: `http://CONTAINER_IP:8788`

Empfohlener Erst-Check in der UI:
1. Dashboard öffnen
2. prüfen, ob Pluto-Service `RUNNING` ist
3. prüfen, ob M3U/EPG `OK` sind
4. unter Diagnostics einmal „Generate stable playlist“ ausführen

### 6) TVHeadend eintragen

#### Option A: Direkt Pluto (Standard)
- M3U: `http://CONTAINER_IP:9000/tvheadend?region=DE`
- EPG: `http://CONTAINER_IP:9000/epg`

#### Option B: Stabilisierte Playlist (empfohlen bei Aussetzern)
1. In der UI → **Diagnostics** → **Generate stable playlist**.
2. In TVHeadend als M3U eintragen:
   - `http://CONTAINER_IP:8788/pluto_stable.m3u`
3. EPG bleibt:
   - `http://CONTAINER_IP:9000/epg`

---

## Betrieb / Wartung

### Konfiguration ändern
- Über UI (Settings) oder API:
```bash
curl -s http://127.0.0.1:8788/api/config
```

### Pluto-Dienst über Gateway neu starten
```bash
curl -X POST http://127.0.0.1:8788/api/restart
```

### Logs lesen
```bash
curl -s 'http://127.0.0.1:8788/api/logs?since=2%20hours%20ago&page=1&page_size=120'
```

### Stable Playlist manuell neu erzeugen
```bash
curl -X POST http://127.0.0.1:8788/api/stable-playlist/generate
curl -I http://127.0.0.1:8788/pluto_stable.m3u
```

---

## Update-Anleitung
```bash
cd /opt/tvhub
git pull
./scripts/install.sh
systemctl restart pluto-gateway-ui
```

Prüfen:
```bash
curl -s http://127.0.0.1:8788/api/status
```

---

## Deinstallation
```bash
systemctl disable --now pluto-gateway-ui
rm -f /etc/systemd/system/pluto-gateway-ui.service
rm -f /etc/sudoers.d/pluto-gateway-ui
systemctl daemon-reload
rm -rf /opt/pluto-gateway-ui
```

Optional Daten entfernen:
```bash
rm -rf /data/config.json /data/diagnostics.json /data/pluto_stable.m3u
```

---

## Troubleshooting
- **404 auf `/tvheadend`**: Pluto läuft nicht oder falscher Port in Config.
- **EPG OK, Streams failen**: Kanaldiagnose aufrufen; auf HTTP/ffprobe-Fehler achten.
- **"not available on this device" Overlay**: Betroffene Kanäle ausfiltern via Stable Playlist.
- **Restart/Logs schlagen fehl**: sudoers-Datei prüfen (`/etc/sudoers.d/pluto-gateway-ui`).
- **Nicht erreichbar von extern**: Container-Firewall/NAT/Bind-Adresse prüfen.
- **TVHeadend sieht nichts**: von TVHeadend-Host testen:
  ```bash
  curl -I http://CONTAINER_IP:9000/tvheadend?region=DE
  curl -I http://CONTAINER_IP:9000/epg
  curl -I http://CONTAINER_IP:8788/pluto_stable.m3u
  ```

## Dev-Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] httpx pydantic
uvicorn app.main:app --host 0.0.0.0 --port 8788 --reload
```
