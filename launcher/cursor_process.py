"""Cursor 进程检测、关闭与 IDE 模式启动。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CURSOR_START_ARGS = ("--classic",)
LIGHT_START_ARGS = (
    "--classic",
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--new-window",
    "--js-flags=--max-old-space-size=1536",
)
CONFIG_VERSION = 1
LIGHT_README = """# 轻量工作区

由 Cursor Launcher 在「轻量启动」时打开。

这里几乎没有文件，Cursor 不会去索引整个大仓库，也不会加载项目里的 MCP。
打游戏挂机用这个窗口即可；写代码请再打开原来的项目文件夹。
"""


@dataclass(frozen=True)
class CursorInstall:
    install_root: Path
    executable: Path
    version: str


def _config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "CursorLauncher" / "config.json"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_config() -> dict:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def update_config(**kwargs) -> dict:
    data = _load_config()
    data.update({k: v for k, v in kwargs.items() if v is not None})
    data["version"] = CONFIG_VERSION
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _write_json(_config_path(), data)
    return data


def light_workspace_dir() -> Path:
    path = _config_path().parent / "light-workspace"
    path.mkdir(parents=True, exist_ok=True)
    readme = path / "README.md"
    if not readme.is_file():
        readme.write_text(LIGHT_README, encoding="utf-8")
    return path


def launch_args(*, light: bool = False) -> list[str]:
    if not light:
        return list(CURSOR_START_ARGS)
    return [*LIGHT_START_ARGS, str(light_workspace_dir())]


def _read_version(install_root: Path) -> str:
    product = install_root / "resources" / "app" / "product.json"
    if not product.is_file():
        app_dir = install_root / "resources" / "app"
        if app_dir.is_dir():
            product = app_dir / "product.json"
    try:
        data = json.loads(product.read_text(encoding="utf-8"))
        return str(data.get("version") or "?")
    except Exception:
        return "?"


def _layout_from_executable(exe: Path) -> CursorInstall:
    exe = exe.resolve()
    if sys.platform == "win32":
        install_root = exe.parent
        if install_root.name.lower() == "bin" and (install_root.parent / "resources").is_dir():
            install_root = install_root.parent
    elif sys.platform == "darwin":
        install_root = exe
        for _ in range(4):
            if install_root.suffix == ".app":
                break
            install_root = install_root.parent
    else:
        install_root = exe.parent
    return CursorInstall(
        install_root=install_root,
        executable=exe,
        version=_read_version(install_root),
    )


def layout_from_path(raw: str) -> CursorInstall:
    path = Path(raw.strip().strip('"')).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
    if path.is_file():
        return _layout_from_executable(path)
    if sys.platform == "win32":
        for candidate in (path / "Cursor.exe", path / "bin" / "Cursor.exe"):
            if candidate.is_file():
                return _layout_from_executable(candidate)
    if sys.platform == "darwin" and path.suffix == ".app":
        exe = path / "Contents" / "MacOS" / "Cursor"
        if exe.is_file():
            return _layout_from_executable(exe)
    app_dir = path / "resources" / "app"
    if app_dir.is_dir():
        for parent in (path, path.parent):
            exe = parent / ("Cursor.exe" if sys.platform == "win32" else "Cursor")
            if exe.is_file():
                return _layout_from_executable(exe)
    raise FileNotFoundError(f"未找到 Cursor 可执行文件：{path}")


def _default_candidates() -> list[Path]:
    out: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or ""
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        for p in (
            Path(local) / "Programs" / "cursor" / "Cursor.exe",
            Path(pf) / "Cursor" / "Cursor.exe",
            Path(r"D:\Tools\cursor\Cursor.exe"),
        ):
            if p.is_file():
                out.append(p)
    elif sys.platform == "darwin":
        p = Path("/Applications/Cursor.app")
        if p.is_dir():
            out.append(p)
    return out


def resolve_install(custom: str | None = None) -> CursorInstall:
    if custom and custom.strip().casefold() not in {"", "auto"}:
        return layout_from_path(custom)
    configured = _load_config().get("cursorPath")
    if isinstance(configured, str) and configured.strip():
        return layout_from_path(configured)
    for candidate in _default_candidates():
        try:
            return _layout_from_executable(candidate)
        except Exception:
            continue
    raise FileNotFoundError("未检测到 Cursor 安装，请在设置里指定 Cursor.exe 路径")


def save_cursor_path(value: str) -> dict:
    if value.strip().casefold() in {"auto", "clear", "reset", ""}:
        data = update_config(cursorPath="")
        return {"cursorPath": data.get("cursorPath") or ""}
    layout = layout_from_path(value)
    data = update_config(cursorPath=str(layout.install_root), lastVersion=layout.version)
    return {"cursorPath": str(layout.install_root), "version": layout.version}


def is_cursor_running() -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Cursor.exe", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            return "cursor.exe" in (result.stdout or "").lower()
        except Exception:
            return False
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["pgrep", "-x", "Cursor"], capture_output=True, timeout=5, check=False)
            return result.returncode == 0
        except Exception:
            return False
    return False


def close_cursor(layout: CursorInstall | None = None) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/IM", "Cursor.exe"], capture_output=True, timeout=10, check=False)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not is_cursor_running():
                time.sleep(0.35)  # 进程退出后再等落盘
                return
            time.sleep(0.2)
        return
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", 'tell application "Cursor" to quit'], capture_output=True, timeout=10, check=False)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not is_cursor_running():
                time.sleep(0.35)
                return
            time.sleep(0.25)
        subprocess.run(["pkill", "-9", "Cursor"], capture_output=True, timeout=5, check=False)


def start_cursor(layout: CursorInstall, extra_args: tuple[str, ...] = (), *, light: bool = False) -> None:
    args = launch_args(light=light)
    if extra_args:
        args = [*args, *extra_args]
    if sys.platform == "win32":
        subprocess.Popen(
            [str(layout.executable), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x00000200,
        )
        return
    if sys.platform == "darwin":
        bundle = layout.install_root if layout.install_root.suffix == ".app" else None
        if bundle is None:
            for parent in (layout.install_root, layout.install_root.parent):
                if parent.suffix == ".app":
                    bundle = parent
                    break
        if bundle is None:
            raise RuntimeError("未找到 Cursor.app")
        subprocess.run(
            [shutil.which("open") or "/usr/bin/open", "-a", str(bundle), "--args", *args],
            timeout=20,
            check=False,
        )
        return
    raise RuntimeError("当前仅支持 Windows / macOS")


COMPACT_BUSY_MSG = "目前 Cursor 正在运行，状态库被占用，无法压缩。请先点「关闭 IDE」。"
COMPACT_LOCKED_MSG = "状态库仍被占用，请等 Cursor 完全退出后再试。"


def _db_locked(path: Path) -> bool:
    import sqlite3

    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=0.2)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        finally:
            conn.close()
        return False
    except sqlite3.OperationalError:
        return True
    except Exception:
        return True


def compact_precheck() -> dict:
    from .local_cursor import state_db_path

    running = is_cursor_running()
    db = Path(state_db_path())
    size_mb = round(db.stat().st_size / (1024 * 1024), 1) if db.is_file() else 0
    backup = db.with_name(db.name + ".backup")
    backup_mb = round(backup.stat().st_size / (1024 * 1024), 1) if backup.is_file() else 0
    if running:
        return {
            "ok": False,
            "occupied": True,
            "running": True,
            "error": COMPACT_BUSY_MSG,
            "sizeMb": size_mb,
            "backupMb": backup_mb,
        }
    if db.is_file() and _db_locked(db):
        return {
            "ok": False,
            "occupied": True,
            "running": False,
            "error": COMPACT_LOCKED_MSG,
            "sizeMb": size_mb,
            "backupMb": backup_mb,
        }
    if not db.is_file():
        return {"ok": False, "error": "未找到 state.vscdb", "sizeMb": 0, "backupMb": 0}
    return {"ok": True, "occupied": False, "running": False, "sizeMb": size_mb, "backupMb": backup_mb}


def compact_cursor_state(on_progress=None) -> dict:
    """压缩 Cursor state.vscdb。on_progress(dict) 可选。"""
    import math
    import sqlite3
    import time as _time

    def emit(pct: int, phase: str, message: str, **extra) -> None:
        if on_progress:
            payload = {"pct": max(0, min(100, int(pct))), "phase": phase, "message": message, **extra}
            try:
                on_progress(payload)
            except Exception:
                pass

    pre = compact_precheck()
    if not pre.get("ok"):
        return pre

    from .local_cursor import state_db_path

    db = Path(state_db_path())
    before = db.stat().st_size
    backup = db.with_name(db.name + ".backup")
    backup_size = backup.stat().st_size if backup.is_file() else 0
    emit(4, "backup", f"准备压缩 {pre['sizeMb']}MB…", beforeMb=pre["sizeMb"])
    if backup.is_file():
        emit(8, "backup", f"正在删除 backup（{pre['backupMb']}MB）…")
        try:
            backup.unlink()
        except OSError as exc:
            return {"ok": False, "error": f"无法删除 backup：{exc}"}

    emit(12, "vacuum", "正在压缩状态库，完成前请不要打开 Cursor…")
    ticks = 0
    last_emit = 0.0
    conn = sqlite3.connect(str(db), timeout=2)
    try:
        conn.execute("PRAGMA busy_timeout=2000")

        def _handler():
            nonlocal ticks, last_emit
            ticks += 1
            now = _time.monotonic()
            if now - last_emit < 0.2:
                return 0
            last_emit = now
            pct = int(min(92, 12 + 80 * (1 - math.exp(-ticks / 400))))
            elapsed = int(now - start)
            emit(pct, "vacuum", f"正在压缩… {pct}% · 已用 {elapsed}s · 请勿打开 Cursor")
            return 0

        start = _time.monotonic()
        conn.set_progress_handler(_handler, 4000)
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "locked" in msg:
                return {"ok": False, "occupied": True, "error": COMPACT_LOCKED_MSG}
            return {"ok": False, "error": str(exc)}
        finally:
            conn.set_progress_handler(None, 0)
    finally:
        conn.close()
    after = db.stat().st_size if db.is_file() else 0
    result = {
        "ok": True,
        "beforeMb": round(before / (1024 * 1024), 1),
        "afterMb": round(after / (1024 * 1024), 1),
        "backupRemovedMb": round(backup_size / (1024 * 1024), 1),
        "seconds": round(_time.monotonic() - start, 1),
    }
    emit(
        100,
        "done",
        f"压缩完成 {result['beforeMb']}MB → {result['afterMb']}MB，现在可以打开 Cursor",
        **result,
    )
    return result
