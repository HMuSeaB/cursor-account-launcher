"""Grok Extra High 上下文窗口补丁（256k → 500k）状态 / 应用 / 还原。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from launcher.cursor_process import is_cursor_running, resolve_install

MARK_START = "/* __CTXWIN_PATCH_START__ */"
FROM_TOKENS = 256000
TO_TOKENS = 500000


def _frozen_base() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def bundled_script() -> Path:
    return _frozen_base() / "scripts" / "patch-ctxwin.mjs"


def working_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "scripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def working_script() -> Path:
    return working_dir() / "patch-ctxwin.mjs"


def ensure_working_script() -> Path:
    dest = working_script()
    src = bundled_script()
    if src.is_file():
        if (not dest.is_file()) or src.stat().st_size != dest.stat().st_size or src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
        return dest
    if dest.is_file():
        return dest
    raise FileNotFoundError("找不到 patch-ctxwin.mjs。请确认启动器 scripts 目录完整。")


def find_node() -> Path | None:
    which = shutil.which("node")
    if which:
        return Path(which)
    extra = [
        Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "node" / "node.exe",
    ]
    for cand in extra:
        if cand.is_file():
            return cand
    return None


def app_root_for(layout) -> Path:
    return Path(layout.install_root) / "resources" / "app"


def host_js_path(app_root: Path) -> Path:
    return app_root / "out" / "vs" / "workbench" / "api" / "node" / "extensionHostProcess.js"


def file_has_patch(path: Path) -> bool:
    if not path.is_file():
        return False
    needle = MARK_START.encode("ascii")
    with path.open("rb") as handle:
        chunk = handle.read(256 * 1024)
        if needle in chunk:
            return True
        while True:
            more = handle.read(1024 * 1024)
            if not more:
                return False
            # 标记可能跨块：保留尾部重叠
            window = chunk[-len(needle) :] + more
            if needle in window:
                return True
            chunk = more


def ctxwin_status() -> dict:
    node = find_node()
    running = is_cursor_running()
    try:
        layout = resolve_install()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "patched": False,
            "running": running,
            "from": FROM_TOKENS,
            "to": TO_TOKENS,
            "node": str(node) if node else "",
        }
    app_root = app_root_for(layout)
    host = host_js_path(app_root)
    exists = host.is_file()
    patched = file_has_patch(host) if exists else False
    return {
        "ok": True,
        "patched": patched,
        "running": running,
        "exists": exists,
        "hostPath": str(host),
        "appRoot": str(app_root),
        "version": layout.version,
        "from": FROM_TOKENS,
        "to": TO_TOKENS,
        "node": str(node) if node else "",
        "canApply": bool(node) and exists and not running,
        "canRestore": patched and not running,
    }


def _run(cmd: str) -> dict:
    node = find_node()
    if not node:
        return {"ok": False, "error": "未找到 Node.js。打补丁需要本机 node 在 PATH 上。"}
    if is_cursor_running():
        return {"ok": False, "error": "目前 Cursor 正在运行，文件被占用。请先点「关闭 IDE」。", "running": True}
    try:
        script = ensure_working_script()
        layout = resolve_install()
        app_root = app_root_for(layout)
        host = host_js_path(app_root)
        if not host.is_file():
            return {"ok": False, "error": f"找不到 extensionHostProcess.js：{host}"}
        env = os.environ.copy()
        env["CURSOR_APP_ROOT"] = str(app_root)
        result = subprocess.run(
            [str(node), str(script), cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            env=env,
            cwd=str(script.parent),
            check=False,
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if result.returncode != 0:
            return {"ok": False, "error": output or f"node 退出码 {result.returncode}", "output": output}
        status = ctxwin_status()
        status["output"] = output
        status["ok"] = True
        return status
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ctxwin_apply() -> dict:
    return _run("apply")


def ctxwin_restore() -> dict:
    status = ctxwin_status()
    if status.get("ok") and not status.get("patched"):
        status["skipped"] = True
        status["message"] = "当前未打补丁，无需还原"
        return status
    return _run("restore")
