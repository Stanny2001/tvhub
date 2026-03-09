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

## Schritt-für-Schritt Installation (Ubuntu 22.04/24.04)
1. **Code in den Container kopieren** (z. B. nach `/workspace/tvhub`).
2. **Als root installieren:**
   ```bash
   cd /workspace/tvhub
   ./scripts/install.sh
   ```
3. **Prüfen, ob Services laufen:**
   ```bash
   systemctl status plutotv
   systemctl status pluto-gateway-ui
   ```
4. **API Schnelltest:**
   ```bash
   curl -s http://127.0.0.1:8788/api/health
   curl -s http://127.0.0.1:8788/api/status
   ```
5. **WebUI öffnen:**
   - `http://CONTAINER_IP:8788`

## TVHeadend eintragen
### Option A – Direkt Pluto
- M3U: `http://CONTAINER_IP:9000/tvheadend?region=DE`
- EPG: `http://CONTAINER_IP:9000/epg`

### Option B – Stabilisierte Playlist (empfohlen bei Aussetzern)
1. In der UI → **Diagnostics** → **Generate stable playlist**.
2. In TVHeadend als M3U nutzen:
   - `http://CONTAINER_IP:8788/pluto_stable.m3u`
3. EPG bleibt:
   - `http://CONTAINER_IP:9000/epg`

## Troubleshooting
- **404 auf `/tvheadend`**: Pluto läuft nicht oder falscher Port in Config.
- **EPG OK, Streams failen**: Kanaldiagnose aufrufen; auf HTTP/ffprobe-Fehler achten.
- **"not available on this device" Overlay**: Betroffene Kanäle ausfiltern via Stable Playlist.
- **Restart/Logs schlagen fehl**: sudoers-Datei prüfen (`/etc/sudoers.d/pluto-gateway-ui`).
- **Nicht erreichbar von extern**: Container-Firewall/NAT/Bind-Adresse prüfen.

## Dev-Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] httpx pydantic
uvicorn app.main:app --host 0.0.0.0 --port 8788 --reload
```
