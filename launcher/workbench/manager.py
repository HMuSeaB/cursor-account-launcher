"""workbench 唯一写入网关：备份 → 预检 → 原子写入 → checksum。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

from launcher.workbench import backup as wb_backup
from launcher.workbench.preflight import PreflightError, assert_safe


class WorkbenchWriteError(RuntimeError):
    pass


def _product_checksum(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def sync_product_checksums(app_root: Path, changed: dict[Path, bytes]) -> bytes | None:
    product = app_root / "product.json"
    if not product.is_file():
        return None
    raw = product.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise WorkbenchWriteError(f"无法解析 product.json：{exc}") from exc
    checksums = data.get("checksums") if isinstance(data, dict) else None
    if not isinstance(checksums, dict):
        return None
    out_root = (app_root / "out").resolve()
    dirty = False
    for key in list(checksums.keys()):
        if not isinstance(key, str):
            continue
        parts = [p for p in re.split(r"[\\/]", key) if p]
        target = out_root.joinpath(*parts).resolve()
        if target in changed:
            digest = _product_checksum(changed[target])
            if checksums.get(key) != digest:
                checksums[key] = digest
                dirty = True
    if not dirty:
        return None
    text = json.dumps(data, ensure_ascii=False, indent="\t")
    out = text.encode("utf-8")
    if has_bom:
        out = b"\xef\xbb\xbf" + out
    return out


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".wb-{os.getpid()}-{time.time_ns()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def commit_changes(
    app_root: Path,
    workbench_files: list[Path],
    pending: dict[Path, bytes | str],
    *,
    layer: str,
    reason: str,
    skip_preflight: bool = False,
) -> dict:
    """唯一 workbench 写入入口。pending 的 key 必须是 workbench 文件或 product.json。"""
    if not pending:
        return {"ok": True, "skipped": True, "changed": []}

    allowed = {p.resolve() for p in workbench_files}
    product_path = (app_root / "product.json").resolve()
    allowed.add(product_path)

    for path in pending:
        if path.resolve() not in allowed:
            raise WorkbenchWriteError(f"拒绝写入非 workbench 路径：{path}")

    # 写入前：对将要变更的 workbench 文本做预检
    if not skip_preflight:
        for path, data in pending.items():
            if path.suffix != ".js":
                continue
            text = data.decode("utf-8") if isinstance(data, bytes) else data
            try:
                assert_safe(text)
            except PreflightError as exc:
                raise WorkbenchWriteError("预检未通过：" + "; ".join(exc.issues)) from exc

    wb_backup.ensure_official(workbench_files, app_root / "product.json")
    snap = wb_backup.snapshot_before_write(
        workbench_files,
        layer=layer,
        reason=reason,
        product_json=app_root / "product.json",
    )

    # 合并 product checksum
    byte_pending: dict[Path, bytes] = {}
    for path, data in pending.items():
        byte_pending[path] = data.encode("utf-8") if isinstance(data, str) else data

    wb_changed = {p: d for p, d in byte_pending.items() if p.suffix == ".js"}
    product_next = sync_product_checksums(app_root, wb_changed)
    if product_next is not None and product_path.is_file():
        byte_pending[product_path] = product_next

    changed_names: list[str] = []
    try:
        for path, data in byte_pending.items():
            if path.is_file() and path.read_bytes() == data:
                continue
            write_atomic(path, data)
            changed_names.append(path.name)
    except PermissionError as exc:
        raise WorkbenchWriteError("没有写入权限或文件被占用，请先关闭 Cursor") from exc
    except OSError as exc:
        raise WorkbenchWriteError(str(exc)) from exc

    return {
        "ok": True,
        "changed": changed_names,
        "snapshot": str(snap),
        "layer": layer,
        "reason": reason,
    }
