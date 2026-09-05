"""创建桌面 / 开始菜单快捷方式（仅打包后的 exe）。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from launcher.cursor_process import _load_config, update_config
from launcher.hidden_proc import run as run_hidden

LINK_NAMES = ("Cursor Launcher.lnk", "Cursor 账号启动器.lnk")
LINK_NAME = LINK_NAMES[0]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launcher_exe() -> Path | None:
    if is_frozen():
        return Path(sys.executable).resolve()
    return None


def bundled_icon() -> Path | None:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / "icon.ico")
    root = Path(__file__).resolve().parent.parent
    candidates.append(root / "assets" / "icon.ico")
    exe = launcher_exe()
    if exe:
        ver = _version_slug()
        candidates.append(exe.parent / f"app-{ver}.ico")
        candidates.append(exe.with_name("app.ico"))
        candidates.append(exe.parent / "assets" / "icon.ico")
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 100:
                return path
        except OSError:
            continue
    return None


def _version_slug() -> str:
    from launcher.versioning import LAUNCHER_VERSION

    return str(LAUNCHER_VERSION).strip() or "dev"


def versioned_icon(*, persist: bool | None = None) -> Path | None:
    """把当前 ico 拷到带版本号的路径，避开 Windows 按「exe,0」缓存旧图标。"""
    src = bundled_icon()
    if not src:
        return None
    if persist is None:
        persist = is_frozen()
    if not persist:
        return src
    base = Path(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")) / "CursorLauncher" / "branding"
    try:
        base.mkdir(parents=True, exist_ok=True)
        dest = base / f"icon-{_version_slug()}.ico"
        if not dest.is_file() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        for old in base.glob("icon-*.ico"):
            if old.resolve() != dest.resolve():
                try:
                    old.unlink()
                except OSError:
                    pass
        return dest
    except OSError:
        return src


def _icon_location(target: Path) -> str:
    ico = versioned_icon()
    if ico:
        return f"{ico},0"
    return f"{target},0"


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


def _link_path(folder: Path | None, name: str = LINK_NAME) -> Path | None:
    if not folder:
        return None
    return folder / name


def _iter_existing_links() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for folder in (desktop_dir(), programs_dir()):
        if not folder:
            continue
        for name in LINK_NAMES:
            path = folder / name
            key = str(path).casefold()
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            found.append(path)
    return found


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    icon = _icon_location(target)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_quote(str(link))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(target.parent))}; "
        f"$s.IconLocation = {_ps_quote(icon)}; "
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


def _notify_shell(paths: list[Path]) -> None:
    if sys.platform != "win32" or not paths:
        return
    import ctypes

    shell32 = ctypes.windll.shell32
    shcne_updateitem = 0x00002000
    shcne_assocchanged = 0x08000000
    shcnf_pathw = 0x0005
    shcnf_flush = 0x1000
    shcnf_idlist = 0x0000
    for path in paths:
        try:
            shell32.SHChangeNotify(
                shcne_updateitem,
                shcnf_pathw | shcnf_flush,
                ctypes.c_wchar_p(str(path)),
                None,
            )
        except Exception:
            continue
    try:
        shell32.SHChangeNotify(shcne_assocchanged, shcnf_idlist | shcnf_flush, None, None)
    except Exception:
        pass


def shortcut_status() -> dict:
    exe = launcher_exe()
    desktop = _link_path(desktop_dir())
    start = _link_path(programs_dir())
    cfg = _load_config()
    ico = None
    try:
        ico = versioned_icon()
    except Exception:
        ico = None
    return {
        "ok": True,
        "canCreate": bool(exe),
        "prompted": bool(cfg.get("shortcutPrompted")),
        "hasDesktop": bool(desktop and desktop.is_file()) or any(
            p.parent == desktop_dir() for p in _iter_existing_links()
        ),
        "hasStartMenu": bool(start and start.is_file()) or any(
            p.parent == programs_dir() for p in _iter_existing_links()
        ),
        "desktopPath": str(desktop) if desktop else "",
        "startMenuPath": str(start) if start else "",
        "exe": str(exe) if exe else "",
        "icon": str(ico) if ico else "",
    }


def create_shortcuts(*, desktop: bool = False, start_menu: bool = False) -> dict:
    exe = launcher_exe()
    if not exe:
        return {"ok": False, "error": "当前是源码运行，打包成 exe 后才能创建快捷方式"}
    if not desktop and not start_menu:
        return {"ok": False, "error": "请至少选桌面或开始菜单"}
    made: list[str] = []
    written: list[Path] = []
    try:
        if desktop:
            dest = _link_path(desktop_dir())
            if not dest:
                return {"ok": False, "error": "找不到桌面文件夹"}
            _create_link(dest, exe)
            written.append(dest)
            made.append("桌面")
        if start_menu:
            dest = _link_path(programs_dir())
            if not dest:
                return {"ok": False, "error": "找不到开始菜单文件夹"}
            _create_link(dest, exe)
            written.append(dest)
            made.append("开始菜单")
        _notify_shell(written + [exe])
    except Exception as exc:
        return {"ok": False, "error": str(exc), **shortcut_status()}
    update_config(shortcutPrompted=True)
    status = shortcut_status()
    status["ok"] = True
    status["message"] = "已创建：" + "、".join(made)
    return status


def refresh_shortcut_icons() -> dict:
    """覆盖已有 .lnk 的 IconLocation，让桌面跟上当前版本图标。"""
    exe = launcher_exe()
    if not exe:
        return {"ok": True, "updated": 0, "skipped": True}
    ico = versioned_icon()
    updated: list[str] = []
    try:
        for link in _iter_existing_links():
            _create_link(link, exe)
            updated.append(str(link))
        _notify_shell([Path(p) for p in updated] + [exe])
    except Exception as exc:
        return {"ok": False, "error": str(exc), "updated": len(updated), "icon": str(ico) if ico else ""}
    return {
        "ok": True,
        "updated": len(updated),
        "icon": str(ico) if ico else "",
        "links": updated,
        "message": f"已刷新 {len(updated)} 个快捷方式图标" if updated else "没有已有快捷方式需要刷新",
    }


def mark_shortcut_prompted() -> dict:
    update_config(shortcutPrompted=True)
    status = shortcut_status()
    status["ok"] = True
    return status
