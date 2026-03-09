import asyncio
import json
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

APP_VERSION = "0.1.0"
DATA_DIR = Path("/data")
CONFIG_PATH = DATA_DIR / "config.json"
STABLE_M3U_PATH = DATA_DIR / "pluto_stable.m3u"
DIAG_STATE_PATH = DATA_DIR / "diagnostics.json"


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


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> GatewayConfig:
    ensure_data_dir()
    if not CONFIG_PATH.exists():
        cfg = GatewayConfig()
        CONFIG_PATH.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
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
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", f"timeout running: {' '.join(shlex.quote(c) for c in cmd)}"


async def fetch_health(url: str, headers: dict[str, str]) -> dict[str, Any]:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        return {
            "ok": r.status_code == 200,
            "status_code": r.status_code,
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
            m = re.search(r"/stream/([^/.]+)", line)
            if not m:
                continue
            cid = m.group(1)
            name = current_meta.split(",", maxsplit=1)[-1] if "," in current_meta else cid
            logo = re.search(r'tvg-logo="([^"]+)"', current_meta)
            group = re.search(r'group-title="([^"]+)"', current_meta)
            channels.append(
                Channel(
                    channel_id=cid,
                    name=name.strip(),
                    logo=logo.group(1) if logo else None,
                    group=group.group(1) if group else None,
                )
            )
    return channels


async def pluto_base_url(cfg: GatewayConfig) -> str:
    bind = "127.0.0.1" if cfg.bind_addr == "0.0.0.0" else cfg.bind_addr
    return f"http://{bind}:{cfg.port}"


async def get_channels(cfg: GatewayConfig) -> list[Channel]:
    base = await pluto_base_url(cfg)
    m3u_url = f"{base}/tvheadend?region={cfg.region}"
    headers = {"User-Agent": cfg.user_agent, **cfg.extra_headers}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(m3u_url, headers=headers)
        r.raise_for_status()
    return parse_m3u(r.text)


async def test_channel(cfg: GatewayConfig, channel: Channel) -> ChannelDiagnostic:
    base = await pluto_base_url(cfg)
    url = f"{base}/stream/{channel.channel_id}.m3u8"
    headers = {"User-Agent": cfg.user_agent, **cfg.extra_headers}
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=18.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
        latency = round((time.monotonic() - start) * 1000, 2)
        ffprobe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            "-i",
            url,
        ]
        code, out, err = await run_cmd(ffprobe_cmd, timeout=20)
        streams = [s.strip() for s in out.splitlines() if s.strip()]
        has_audio = "audio" in streams
        has_video = "video" in streams
        ff_ok = code == 0 and has_audio and has_video
        summary = f"streams={streams}" if streams else (err.strip() or "no streams")
        ok = resp.status_code == 200 and ff_ok
        return ChannelDiagnostic(
            channel_id=channel.channel_id,
            name=channel.name,
            stream_url=url,
            checked_at=time.time(),
            ok=ok,
            http_code=resp.status_code,
            latency_ms=latency,
            redirects=len(resp.history),
            ffprobe_ok=ff_ok,
            ffprobe_summary=summary,
            error=None if ok else "stream check failed",
        )
    except Exception as exc:  # noqa: BLE001
        return ChannelDiagnostic(
            channel_id=channel.channel_id,
            name=channel.name,
            stream_url=url,
            checked_at=time.time(),
            ok=False,
            error=str(exc),
        )


