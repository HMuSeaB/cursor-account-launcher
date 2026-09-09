"""启动器侧 Bot 网关控制（领票 + 挂路由 + 本机监听 + Cursor 改道注入）。"""

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
from bot_gateway.cursor_inject import (
    MARKER,
    InjectError,
    apply_to_files,
    default_listen_path,
    inspect_paths,
    remove_from_files,
    resolve_inject_targets,
    write_listen_config,
)
from bot_gateway.provision import ProvisionError, provision_upstream
from bot_gateway.server import STREAM_PATH

MODE_NAME = "mode.json"
PID_NAME = "gateway.pid"


def _mode_path() -> Path:
    return default_config_dir() / MODE_NAME


def _pid_path() -> Path:
    return default_config_dir() / PID_NAME


def _backup_dir() -> Path:
    return default_config_dir() / "cursor-inject-backup"


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


def _cursor_inject_targets() -> tuple[Any, list[Path]]:
    from launcher.sand_stream import build_layout

    layout = build_layout()
    return layout, resolve_inject_targets(layout.app_root)


def cursor_inject_status() -> dict[str, Any]:
    try:
        _layout, targets = _cursor_inject_targets()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "injected": False, "targets": []}
    info = inspect_paths(targets)
    return {"ok": True, "targets": [str(p) for p in targets], **info}


def inject_cursor_redirect(*, host: str, port: int) -> dict[str, Any]:
    from launcher.cursor_process import is_cursor_running

    if is_cursor_running():
        raise InjectError("请先关闭 Cursor，再启用本机网关改道（需写 JS）")
    listen_path = write_listen_config(host=host, port=port)
    _layout, targets = _cursor_inject_targets()
    if not targets:
        raise InjectError("当前 Cursor 安装缺少 agent-host / always-local（可能是 asar 或旧版本）")
    applied = apply_to_files(targets, backup_dir=_backup_dir())
    return {
        "ok": True,
        "listenConfig": str(listen_path),
        "marker": MARKER,
        **applied,
    }


def strip_cursor_redirect() -> dict[str, Any]:
    from launcher.cursor_process import is_cursor_running

    if is_cursor_running():
        raise InjectError("请先关闭 Cursor，再关闭网关改道（需剥离 JS）")
    try:
        _layout, targets = _cursor_inject_targets()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "changed": []}
    if not targets:
        return {"ok": True, "changed": [], "note": "没有可剥离的目标文件"}
    return remove_from_files(targets)


def start_gateway(*, host: str = "127.0.0.1", port: int = 8765) -> dict[str, Any]:
    live = gateway_process_status()
    if live.get("running"):
        return {"ok": True, "skipped": True, "message": "本机网关已在运行", **live}
    default_config_dir().mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("BOT_GATEWAY_HOST", host)
    env.setdefault("BOT_GATEWAY_PORT", str(port))
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
    return {
        "ok": True,
        "pid": proc.pid,
        "listen": listen,
        "streamPath": STREAM_PATH,
        "message": f"本机网关已监听 {listen}{STREAM_PATH}",
    }


def stop_gateway(*, strip_cursor: bool = True) -> dict[str, Any]:
    inject_result: Optional[dict[str, Any]] = None
    if strip_cursor:
        try:
            inject_result = strip_cursor_redirect()
        except InjectError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"剥离 Cursor 改道失败：{exc}"}

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
    return {
        "ok": True,
        "message": "已关闭本机网关并剥离 Cursor 改道",
        "cursorInject": inject_result,
    }


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
        from launcher.sand_stream import build_layout, inspect_status

        layout = build_layout()
        hits = inspect_status(layout, include_compat=False).hits
        direct_hits = int(hits.get("directStream") or 0)
    except Exception:
        direct_hits = -1
    inject = cursor_inject_status()
    listen = str(mode.get("listen") or "http://127.0.0.1:8765")
    foreign = list(inject.get("foreign") or [])
    return {
        "ok": True,
        "modeEnabled": bool(mode.get("enabled")),
        "listen": listen,
        "streamPath": STREAM_PATH,
        "localStreamUrl": listen.rstrip("/") + STREAM_PATH,
        "listenConfig": str(default_listen_path()),
        "process": proc,
        "upstreamPath": str(default_upstream_path()),
        "upstream": redacted_summary(cfg),
        "loadError": load_error or None,
        "directStreamHits": direct_hits,
        "conflictDirect": direct_hits > 0,
        "cursorInject": inject,
        "conflictForeign": bool(foreign),
        "note": (
            "领取并挂路由 → 关 Cursor → 开本机网关（会注入 applyAuthorization 指到 8765）。"
            "关网关会剥离该注入。勿与 Direct / v136 叠打。"
        ),
    }


def enable_redirect(*, host: str = "127.0.0.1", port: int = 8765) -> dict[str, Any]:
    """B：写 listen.json、注入 Cursor、启动本机网关。已有 Direct / 外置 relay 则拒绝。"""
    st = status()
    if st.get("conflictDirect"):
        return {
            "ok": False,
            "error": "检测到启动器 Direct Stream 补丁。请先点「还原」去掉 Direct，再启用 Bot 网关，避免叠打。",
            "status": st,
        }
    foreign = (st.get("cursorInject") or {}).get("foreign") or []
    # Direct 已在 conflictDirect 处理；其余外置 relay 也拒
    foreign_relay = [m for m in foreign if "DIRECT" not in m]
    if foreign_relay:
        return {
            "ok": False,
            "error": (
                "检测到外置 Box Relay 注入（"
                + ", ".join(foreign_relay)
                + "）。请先用 v136/Claimer 卸载，再启用启动器本机网关。"
            ),
            "status": st,
        }
    if not st.get("upstream", {}).get("configured"):
        return {
            "ok": False,
            "error": "还没有 Box 票。请先点「领取并挂路由」，再开本机网关。",
            "status": st,
        }

    try:
        injected = inject_cursor_redirect(host=host, port=port)
    except InjectError as exc:
        return {"ok": False, "error": str(exc), "status": st}
    except Exception as exc:
        return {"ok": False, "error": f"注入 Cursor 失败：{exc}", "status": st}

    started = start_gateway(host=host, port=port)
    if not started.get("ok"):
        try:
            strip_cursor_redirect()
        except Exception:
            pass
        return started

    listen = started.get("listen") or listen_fallback(host, port)
    write_mode(
        True,
        listen=listen,
        streamPath=STREAM_PATH,
        cursorInjected=True,
        marker=MARKER,
    )
    return {
        "ok": True,
        "message": started.get("message"),
        "listen": listen,
        "localStreamUrl": listen.rstrip("/") + STREAM_PATH,
        "cursorInject": injected,
        "status": status(),
        "note": (
            f"已注入 Cursor → {listen}{STREAM_PATH}。"
            "请重新打开 Cursor；Stream 会经本机网关转发到 Box。"
        ),
    }


def listen_fallback(host: str, port: int) -> str:
    return f"http://{host}:{port}"
