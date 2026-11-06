"""当前还能启动的干净基线。

只保存、只还原同一 Cursor 版本的 js。版本对不上就地反补丁，
不用旧 official / bajie 备份盖新安装，也不依赖外部网关。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from launcher.cursor_install import resolve_layout
from launcher.cursor_process import is_cursor_running
from launcher.ctxwin import file_has_patch
from launcher.versioning import usable_cursor_version
from launcher.workbench import backup as wb_backup
from launcher.workbench.layers import scan_files
from launcher.workbench.manager import sync_product_checksums, write_atomic

CLEAN_DIR = "clean-now"
_SAND_NEEDLES = (
    b"/*SAND_DIRECT_INFERENCE_STREAM_V1*/",
    b"/*SAND_CLIENT_MODE_V1*/",
    b"/*SAND_MANAGED_LOCAL_ROUTE_V1*/",
    b"/*SAND_SESSION_INFERENCE_STREAM_V1*/",
)


def clean_dir() -> Path:
    path = wb_backup.store_root() / CLEAN_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_product_version(product_json: Path) -> str:
    if not product_json.is_file():
        return ""
    try:
        data = json.loads(product_json.read_bytes().decode("utf-8-sig"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return usable_cursor_version(str(data.get("version") or ""))


def backup_version_matches(backup_dir: Path, product_json: Path) -> bool:
    """备份里的 product.json 版本必须和当前安装一致，否则不能盖文件。"""
    current = read_product_version(product_json)
    pinned = read_product_version(backup_dir / "product.json")
    return bool(current and pinned and current == pinned)


def _read_manifest(dest: Path | None = None) -> dict:
    path = (dest or clean_dir()) / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _targets(files: list[Path], host: Path | None) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in list(files) + ([host] if host is not None else []):
        if path is None or not path.is_file():
            continue
        key = path.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def files_look_clean(files: list[Path], host: Path | None) -> tuple[bool, str]:
    scan = scan_files(files) if files else scan_files([])
    if scan.corrupted:
        return False, "workbench 异常，不能记成干净基线"
    if scan.launcher_installed:
        return False, "workbench 还有启动器补丁，不能记成干净基线"
    if host is not None and host.is_file() and file_has_patch(host):
        return False, "500k 回包还在，不能记成干净基线"
    for path in _targets(files, host):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(needle in data for needle in _SAND_NEEDLES):
            return False, "Grok Bot 标记还在，不能记成干净基线"
    return True, ""


def clean_status(product_json: Path | None = None) -> dict:
    manifest = _read_manifest()
    version = str(manifest.get("version") or "")
    current = read_product_version(product_json) if product_json else ""
    return {
        "pinned": bool(version),
        "version": version,
        "currentVersion": current,
        "sameVersion": bool(version and current and version == current),
        "createdAt": manifest.get("createdAt") or "",
        "files": list(manifest.get("files") or []),
        "path": str(clean_dir()),
    }


def pin_clean_now(
    files: list[Path],
    host: Path | None,
    product_json: Path,
) -> dict:
    """当前文件没有启动器补丁时，记下这一版 Cursor 的干净 js。同版本不重复写。"""
    version = read_product_version(product_json)
    if not version:
        return {"ok": True, "skipped": True, "reason": "no-version", "message": "读不到 Cursor 版本，未记干净基线"}

    manifest = _read_manifest()
    if str(manifest.get("version") or "") == version and manifest.get("files"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already",
            "pinned": True,
            "version": version,
            "message": f"已有 v{version} 干净快照",
            **clean_status(product_json),
        }

    ok, why = files_look_clean(files, host)
    if not ok:
        return {
            "ok": True,
            "skipped": True,
            "reason": "dirty",
            "message": why,
            **clean_status(product_json),
        }

    targets = _targets(files, host)
    if not targets:
        return {"ok": False, "error": "没有可记的 workbench 文件"}

    staging = clean_dir().parent / f"{CLEAN_DIR}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    names: list[str] = []
    try:
        for path in targets:
            shutil.copy2(path, staging / path.name)
            names.append(path.name)
        payload = {
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "files": names,
            "note": "同版本干净 js。还原时不覆盖 product.json，版本不同则拒绝覆盖。",
        }
        (staging / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        dest = clean_dir()
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(staging), str(dest))
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "created": True,
        "message": f"已记下 v{version} 干净快照",
        **clean_status(product_json),
    }


def restore_pinned_files(
    files: list[Path],
    host: Path | None,
    product_json: Path,
) -> dict:
    """只在版本一致时把记下的 js 拷回。绝不写 product.json。"""
    manifest = _read_manifest()
    pinned = str(manifest.get("version") or "")
    current = read_product_version(product_json)
    if not pinned:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no-pin",
            "message": "还没有干净快照，只做就地反补丁",
        }
    if not current or current != pinned:
        return {
            "ok": True,
            "skipped": True,
            "reason": "version-mismatch",
            "pinnedVersion": pinned,
            "version": current,
            "message": f"干净快照是 v{pinned or '未知'}，当前是 v{current or '未知'}，不覆盖文件",
        }

    changed: dict[Path, bytes] = {}
    restored: list[str] = []
    for path in _targets(files, host):
        src = clean_dir() / path.name
        if not src.is_file():
            continue
        data = src.read_bytes()
        try:
            current_bytes = path.read_bytes()
        except OSError as exc:
            return {"ok": False, "error": f"读不到 {path.name}：{exc}"}
        if current_bytes == data:
            continue
        changed[path.resolve()] = data
        restored.append(path.name)

    if not changed:
        return {
            "ok": True,
            "skipped": True,
            "reason": "same",
            "version": current,
            "message": f"文件已与 v{current} 干净快照一致",
        }

    for path, data in changed.items():
        write_atomic(path, data)

    app_root = product_json.parent
    product_next = sync_product_checksums(app_root, changed)
    checksums = False
    if product_next is not None and product_json.is_file():
        write_atomic(product_json, product_next)
        checksums = True

    return {
        "ok": True,
        "restored": restored,
        "version": current,
        "checksums": checksums,
        "message": f"已从 v{current} 干净快照还原 {', '.join(restored)}",
    }


def _step(name: str, result: dict) -> dict:
    return {
        "id": name,
        "ok": bool(result.get("ok")),
        "skipped": bool(result.get("skipped")),
        "message": result.get("message") or result.get("error") or "",
    }


def restore_to_clean() -> dict:
    """补丁页一键回到当前还能启动的状态。不走外部网关，不用跨版本备份。"""
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE", "running": True}

    try:
        _layout, app_root, files = resolve_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    from launcher.ctxwin import ctxwin_restore, ctxwin_status, host_js_path

    product_json = app_root / "product.json"
    host = host_js_path(app_root)
    host_path = host if host.is_file() else None
    steps: list[dict] = []
    hard_error = ""

    pinned = restore_pinned_files(files, host_path, product_json)
    steps.append(_step("snapshot", pinned))
    if not pinned.get("ok"):
        hard_error = pinned.get("error") or "还原干净快照失败"

    try:
        from launcher.sand_stream import restore as sand_restore

        sand = sand_restore(keep_siblings=False)
    except Exception as exc:
        sand = {"ok": False, "error": str(exc)}
    steps.append(_step("sand", sand))
    if not sand.get("ok"):
        hard_error = hard_error or sand.get("error") or "Grok Bot 还原失败"

    try:
        from launcher.model_unlock import restore as unlock_restore

        unlock = unlock_restore()
    except Exception as exc:
        unlock = {"ok": False, "error": str(exc)}
    steps.append(_step("unlock", unlock))
    if not unlock.get("ok"):
        hard_error = hard_error or unlock.get("error") or "解锁还原失败"

    try:
        ctx_status = ctxwin_status()
        if ctx_status.get("patched"):
            ctx = ctxwin_restore()
        else:
            ctx = {"ok": True, "skipped": True, "message": "没有 500k 回包"}
    except Exception as exc:
        ctx = {"ok": False, "error": str(exc)}
    steps.append(_step("ctxwin", ctx))
    if not ctx.get("ok"):
        hard_error = hard_error or ctx.get("error") or "500k 还原失败"

    try:
        from launcher.bot_gateway_ctl import (
            gateway_process_status,
            is_gateway_mode,
            stop_gateway,
        )

        if is_gateway_mode() or gateway_process_status().get("running"):
            gateway = stop_gateway()
        else:
            gateway = {"ok": True, "skipped": True, "message": "本机 Bot 网关未开"}
    except Exception as exc:
        gateway = {"ok": False, "error": str(exc)}
    steps.append(_step("gateway", gateway))
    if not gateway.get("ok"):
        hard_error = hard_error or gateway.get("error") or "关闭本机网关失败"

    pinned_after = pin_clean_now(files, host_path, product_json)
    steps.append(_step("pin", pinned_after))

    bits = [step["message"] for step in steps if step.get("message")]
    if hard_error:
        return {
            "ok": False,
            "error": hard_error,
            "message": "；".join(bits),
            "steps": steps,
            "clean": clean_status(product_json),
        }
    return {
        "ok": True,
        "message": "；".join(bits) or "已回到当前干净状态",
        "steps": steps,
        "clean": clean_status(product_json),
    }
