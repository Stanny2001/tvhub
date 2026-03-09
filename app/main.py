import asyncio
import json
import os
import re
import shlex
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator

APP_VERSION = "0.3.0"
DATA_DIR = Path(os.getenv("PLUTO_GATEWAY_DATA_DIR", "/data"))
CONFIG_PATH = DATA_DIR / "config.json"
STABLE_M3U_PATH = DATA_DIR / "pluto_stable.m3u"
DIAG_STATE_PATH = DATA_DIR / "diagnostics.json"
UI_START_TIME = time.time()
PLUTO_SERVICE = os.getenv("PLUTO_SERVICE_NAME", "plutotv")
AUTO_STABLE_INTERVAL_S = 86400
UI_PORT = int(os.getenv("PLUTO_UI_PORT", "8080"))


class GatewayConfig(BaseModel):
    region: str = "DE"
    bind_addr: str = "0.0.0.0"
    port: int = 9000
    cache_ttl: int = 300
    user_agent: str = "Mozilla/5.0 (TVHeadend Pluto Gateway)"
    extra_headers: dict[str, str] = Field(default_factory=dict)
    epg_refresh: int = 3600
    logging_level: str = "INFO"
    enable_stream_proxy: bool = False

    @field_validator("port")
    @classmethod
    def valid_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError("port must be between 1 and 65535")
        return value


class ConfigPatch(BaseModel):
    region: str | None = None
    bind_addr: str | None = None
    port: int | None = None
    cache_ttl: int | None = None
    user_agent: str | None = None
    extra_headers: dict[str, str] | None = None
    epg_refresh: int | None = None
    logging_level: str | None = None
    enable_stream_proxy: bool | None = None


class ChannelDiagnostic(BaseModel):
    channel_id: str
    name: str
    stream_url: str
    checked_at: float
    ok: bool
    http_code: int | None = None
    latency_ms: float | None = None
    redirects: int | None = None
    ffprobe_ok: bool | None = None
    ffprobe_summary: str | None = None
    error: str | None = None


@dataclass
class Channel:
    channel_id: str
    name: str
    logo: str | None
    group: str | None


def now_ts() -> float:
    return time.time()


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> GatewayConfig:
    ensure_data_dir()
    if not CONFIG_PATH.exists():
        cfg = GatewayConfig()
        save_config(cfg)
        return cfg
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return GatewayConfig(**payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"Invalid config at {CONFIG_PATH}: {exc}") from exc


def save_config(cfg: GatewayConfig) -> None:
    ensure_data_dir()
    CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")


