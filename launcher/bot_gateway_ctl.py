"""启动器侧 Bot 网关控制（A 领票 + B 本机监听 / 与 Direct 互斥）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from bot_gateway.config import (
    default_config_dir,
    default_upstream_path,
    load_upstream,
    redacted_summary,
)
from bot_gateway.provision import ProvisionError, provision_upstream
from bot_gateway.server import STREAM_PATH

MODE_NAME = "mode.json"
PID_NAME = "gateway.pid"


def _mode_path() -> Path:
    return default_config_dir() / MODE_NAME


def _pid_path() -> Path:
    return default_config_dir() / PID_NAME


def read_mode() -> dict[str, Any]:
    path = _mode_path()
    if not path.is_file():
        return {"enabled": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False}
    return data if isinstance(data, dict) else {"enabled": False}


def is_gateway_mode() -> bool:
    return bool(read_mode().get("enabled"))


def write_mode(enabled: bool, **extra: Any) -> dict[str, Any]:
    default_config_dir().mkdir(parents=True, exist_ok=True)
    payload = {"enabled": bool(enabled), "updatedAt": int(time.time()), **extra}
    _mode_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def gateway_process_status() -> dict[str, Any]:
    path = _pid_path()
    if not path.is_file():
        return {"running": False, "pid": None}
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return {"running": False, "pid": None}
    live = _pid_running(pid)
    if not live:
        return {"running": False, "pid": pid, "stale": True}
    return {"running": True, "pid": pid}


def start_gateway(*, host: str = "127.0.0.1", port: int = 8765) -> dict[str, Any]:
    live = gateway_process_status()
    if live.get("running"):
        return {"ok": True, "skipped": True, "message": "本机网关已在运行", **live}
    default_config_dir().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("BOT_GATEWAY_HOST", host)
    env.setdefault("BOT_GATEWAY_PORT", str(port))
    # 保证能 import bot_gateway
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "bot_gateway", "--host", host, "--port", str(port)],
        cwd=str(root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    _pid_path().write_text(str(proc.pid), encoding="utf-8")
    listen = f"http://{host}:{port}"
    write_mode(True, listen=listen, streamPath=STREAM_PATH)
    return {
        "ok": True,
        "pid": proc.pid,
        "listen": listen,
        "streamPath": STREAM_PATH,
        "message": f"本机网关已监听 {listen}{STREAM_PATH}",
    }


def stop_gateway() -> dict[str, Any]:
    st = gateway_process_status()
    pid = st.get("pid")
    if st.get("running") and isinstance(pid, int):
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        for _ in range(20):
            if not _pid_running(pid):
                break
            time.sleep(0.1)
        if _pid_running(pid) and os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                check=False,
            )
    try:
        _pid_path().unlink(missing_ok=True)
    except OSError:
        pass
    write_mode(False)
    return {"ok": True, "message": "已关闭本机网关改道模式"}


def provision(*, mount: bool = True, wait_seconds: float = 240) -> dict[str, Any]:
    try:
        if mount:
            from bot_gateway.box_mount import provision_and_mount

            return provision_and_mount(wait_seconds=wait_seconds)
        return provision_upstream()
    except ProvisionError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def status() -> dict[str, Any]:
    cfg = None
    load_error = ""
    try:
        cfg = load_upstream()
    except Exception as exc:
        load_error = str(exc)
    mode = read_mode()
    proc = gateway_process_status()
    direct_hits = 0
    try:
        from launcher.sand_stream import SAND_DIRECT_STREAM_MARKER, build_layout, inspect_status

        layout = build_layout()
        hits = inspect_status(layout, include_compat=False).hits
        direct_hits = int(hits.get("directStream") or 0)
    except Exception:
        direct_hits = -1
    listen = str(mode.get("listen") or "http://127.0.0.1:8765")
    return {
        "ok": True,
        "modeEnabled": bool(mode.get("enabled")),
        "listen": listen,
        "streamPath": STREAM_PATH,
        "localStreamUrl": listen.rstrip("/") + STREAM_PATH,
        "process": proc,
        "upstreamPath": str(default_upstream_path()),
        "upstream": redacted_summary(cfg),
        "loadError": load_error or None,
        "directStreamHits": direct_hits,
        "conflictDirect": direct_hits > 0,
        "note": (
            "A=领取 Box 票写入 upstream.json；B=本机监听并把 Cursor Stream 指过来。"
            "已打 Direct 时不要开 B 改道，先还原 Bot 补丁。"
        ),
    }


def enable_redirect(*, host: str = "127.0.0.1", port: int = 8765) -> dict[str, Any]:
    """B：启动本机网关并打开改道模式。已有 Direct 则拒绝。"""
    st = status()
    if st.get("conflictDirect"):
        return {
            "ok": False,
            "error": "检测到启动器 Direct Stream 补丁。请先点「还原」去掉 Direct，再启用 Bot 网关，避免叠打。",
            "status": st,
        }
    if not st.get("upstream", {}).get("configured"):
        return {
            "ok": False,
            "error": "还没有 Box 票。请先点「领取 Box 票」（A），再开本机网关。",
            "status": st,
        }
    started = start_gateway(host=host, port=port)
    if not started.get("ok"):
        return started
    return {
        "ok": True,
        "message": started.get("message"),
        "listen": started.get("listen"),
        "localStreamUrl": started.get("listen", listen_fallback(host, port)).rstrip("/") + STREAM_PATH,
        "status": status(),
        "cursorHint": (
            "本机网关已起来。Cursor 不会自动改道：需要把 Stream 指到 "
            f"{started.get('listen')}{STREAM_PATH}。"
            "本轮不注入 applyAuthorization（避免和 Direct 抢锚）。"
            "若以前用过 v136 注入，请先卸载那套，只保留本网关。"
        ),
    }


def listen_fallback(host: str, port: int) -> str:
    return f"http://{host}:{port}"
