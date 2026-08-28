"""禁用 Cursor 自动更新（settings + Windows 更新器拦截）。"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

from launcher.cursor_proxy import _load_settings, _save_settings
from launcher.cursor_process import _config_path, _load_config, update_config

UPDATE_MODE_KEY = "update.mode"
UPDATE_BG_KEY = "update.enableWindowsBackgroundUpdates"
UPDATE_MODE_NONE = "none"
UPDATER_EXE = "inno_updater.exe"
UPDATER_DISABLED = "inno_updater.exe.disabled"


def _backup_dir() -> Path:
    path = _config_path().parent / "updater-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _windows_updater_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "cursor-updater"


def _set_readonly(path: Path) -> None:
    if sys.platform != "win32":
        return
    mode = path.stat().st_mode
    path.chmod(mode & ~stat.S_IWRITE)


def read_update_status(install_root: Path | None = None) -> dict:
    settings = _load_settings()
    mode = settings.get(UPDATE_MODE_KEY)
    bg = settings.get(UPDATE_BG_KEY)
    cfg = _load_config()
    enabled = cfg.get("disableAutoUpdate")
    if enabled is None:
        enabled = True
    updater_dir = _windows_updater_dir()
    inno = None
    inno_disabled = False
    if install_root is not None:
        tools = Path(install_root) / "tools"
        inno = tools / UPDATER_EXE
        inno_disabled = (tools / UPDATER_DISABLED).is_file() and not inno.is_file()
    return {
        "ok": True,
        "disableAutoUpdate": bool(enabled),
        "updateMode": mode,
        "backgroundUpdates": bg,
        "settingsBlocked": mode == UPDATE_MODE_NONE and bg is False,
        "updaterDir": str(updater_dir),
        "updaterDirBlocked": updater_dir.is_dir() and not os.access(updater_dir, os.W_OK),
        "innoUpdaterDisabled": inno_disabled,
        "innoUpdaterPath": str(inno) if inno else "",
    }


def apply_disable_updates(install_root: Path | None = None) -> dict:
    """写入 settings.json，并在 Windows 上拦截 cursor-updater / inno_updater。"""
    from launcher.local_cursor import settings_json_path

    sp = settings_json_path()
    settings = _load_settings()
    if not settings and sp and os.path.isfile(sp):
        return {"ok": False, "error": "无法解析 settings.json，已跳过以免覆盖现有配置"}
    if not sp:
        return {"ok": False, "error": "找不到 settings.json 路径"}
    if not settings and not os.path.isfile(sp):
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        settings = {}

    settings[UPDATE_MODE_KEY] = UPDATE_MODE_NONE
    settings[UPDATE_BG_KEY] = False
    _save_settings(settings)

    update_config(disableAutoUpdate=True)
    result: dict = {
        "ok": True,
        "updateMode": UPDATE_MODE_NONE,
        "backgroundUpdates": False,
    }

    if sys.platform == "win32":
        updater_dir = _windows_updater_dir()
        updater_dir.mkdir(parents=True, exist_ok=True)
        marker = updater_dir / ".cursor-launcher-blocked"
        if not marker.is_file():
            marker.write_text("blocked by Cursor Launcher\n", encoding="utf-8")
        try:
            _set_readonly(marker)
            _set_readonly(updater_dir)
            result["updaterDirBlocked"] = True
        except OSError as exc:
            result["updaterDirBlocked"] = False
            result["updaterDirError"] = str(exc)

        if install_root is not None:
            tools = Path(install_root) / "tools"
            src = tools / UPDATER_EXE
            dst = tools / UPDATER_DISABLED
            if src.is_file():
                backup = _backup_dir() / UPDATER_EXE
                if not backup.is_file():
                    shutil.copy2(src, backup)
                try:
                    src.replace(dst)
                    result["innoUpdaterDisabled"] = True
                except OSError as exc:
                    result["innoUpdaterDisabled"] = False
                    result["innoUpdaterError"] = str(exc)
            elif dst.is_file():
                result["innoUpdaterDisabled"] = True
            else:
                result["innoUpdaterDisabled"] = False
                result["innoUpdaterSkipped"] = True

    return result


def restore_updates(install_root: Path | None = None) -> dict:
    """恢复自动更新（仅 settings + inno_updater；cursor-updater 目录需手动删只读）。"""
    settings = _load_settings()
    settings.pop(UPDATE_MODE_KEY, None)
    settings.pop(UPDATE_BG_KEY, None)
    _save_settings(settings)
    update_config(disableAutoUpdate=False)

    result: dict = {"ok": True, "disableAutoUpdate": False}
    if sys.platform == "win32" and install_root is not None:
        tools = Path(install_root) / "tools"
        src = tools / UPDATER_DISABLED
        dst = tools / UPDATER_EXE
        if src.is_file() and not dst.is_file():
            try:
                src.replace(dst)
                result["innoUpdaterRestored"] = True
            except OSError as exc:
                return {"ok": False, "error": str(exc)}
    return result
