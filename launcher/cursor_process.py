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
CONFIG_VERSION = 1


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
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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
        _write_json(
            _config_path(),
            {"version": CONFIG_VERSION, "cursorPath": "", "updatedAt": datetime.now(timezone.utc).isoformat()},
        )
        return {"cursorPath": ""}
    layout = layout_from_path(value)
    _write_json(
        _config_path(),
        {
            "version": CONFIG_VERSION,
            "cursorPath": str(layout.install_root),
            "lastVersion": layout.version,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not is_cursor_running():
                return
            time.sleep(0.2)
        return
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", 'tell application "Cursor" to quit'], capture_output=True, timeout=10, check=False)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if not is_cursor_running():
                return
            time.sleep(0.25)
        subprocess.run(["pkill", "-9", "Cursor"], capture_output=True, timeout=5, check=False)


def start_cursor(layout: CursorInstall, extra_args: tuple[str, ...] = ()) -> None:
    args = (*CURSOR_START_ARGS, *extra_args)
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
