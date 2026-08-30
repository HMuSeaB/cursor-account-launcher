"""把网关插件改过的 API 地址改回官方，让 Agent 走 Chromium / Clash。

插件把 ``https://api2.cursor.sh`` 改成 ``https://127.0.0.1:43111/__bajie/api2.cursor.sh``。
本机回环会绕过 HTTP 代理，所以 Clash 再怎么注入也吃不到模型请求。
去掉 ``/__bajie/`` 前缀后，请求重新打官方主机，启动器加的 ``--proxy-server`` 才会生效。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from launcher.cursor_install import workbench_files
from launcher.workbench.layers import BAJIE_PREFIX, strip_gateway_urls
from launcher.workbench.manager import WorkbenchWriteError, commit_changes


def _legacy_backup_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "bajie-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def detect_patch(install_root: Path) -> dict:
    """检测 workbench 里是否已有网关补丁（43111/__bajie）。"""
    from launcher.workbench.layers import scan_files

    files = workbench_files(install_root)
    if not files:
        return {"ok": False, "patched": False, "hits": 0, "hasBackup": False, "error": "找不到 workbench"}
    scan = scan_files(files)
    backups = _legacy_backup_dir()
    has_backup = any((backups / p.name).is_file() for p in files)
    return {
        "ok": True,
        "patched": scan.gateway_hits > 0,
        "hits": scan.gateway_hits,
        "hasBackup": has_backup,
        "files": len(files),
    }


def apply_bajie_route(install_root: Path, *, bypass: bool) -> dict:
    """bypass=True：改回官方 URL；False：从备份恢复插件改过的文件。"""
    from launcher.cursor_install import app_root as resolve_app_root

    files = workbench_files(install_root)
    if not files:
        return {"ok": False, "error": "找不到 workbench 文件，无法改路由", "changed": 0}
    app_root_path = resolve_app_root(install_root)
    backups = _legacy_backup_dir()
    changed = 0
    hits = 0
    restored = 0
    try:
        if bypass:
            pending: dict[Path, str] = {}
            for path in files:
                raw = path.read_text(encoding="utf-8")
                bak = backups / path.name
                if BAJIE_PREFIX in raw and not bak.is_file():
                    shutil.copy2(path, bak)
                new, n = strip_gateway_urls(raw)
                hits += n
                if n and new != raw:
                    pending[path] = new
            snapshot = None
            if pending:
                wb_result = commit_changes(
                    app_root_path,
                    files,
                    pending,
                    layer="gateway-bypass",
                    reason="strip-bajie-for-clash",
                    skip_preflight=True,
                )
                changed = len([n for n in wb_result.get("changed", []) if n.endswith(".js")])
                snapshot = wb_result.get("snapshot")
            return {
                "ok": True,
                "bypass": True,
                "changed": changed,
                "hits": hits,
                "restored": 0,
                "snapshot": snapshot,
                "files": [str(p) for p in files],
            }

        for path in files:
            bak = backups / path.name
            if bak.is_file():
                shutil.copy2(bak, path)
                restored += 1
        if restored == 0:
            from launcher.workbench.diagnostic import restore_workbench_layer

            unified = restore_workbench_layer(target="legacy-bajie")
            if unified.get("ok") and unified.get("restored"):
                return {
                    "ok": True,
                    "bypass": False,
                    "changed": 0,
                    "hits": 0,
                    "restored": len(unified["restored"]),
                    "message": unified.get("message"),
                    "source": unified.get("source"),
                }
            return {"ok": False, "error": "没有 workbench 备份，无法还原", "restored": 0}
        return {
            "ok": True,
            "bypass": False,
            "changed": 0,
            "hits": 0,
            "restored": restored,
            "message": f"已还原 {restored} 个 workbench 文件",
            "files": [str(p) for p in files],
        }
    except WorkbenchWriteError as exc:
        return {"ok": False, "error": str(exc), "changed": changed}
    except PermissionError:
        return {
            "ok": False,
            "error": "workbench 文件被占用，请先关闭 Cursor 再注入",
            "changed": changed,
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc), "changed": changed}


# 兼容旧 import
strip_bajie_urls = strip_gateway_urls
