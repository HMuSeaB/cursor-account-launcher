"""workbench 统一备份：official 基线 + 每次写入前快照。"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from launcher.workbench.layers import LayerScan, scan_content

STATE_ROOT = "workbench"
OFFICIAL_DIR = "official"
SNAPSHOTS_DIR = "snapshots"
LEGACY_BAJIE = "bajie-backups"
LEGACY_MODEL_UNLOCK = "model-unlock/backups"


def _launcher_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_root() -> Path:
    path = _launcher_root() / STATE_ROOT
    path.mkdir(parents=True, exist_ok=True)
    return path


def official_dir() -> Path:
    path = store_root() / OFFICIAL_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshots_dir() -> Path:
    path = store_root() / SNAPSHOTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_dirs() -> dict[str, Path]:
    root = _launcher_root()
    return {
        "bajie": root / LEGACY_BAJIE,
        "modelUnlock": root / LEGACY_MODEL_UNLOCK,
    }


def _write_manifest(dest: Path, *, layer: str, reason: str, files: list[Path]) -> None:
    scans: dict[str, dict] = {}
    for path in files:
        if path.is_file():
            try:
                scans[path.name] = scan_content(
                    path.read_text(encoding="utf-8", errors="ignore")
                ).as_hits()
            except OSError:
                scans[path.name] = {}
    manifest = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "layer": layer,
        "reason": reason,
        "files": [p.name for p in files],
        "scans": scans,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_files(files: list[Path], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in files:
        if path.is_file():
            shutil.copy2(path, dest / path.name)


def ensure_official(files: list[Path], product_json: Path | None = None) -> dict:
    """首次见到「无启动器补丁」的 workbench 时保存 official 基线。"""
    off = official_dir()
    desktop = off / "workbench.desktop.main.js"
    if desktop.is_file():
        return {"ok": True, "skipped": True, "path": str(off)}

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scan = scan_content(text)
        if scan.launcher_installed or scan.corrupted:
            return {
                "ok": False,
                "skipped": True,
                "error": "当前 workbench 已有启动器补丁或异常，无法建立 official 基线",
            }

    _copy_files(files, off)
    if product_json and product_json.is_file():
        shutil.copy2(product_json, off / "product.json")
    _write_manifest(off, layer="official", reason="baseline", files=files)
    return {"ok": True, "created": True, "path": str(off)}


def snapshot_before_write(
    files: list[Path],
    *,
    layer: str,
    reason: str,
    product_json: Path | None = None,
) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = snapshots_dir() / f"{stamp}-{layer}"
    _copy_files(files, dest)
    if product_json and product_json.is_file():
        shutil.copy2(product_json, dest / "product.json")
    _write_manifest(dest, layer=layer, reason=reason, files=files)
    return dest


def list_snapshots(limit: int = 20) -> list[dict]:
    root = snapshots_dir()
    out: list[dict] = []
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta: dict = {}
        mf = entry / "manifest.json"
        if mf.is_file():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        out.append(
            {
                "name": entry.name,
                "path": str(entry),
                "layer": meta.get("layer") or "",
                "reason": meta.get("reason") or "",
                "createdAt": meta.get("createdAt") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def restore_from_dir(files: list[Path], backup_dir: Path) -> list[str]:
    restored: list[str] = []
    for path in files:
        src = backup_dir / path.name
        if not src.is_file():
            continue
        shutil.copy2(src, path)
        restored.append(path.name)
    return restored


def find_best_legacy_clean() -> Path | None:
    """从旧版 model-unlock 备份里找最干净的快照。"""
    from launcher.workbench.markers import MARKER_MEM, MAX_MEM_INJECT

    root = _launcher_root() / LEGACY_MODEL_UNLOCK
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        desktop = entry / "workbench.desktop.main.js"
        if not desktop.is_file():
            continue
        text = desktop.read_text(encoding="utf-8", errors="ignore")
        if text.count(MARKER_MEM) > MAX_MEM_INJECT:
            continue
        head = text[:80].lstrip()
        if head.startswith("/*!") or head.startswith("(function"):
            return entry
    return None


def backup_status(files: list[Path]) -> dict:
    off = official_dir()
    legacy = legacy_dirs()
    has_official = any((off / p.name).is_file() for p in files)
    has_bajie = any((legacy["bajie"] / p.name).is_file() for p in files)
    snapshots = list_snapshots(limit=5)
    best_legacy = find_best_legacy_clean()
    return {
        "storeRoot": str(store_root()),
        "hasOfficial": has_official,
        "officialPath": str(off),
        "hasLegacyBajie": has_bajie,
        "legacyBajiePath": str(legacy["bajie"]),
        "legacyModelUnlockPath": str(legacy["modelUnlock"]),
        "hasLegacyModelUnlockClean": best_legacy is not None,
        "legacyModelUnlockClean": str(best_legacy) if best_legacy else "",
        "recentSnapshots": snapshots,
        "snapshotCount": len(list(snapshots_dir().iterdir())) if snapshots_dir().is_dir() else 0,
    }
