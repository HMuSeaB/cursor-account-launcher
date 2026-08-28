"""进程级代理：沿用 Antigravity-Proxy 的 version.dll（MinHook），不靠 TUN。

把 ``version.dll`` + ``config.json`` 放到 Cursor.exe 同目录，进程加载时 hook
Winsock，只影响 Cursor 及其子进程。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

MARKER = "CursorLauncher"
DLL_NAME = "version.dll"
CONFIG_NAME = "config.json"

DEFAULT_DLL_CANDIDATES = (
    Path(r"d:\4rchive\AI\antigravity\antigravity-proxy\version.dll"),
    Path(__file__).resolve().parent.parent / "vendor" / "process-proxy" / "version.dll",
)


def _state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "process-proxy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_dll_source(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    cached = _state_dir() / DLL_NAME
    if cached.is_file():
        return cached
    for cand in DEFAULT_DLL_CANDIDATES:
        if cand.is_file():
            return cand
    return None


def build_hook_config(*, host: str, port: int, proxy_type: str) -> dict:
    ptype = "socks5" if str(proxy_type).lower().startswith("socks") else "http"
    return {
        "_comment": "Cursor Launcher 进程代理（Antigravity-Proxy / MinHook）",
        "_managed_by": MARKER,
        "_version": "2.0",
        "log_level": "info",
        "traffic_logging": False,
        "child_injection": True,
        # inherit：Cursor 会拉起 cursor-bridge / Network 等子进程，全部注入才能堵住直连
        "child_injection_mode": "inherit",
        "child_injection_exclude": [],
        "target_processes": [
            "Cursor.exe",
            "cursor-bridge.exe",
            "Cursor Helper.exe",
            "Cursor Helper (Network).exe",
            "Cursor Helper (Renderer).exe",
            "Cursor Helper (GPU).exe",
        ],
        "proxy": {
            "host": host or "127.0.0.1",
            "port": int(port or 7891),
            "type": ptype,
        },
        "fake_ip": {"enabled": True, "cidr": "198.18.0.0/15"},
        "timeout": {"connect": 5000, "send": 5000, "recv": 5000},
        "proxy_rules": {
            "allowed_ports": [80, 443],
            "dns_mode": "direct",
            "ipv6_mode": "proxy",
            # 禁 UDP，逼 QUIC/HTTP3 走 TCP，才能进 SOCKS/HTTP 代理
            "udp_mode": "block",
            "udp_fallback": "block",
            "routing": {
                "enabled": True,
                "priority_mode": "order",
                "default_action": "proxy",
                "use_default_private": True,
                "rules": [],
            },
        },
    }


def status(install_root: Path) -> dict:
    root = Path(install_root)
    dll = root / DLL_NAME
    cfg = root / CONFIG_NAME
    managed = False
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            managed = data.get("_managed_by") == MARKER
        except Exception:
            managed = False
    src = resolve_dll_source()
    return {
        "ok": True,
        "installed": dll.is_file() and cfg.is_file(),
        "managed": managed,
        "dll": str(dll) if dll.is_file() else "",
        "config": str(cfg) if cfg.is_file() else "",
        "dllSource": str(src) if src else "",
        "hasDllSource": bool(src),
    }


def deploy_process_proxy(
    install_root: Path,
    *,
    host: str,
    port: int,
    proxy_type: str,
    dll_source: str | None = None,
) -> dict:
    root = Path(install_root)
    if not root.is_dir():
        return {"ok": False, "error": f"安装目录不存在：{root}"}
    src = resolve_dll_source(dll_source)
    if not src:
        return {
            "ok": False,
            "error": (
                "找不到 version.dll。请把 Antigravity-Proxy 的 version.dll 放到 "
                r"d:\4rchive\AI\antigravity\antigravity-proxy\ "
                "或启动器 vendor\\process-proxy\\"
            ),
        }
    try:
        cached = _state_dir() / DLL_NAME
        if src.resolve() != cached.resolve():
            shutil.copy2(src, cached)
            src = cached
        dest_dll = root / DLL_NAME
        dest_cfg = root / CONFIG_NAME
        # 已有别人的 version.dll 且不是我们管的，别覆盖
        existing_cfg = {}
        if dest_cfg.is_file():
            try:
                existing_cfg = json.loads(dest_cfg.read_text(encoding="utf-8"))
            except Exception:
                existing_cfg = {}
        managed_by = existing_cfg.get("_managed_by")
        if dest_dll.is_file() and managed_by != MARKER:
            return {
                "ok": False,
                "error": "Cursor 目录已有 version.dll（非本工具管理），已跳过。请手动处理后再试",
            }
        shutil.copy2(src, dest_dll)
        cfg = build_hook_config(host=host, port=port, proxy_type=proxy_type)
        tmp = dest_cfg.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(dest_cfg)
        return {
            "ok": True,
            "dll": str(dest_dll),
            "config": str(dest_cfg),
            "proxy": cfg["proxy"],
            "message": "已写入进程代理 DLL（仅 Cursor，非 TUN）",
        }
    except PermissionError:
        return {"ok": False, "error": "无法写入 Cursor 目录，请先关闭 IDE 或以足够权限重试"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def remove_process_proxy(install_root: Path) -> dict:
    root = Path(install_root)
    dest_dll = root / DLL_NAME
    dest_cfg = root / CONFIG_NAME
    if not dest_cfg.is_file() and not dest_dll.is_file():
        return {"ok": True, "removed": False, "message": "未安装进程代理"}
    managed = False
    if dest_cfg.is_file():
        try:
            managed = json.loads(dest_cfg.read_text(encoding="utf-8")).get("_managed_by") == MARKER
        except Exception:
            managed = False
    if dest_dll.is_file() and not managed:
        return {"ok": False, "error": "检测到非本工具的 version.dll，未删除"}
    removed = []
    try:
        if dest_cfg.is_file() and managed:
            dest_cfg.unlink()
            removed.append(CONFIG_NAME)
        if dest_dll.is_file() and managed:
            dest_dll.unlink()
            removed.append(DLL_NAME)
        return {"ok": True, "removed": bool(removed), "files": removed}
    except PermissionError:
        return {"ok": False, "error": "文件被占用，请先关闭 Cursor 再移除"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