def load_diag_state() -> dict[str, Any]:
    if DIAG_STATE_PATH.exists():
        try:
            return json.loads(DIAG_STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_diag_state(payload: dict[str, Any]) -> None:
    ensure_data_dir()
    DIAG_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


app = FastAPI(title="Pluto Gateway UI", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/api/config")
async def api_get_config() -> dict[str, Any]:
    return load_config().model_dump()


@app.put("/api/config")
async def api_put_config(patch: ConfigPatch) -> dict[str, Any]:
    cfg = load_config()
    updates = patch.model_dump(exclude_none=True)
    merged = cfg.model_dump()
    merged.update(updates)
    new_cfg = GatewayConfig(**merged)
    save_config(new_cfg)
    return new_cfg.model_dump()


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    cfg = load_config()
    base = await pluto_base_url(cfg)
    health_m3u = await fetch_health(f"{base}/tvheadend?region={cfg.region}", {"User-Agent": cfg.user_agent, **cfg.extra_headers})
    health_epg = await fetch_health(f"{base}/epg", {"User-Agent": cfg.user_agent, **cfg.extra_headers})
    rc, out, err = await run_cmd(["systemctl", "is-active", "plutotv"])
    channels_count = 0
    last_refresh = None
    if health_m3u.get("ok"):
        try:
            channels_count = len(await get_channels(cfg))
            last_refresh = time.time()
        except Exception:  # noqa: BLE001
            pass
    return {
        "version": APP_VERSION,
        "pluto_service_active": rc == 0 and out.strip() == "active",
        "systemctl": out.strip() or err.strip(),
        "region": cfg.region,
        "pluto_port": cfg.port,
        "bind_addr": cfg.bind_addr,
        "channels_count": channels_count,
        "last_refresh": last_refresh,
        "m3u": health_m3u,
        "epg": health_epg,
        "uptime_seconds": int(time.time() - Path('/proc/1').stat().st_ctime),
    }


@app.post("/api/restart")
async def api_restart() -> dict[str, Any]:
    rc, out, err = await run_cmd(["sudo", "systemctl", "restart", "plutotv"])
    if rc != 0:
        raise HTTPException(status_code=500, detail={"stdout": out, "stderr": err})
    return {"ok": True, "message": "plutotv restarted"}


@app.get("/api/logs")
async def api_logs(since: str = "1 hour ago", limit: int = Query(default=200, le=2000)) -> dict[str, Any]:
    rc, out, err = await run_cmd(["sudo", "journalctl", "-u", "plutotv", "--since", since, "-n", str(limit), "--no-pager"])
    if rc != 0:
        raise HTTPException(status_code=500, detail=err or out)
    lines = out.splitlines()
    return {"count": len(lines), "lines": lines}


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    cfg = load_config()
    base = await pluto_base_url(cfg)
    headers = {"User-Agent": cfg.user_agent, **cfg.extra_headers}
    m3u = await fetch_health(f"{base}/tvheadend?region={cfg.region}", headers)
    epg = await fetch_health(f"{base}/epg", headers)
    ok = bool(m3u.get("ok") and epg.get("ok"))
    return {"ok": ok, "m3u": m3u, "epg": epg}


@app.get("/api/channels")
async def api_channels() -> dict[str, Any]:
    cfg = load_config()
    channels = await get_channels(cfg)
    state = load_diag_state()
    diags = state.get("diagnostics", {})
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
    ch = next((c for c in channels if c.channel_id == channel_id), None)
    if not ch:
        raise HTTPException(status_code=404, detail="channel not found")
    diag = await test_channel(cfg, ch)
    state = load_diag_state()
    d = state.get("diagnostics", {})
    d[channel_id] = diag.model_dump()
    state["diagnostics"] = d
    state["updated_at"] = time.time()
    save_diag_state(state)
    return diag.model_dump()


@app.post("/api/stable-playlist/generate")
async def api_generate_stable() -> dict[str, Any]:
    cfg = load_config()
    channels = await get_channels(cfg)
    diags: list[ChannelDiagnostic] = []
    for channel in channels:
        diags.append(await test_channel(cfg, channel))
    ok_ids = {d.channel_id for d in diags if d.ok}
    base = await pluto_base_url(cfg)
    lines = ["#EXTM3U"]
    for c in channels:
        if c.channel_id not in ok_ids:
            continue
        attrs = [f'tvg-id="{c.channel_id}"']
        if c.logo:
            attrs.append(f'tvg-logo="{c.logo}"')
        if c.group:
            attrs.append(f'group-title="{c.group}"')
        lines.append(f"#EXTINF:-1 {' '.join(attrs)},{c.name}")
        lines.append(f"{base}/stream/{c.channel_id}.m3u8")
    ensure_data_dir()
    STABLE_M3U_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state = {
        "updated_at": time.time(),
        "diagnostics": {d.channel_id: d.model_dump() for d in diags},
        "stable_count": len(ok_ids),
    }
    save_diag_state(state)
    return {"ok": True, "stable_channels": len(ok_ids), "output": str(STABLE_M3U_PATH)}


@app.get("/pluto_stable.m3u")
async def pluto_stable() -> PlainTextResponse:
    if not STABLE_M3U_PATH.exists():
        raise HTTPException(status_code=404, detail="stable playlist not generated yet")
    return PlainTextResponse(STABLE_M3U_PATH.read_text(encoding="utf-8"), media_type="audio/x-mpegurl")
