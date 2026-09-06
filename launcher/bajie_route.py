"""模型墙由 YC / Sub2API 扩展自己打。启动器只检测，不代写 workbench。"""

from __future__ import annotations

import os
from pathlib import Path

from launcher.cursor_install import workbench_files
from launcher.workbench.layers import BAJIE_PREFIX, strip_gateway_urls


def _legacy_backup_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "bajie-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


WALL_USE_EXTENSION = (
    "模型墙必须由 YC 或 Sub2API 扩展自己在面板里打补丁。"
    "启动器不代写、不剥 __bajie、不拿旧 bajie 备份盖 workbench（版本一变就会打坏）。"
)
WALL_REFUSED = {
    "ok": False,
    "refused": True,
    "changed": 0,
    "restored": 0,
    "error": WALL_USE_EXTENSION,
}


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
    """启动器不再代写模型墙。剥 __bajie / 恢复 bajie 备份都容易把当前版本 workbench 打坏。"""
    del install_root, bypass
    return dict(WALL_REFUSED)


# 兼容旧 import
strip_bajie_urls = strip_gateway_urls