async def run_cmd(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"timeout running: {' '.join(shlex.quote(c) for c in cmd)}"


async def run_privileged(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    if os.geteuid() == 0:
        return await run_cmd(cmd, timeout=timeout)
    return await run_cmd(["sudo", *cmd], timeout=timeout)


def build_headers(cfg: GatewayConfig) -> dict[str, str]:
    return {"User-Agent": cfg.user_agent, **cfg.extra_headers}


def pluto_base_url(cfg: GatewayConfig) -> str:
    target_host = "127.0.0.1" if cfg.bind_addr == "0.0.0.0" else cfg.bind_addr
    return f"http://{target_host}:{cfg.port}"


async def fetch_health(url: str, headers: dict[str, str]) -> dict[str, Any]:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
        return {
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def parse_m3u(text: str) -> list[Channel]:
    channels: list[Channel] = []
    current_meta = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            current_meta = line
            continue
        if line.startswith("http") and "/stream/" in line:
            match = re.search(r"/stream/([^/.]+)", line)
            if not match:
                continue
            channel_id = match.group(1)
            name = current_meta.split(",", maxsplit=1)[-1] if "," in current_meta else channel_id
            logo = re.search(r'tvg-logo="([^"]+)"', current_meta)
            group = re.search(r'group-title="([^"]+)"', current_meta)
            channels.append(
                Channel(
                    channel_id=channel_id,
                    name=name.strip(),
                    logo=logo.group(1) if logo else None,
                    group=group.group(1) if group else None,
                )
            )
    return channels


async def get_channels(cfg: GatewayConfig) -> list[Channel]:
    m3u_url = f"{pluto_base_url(cfg)}/tvheadend?region={cfg.region}"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(m3u_url, headers=build_headers(cfg))
        resp.raise_for_status()
    return parse_m3u(resp.text)


async def probe_stream(url: str, headers: dict[str, str]) -> tuple[bool, str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "-headers",
        "".join(f"{k}: {v}\r\n" for k, v in headers.items()),
        "-i",
        url,
    ]
    code, out, err = await run_cmd(cmd, timeout=20)
    streams = [s.strip() for s in out.splitlines() if s.strip()]
    ok = code == 0 and "video" in streams and "audio" in streams
    summary = f"streams={streams}" if streams else err.strip() or "no stream entries"
    return ok, summary


async def test_channel(cfg: GatewayConfig, channel: Channel) -> ChannelDiagnostic:
    url = f"{pluto_base_url(cfg)}/stream/{channel.channel_id}.m3u8"
    headers = build_headers(cfg)
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=18.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
        latency = round((time.monotonic() - start) * 1000, 2)
        ff_ok, ff_summary = await probe_stream(url, headers)
        ok = resp.status_code == 200 and ff_ok
        return ChannelDiagnostic(
            channel_id=channel.channel_id,
            name=channel.name,
            stream_url=url,
            checked_at=now_ts(),
            ok=ok,
            http_code=resp.status_code,
            latency_ms=latency,
            redirects=len(resp.history),
            ffprobe_ok=ff_ok,
            ffprobe_summary=ff_summary,
            error=None if ok else "stream check failed",
        )
    except Exception as exc:  # noqa: BLE001
        return ChannelDiagnostic(
            channel_id=channel.channel_id,
            name=channel.name,
            stream_url=url,
            checked_at=now_ts(),
            ok=False,
            error=str(exc),
        )


def load_diag_state() -> dict[str, Any]:
    if not DIAG_STATE_PATH.exists():
        return {}
    try:
        return json.loads(DIAG_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_diag_state(payload: dict[str, Any]) -> None:
    ensure_data_dir()
    DIAG_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def generate_stable_playlist() -> dict[str, Any]:
    cfg = load_config()
    channels = await get_channels(cfg)
    diagnostics = [await test_channel(cfg, channel) for channel in channels]
    ok_ids = {d.channel_id for d in diagnostics if d.ok}
    base = pluto_base_url(cfg)
    lines = ["#EXTM3U"]
    for channel in channels:
        if channel.channel_id not in ok_ids:
            continue
        attrs = [f'tvg-id="{channel.channel_id}"']
        if channel.logo:
            attrs.append(f'tvg-logo="{channel.logo}"')
        if channel.group:
            attrs.append(f'group-title="{channel.group}"')
        lines.append(f"#EXTINF:-1 {' '.join(attrs)},{channel.name}")
        lines.append(f"{base}/stream/{channel.channel_id}.m3u8")

    ensure_data_dir()
    STABLE_M3U_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state = {
        "updated_at": now_ts(),
        "stable_count": len(ok_ids),
        "diagnostics": {d.channel_id: d.model_dump() for d in diagnostics},
    }
    save_diag_state(state)
    return {"ok": True, "stable_channels": len(ok_ids), "output": str(STABLE_M3U_PATH)}


async def daily_stable_job() -> None:
    while True:
        try:
            await generate_stable_playlist()
        except Exception:
            pass
        await asyncio.sleep(AUTO_STABLE_INTERVAL_S)


app = FastAPI(title="Pluto Gateway UI", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def on_startup() -> None:
    ensure_data_dir()
    load_config()
    app.state.stable_task = asyncio.create_task(daily_stable_job())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    task = getattr(app.state, "stable_task", None)
    if task:
        task.cancel()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/config")
async def api_get_config() -> dict[str, Any]:
    return load_config().model_dump()


@app.put("/api/config")
async def api_put_config(patch: ConfigPatch) -> dict[str, Any]:
    cfg = load_config()
    updated = cfg.model_dump()
    updated.update(patch.model_dump(exclude_none=True))
    new_cfg = GatewayConfig(**updated)
    save_config(new_cfg)
    return new_cfg.model_dump()


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    cfg = load_config()
    base = pluto_base_url(cfg)
    headers = build_headers(cfg)
    m3u_health = await fetch_health(f"{base}/tvheadend?region={cfg.region}", headers)
    epg_health = await fetch_health(f"{base}/epg", headers)

    service_rc, service_out, service_err = await run_privileged(["systemctl", "is-active", PLUTO_SERVICE])
    status_rc, status_out, status_err = await run_privileged(["systemctl", "status", PLUTO_SERVICE, "--no-pager", "--lines", "0"])
    ss_rc, ss_out, _ = await run_cmd(["ss", "-ltnp"], timeout=8)

    channels_count = 0
    if m3u_health.get("ok"):
        try:
            channels_count = len(await get_channels(cfg))
        except Exception:
            channels_count = 0

    return {
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pluto_service": {
            "name": PLUTO_SERVICE,
            "active": service_rc == 0 and service_out.strip() == "active",
            "is_active_output": service_out.strip() or service_err.strip(),
            "status_ok": status_rc == 0,
            "status_summary": (status_out or status_err).strip().splitlines()[:8],
        },
        "pluto": {
            "region": cfg.region,
            "bind_addr": cfg.bind_addr,
            "port": cfg.port,
            "channels_count": channels_count,
        },
        "checks": {"m3u": m3u_health, "epg": epg_health},
        "ports": {
            "query_ok": ss_rc == 0,
            "listeners": [line for line in ss_out.splitlines() if f":{cfg.port}" in line or f":{UI_PORT}" in line][:20],
        },
        "ui_port": UI_PORT,
        "ui_uptime_seconds": int(now_ts() - UI_START_TIME),
        "last_diagnostics_update": load_diag_state().get("updated_at"),
    }


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    cfg = load_config()
    base = pluto_base_url(cfg)
    headers = build_headers(cfg)
    m3u = await fetch_health(f"{base}/tvheadend?region={cfg.region}", headers)
    epg = await fetch_health(f"{base}/epg", headers)
    return {"ok": bool(m3u.get("ok") and epg.get("ok")), "m3u": m3u, "epg": epg}


@app.post("/api/restart")
async def api_restart() -> dict[str, Any]:
    rc, out, err = await run_privileged(["systemctl", "restart", PLUTO_SERVICE])
    if rc != 0:
        raise HTTPException(status_code=500, detail={"stdout": out, "stderr": err})
    return {"ok": True, "message": f"{PLUTO_SERVICE} restarted"}


@app.get("/api/logs")
async def api_logs(
    since: str = "1 hour ago",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    q: str | None = None,
) -> dict[str, Any]:
    rc, out, err = await run_privileged(["journalctl", "-u", PLUTO_SERVICE, "--since", since, "--no-pager", "-o", "short-iso"])
    if rc != 0:
        raise HTTPException(status_code=500, detail=err or out)
    lines = out.splitlines()
    if q:
        lines = [line for line in lines if q.lower() in line.lower()]
    total = len(lines)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "count": max(0, min(page_size, total - start)),
        "total": total,
        "page": page,
        "page_size": page_size,
        "lines": lines[start:end],
    }


@app.get("/api/channels")
async def api_channels() -> dict[str, Any]:
    channels = await get_channels(load_config())
    diags = load_diag_state().get("diagnostics", {})
    return {
        "count": len(channels),
        "channels": [
            {
                "channel_id": c.channel_id,
                "name": c.name,
                "logo": c.logo,
                "group": c.group,
                "diagnostic": diags.get(c.channel_id),
            }
            for c in channels
        ],
    }


@app.post("/api/channels/{channel_id}/test")
async def api_test_channel(channel_id: str) -> dict[str, Any]:
    cfg = load_config()
    channels = await get_channels(cfg)
    channel = next((c for c in channels if c.channel_id == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="channel not found")
    diag = await test_channel(cfg, channel)
    state = load_diag_state()
    diagnostics = state.get("diagnostics", {})
    diagnostics[channel_id] = diag.model_dump()
    state["diagnostics"] = diagnostics
    state["updated_at"] = now_ts()
    save_diag_state(state)
    return diag.model_dump()


@app.post("/api/stable-playlist/generate")
async def api_generate_stable() -> dict[str, Any]:
    return await generate_stable_playlist()


@app.get("/pluto_stable.m3u")
async def pluto_stable() -> PlainTextResponse:
    if not STABLE_M3U_PATH.exists():
        raise HTTPException(status_code=404, detail="stable playlist not generated yet")
    return PlainTextResponse(STABLE_M3U_PATH.read_text(encoding="utf-8"), media_type="audio/x-mpegurl")


@app.get("/tvheadend")
async def passthrough_tvheadend(region: str = "DE") -> PlainTextResponse:
    cfg = load_config()
    url = f"{pluto_base_url(cfg)}/tvheadend?region={region}"
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=build_headers(cfg))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"pluto upstream error: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return PlainTextResponse(resp.text, media_type="audio/x-mpegurl")


@app.get("/epg")
async def passthrough_epg() -> PlainTextResponse:
    cfg = load_config()
    url = f"{pluto_base_url(cfg)}/epg"
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=build_headers(cfg))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"pluto upstream error: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return PlainTextResponse(resp.text, media_type="application/xml")


@app.get("/api/network")
async def api_network() -> dict[str, Any]:
    hostname = socket.gethostname()
    ips = list({ai[4][0] for ai in socket.getaddrinfo(hostname, None, family=socket.AF_INET)})
    return {"hostname": hostname, "ipv4": ips}
