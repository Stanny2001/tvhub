# PlutoTV → TVHeadend Gateway UI

Lightweight FastAPI web UI for managing and diagnosing a PlutoTV local server (Perl/systemd) used by TVHeadend.

## Features
- Config persisted in `/data/config.json`
- API endpoints:
  - `GET /api/status`
  - `GET/PUT /api/config`
  - `POST /api/restart`
  - `GET /api/logs`
  - `GET /api/health`
  - `GET /api/channels`
  - `POST /api/channels/{id}/test`
  - `POST /api/stable-playlist/generate`
  - `GET /pluto_stable.m3u`
- M3U parsing from Pluto `/tvheadend`
- Channel diagnostics with HTTP timing + `ffprobe`
- Stable playlist generation from working channels only
- Minimal SPA dashboard, settings, logs, diagnostics

## Install on Ubuntu container (22.04/24.04)
1. Clone/copy this repository into container.
2. Run install script as root:
   ```bash
   cd /workspace/tvhub
   ./scripts/install.sh
   ```
3. Verify service:
   ```bash
   systemctl status pluto-gateway-ui
   curl -s http://127.0.0.1:8788/api/health
   ```

## TVHeadend URLs
Use the Pluto local server endpoints directly, or the generated stable playlist.

- Normal M3U: `http://CONTAINER_IP:9000/tvheadend?region=DE`
- EPG XMLTV: `http://CONTAINER_IP:9000/epg`
- Stable M3U (generated in UI): `http://CONTAINER_IP:8788/pluto_stable.m3u`

## systemd integration
- UI unit file: `systemd/pluto-gateway-ui.service`
- Sudoers drop-in: `systemd/pluto-gateway-ui.sudoers`

If Pluto service name differs, adjust API command usage in `app/main.py` and sudoers rule.

## Troubleshooting
- **404 at `/tvheadend`**: Check Pluto service and correct port in config (`/api/config`).
- **Wrong port**: Pluto usually on `9000`, UI on `8788`.
- **Local-only bind**: If Pluto binds to loopback, keep `bind_addr` at `0.0.0.0` in config and ensure container networking forwards correctly.
- **"not available on this device" overlay**: Use diagnostics page to test channels and generate stable playlist with failing channels removed.
- **EPG works but streams fail**: typically per-channel HLS/ad discontinuity issue; inspect `/api/channels/{id}/test` output for ffprobe/audio/video failures.

## Run manually (dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] httpx pydantic
uvicorn app.main:app --host 0.0.0.0 --port 8788 --reload
```
