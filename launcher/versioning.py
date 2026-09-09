"""启动器与 Cursor 版本跟踪。"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

# 发版时与 installer / GitHub tag 对齐
LAUNCHER_VERSION = "1.3.14"
GITHUB_REPO = "HMuSeaB/cursor-account-launcher"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_UNREADABLE_VERSIONS = {"", "?", "unknown", "未知"}


def usable_cursor_version(version: str | None) -> str:
    """真正的版本号；读失败时的占位符不算。"""
    ver = str(version or "").strip()
    if not ver or ver.casefold() in _UNREADABLE_VERSIONS:
        return ""
    return ver


def _state_path(name: str) -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher"
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def _read_json(name: str, default: Any = None) -> Any:
    path = _state_path(name)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(name: str, data: Any) -> None:
    path = _state_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def note_cursor_version(version: str) -> dict:
    """记录当前 Cursor 版本；若与上次不同则标记升级。

    读不到 product.json 时会得到 "?" / 空串，那不是一次升级，也不能覆盖上次的真版本。
    """
    ver = usable_cursor_version(version)
    state = _read_json("cursor-version.json", {}) or {}
    prev = usable_cursor_version(str(state.get("lastVersion") or ""))
    stored_prev = usable_cursor_version(str(state.get("previousVersion") or ""))
    if not ver:
        return {
            "ok": True,
            "version": "",
            "previousVersion": prev or stored_prev,
            "upgraded": False,
            "needsRepatch": bool(state.get("needsRepatch")) and bool(prev),
            "unreadable": True,
        }
    upgraded = bool(prev and ver and prev != ver)
    state["lastVersion"] = ver
    if upgraded:
        state["previousVersion"] = prev
        state["upgradedAt"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        state["needsRepatch"] = True
    else:
        state["previousVersion"] = stored_prev
        if not stored_prev:
            state["needsRepatch"] = False
    _write_json("cursor-version.json", state)
    return {
        "ok": True,
        "version": ver,
        "previousVersion": str(state.get("previousVersion") or ""),
        "upgraded": upgraded,
        "needsRepatch": bool(state.get("needsRepatch")),
        "unreadable": False,
    }


def clear_repatch_flag() -> None:
    state = _read_json("cursor-version.json", {}) or {}
    state["needsRepatch"] = False
    _write_json("cursor-version.json", state)


def cursor_upgrade_status() -> dict:
    state = _read_json("cursor-version.json", {}) or {}
    last = usable_cursor_version(str(state.get("lastVersion") or ""))
    prev = usable_cursor_version(str(state.get("previousVersion") or ""))
    return {
        "ok": True,
        "lastVersion": last,
        "previousVersion": prev,
        "needsRepatch": bool(state.get("needsRepatch")) and bool(prev),
        "upgradedAt": state.get("upgradedAt") or "",
    }


def _parse_semver(tag: str) -> tuple[int, ...]:
    s = (tag or "").strip().lstrip("vV")
    parts: list[int] = []
    for bit in s.split("."):
        num = ""
        for ch in bit:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_launcher_update(timeout: float = 4.0) -> dict:
    """查 GitHub latest release；失败时不打断主流程。"""
    current = LAUNCHER_VERSION
    try:
        req = urllib.request.Request(
            RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"CursorLauncher/{current}",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "")
        latest = tag.lstrip("vV")
        newer = _parse_semver(latest) > _parse_semver(current)
        return {
            "ok": True,
            "current": current,
            "latest": latest,
            "tag": tag,
            "newer": newer,
            "url": data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
            "name": data.get("name") or tag,
        }
    except Exception as exc:
        return {
            "ok": False,
            "current": current,
            "latest": "",
            "newer": False,
            "error": str(exc),
            "url": f"https://github.com/{GITHUB_REPO}/releases",
        }
