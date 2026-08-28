"""创建桌面 / 开始菜单快捷方式（仅打包后的 exe）。"""

from __future__ import annotations

import sys
from pathlib import Path

from launcher.cursor_process import _load_config, update_config
from launcher.hidden_proc import run as run_hidden

LINK_NAME = "Cursor Launcher.lnk"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launcher_exe() -> Path | None:
    if is_frozen():
        return Path(sys.executable).resolve()
    return None


def _folder(kind: str) -> Path | None:
    r = run_hidden(
        ["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{kind}')"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        check=False,
    )
    text = (r.stdout or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None


def desktop_dir() -> Path | None:
    return _folder("Desktop")


def programs_dir() -> Path | None:
    return _folder("Programs")


def _link_path(folder: Path | None) -> Path | None:
    if not folder:
        return None
    return folder / LINK_NAME


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_quote(str(link))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(target.parent))}; "
        f"$s.IconLocation = {_ps_quote(str(target) + ',0')}; "
        "$s.Save()"
    )
    result = run_hidden(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        check=False,
    )
    if result.returncode != 0:
        err = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        raise RuntimeError(err or f"powershell 退出码 {result.returncode}")


def shortcut_status() -> dict:
    exe = launcher_exe()
    desktop = _link_path(desktop_dir())
    start = _link_path(programs_dir())
    cfg = _load_config()
    return {
        "ok": True,
        "canCreate": bool(exe),
        "prompted": bool(cfg.get("shortcutPrompted")),
        "hasDesktop": bool(desktop and desktop.is_file()),
        "hasStartMenu": bool(start and start.is_file()),
        "desktopPath": str(desktop) if desktop else "",
        "startMenuPath": str(start) if start else "",
        "exe": str(exe) if exe else "",
    }


def create_shortcuts(*, desktop: bool = False, start_menu: bool = False) -> dict:
    exe = launcher_exe()
    if not exe:
        return {"ok": False, "error": "当前是源码运行，打包成 exe 后才能创建快捷方式"}
    if not desktop and not start_menu:
        return {"ok": False, "error": "请至少选桌面或开始菜单"}
    made: list[str] = []
    try:
        if desktop:
            dest = _link_path(desktop_dir())
            if not dest:
                return {"ok": False, "error": "找不到桌面文件夹"}
            _create_link(dest, exe)
            made.append("桌面")
        if start_menu:
            dest = _link_path(programs_dir())
            if not dest:
                return {"ok": False, "error": "找不到开始菜单文件夹"}
            _create_link(dest, exe)
            made.append("开始菜单")
    except Exception as exc:
        return {"ok": False, "error": str(exc), **shortcut_status()}
    update_config(shortcutPrompted=True)
    status = shortcut_status()
    status["ok"] = True
    status["message"] = "已创建：" + "、".join(made)
    return status


def mark_shortcut_prompted() -> dict:
    update_config(shortcutPrompted=True)
    status = shortcut_status()
    status["ok"] = True
    return status
