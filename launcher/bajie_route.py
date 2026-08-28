"""把网关插件改过的 API 地址改回官方，让 Agent 走 Chromium / Clash。

插件把 ``https://api2.cursor.sh`` 改成 ``https://127.0.0.1:43111/__bajie/api2.cursor.sh``。
本机回环会绕过 HTTP 代理，所以 Clash 再怎么注入也吃不到模型请求。
去掉 ``/__bajie/`` 前缀后，请求重新打官方主机，启动器加的 ``--proxy-server`` 才会生效。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

BAJIE_PREFIX = "https://127.0.0.1:43111/__bajie/"
BAJIE_RE = re.compile(re.escape(BAJIE_PREFIX) + r"([^\"']+)")
WORKBENCH_REL = (
    Path("resources") / "app" / "out" / "vs" / "workbench" / "workbench.desktop.main.js",
    Path("resources") / "app" / "out" / "vs" / "workbench" / "workbench.glass.main.js",
)


def _backup_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "bajie-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def strip_bajie_urls(text: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "https://" + match.group(1)

    return BAJIE_RE.sub(repl, text), count


def workbench_files(install_root: Path) -> list[Path]:
    root = Path(install_root)
    return [root / rel for rel in WORKBENCH_REL]


def detect_patch(install_root: Path) -> dict:
    """检测 workbench 里是否已有网关补丁（43111/__bajie）。"""
    files = [p for p in workbench_files(install_root) if p.is_file()]
    if not files:
        return {"ok": False, "patched": False, "hits": 0, "hasBackup": False, "error": "找不到 workbench"}
    backups = _backup_dir()
    hits = 0
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        _, n = strip_bajie_urls(raw)
        hits += n
    has_backup = any((backups / p.name).is_file() for p in files)
    return {
        "ok": True,
        "patched": hits > 0,
        "hits": hits,
        "hasBackup": has_backup,
        "files": len(files),
    }


def apply_bajie_route(install_root: Path, *, bypass: bool) -> dict:
    """bypass=True：改回官方 URL；False：从备份恢复插件改过的文件。"""
    files = [p for p in workbench_files(install_root) if p.is_file()]
    if not files:
        return {"ok": False, "error": "找不到 workbench 文件，无法改路由", "changed": 0}
    backups = _backup_dir()
    changed = 0
    hits = 0
    restored = 0
    try:
        for path in files:
            bak = backups / path.name
            if bypass:
                raw = path.read_text(encoding="utf-8")
                if BAJIE_PREFIX in raw and not bak.is_file():
                    shutil.copy2(path, bak)
                new, n = strip_bajie_urls(raw)
                hits += n
                if n:
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text(new, encoding="utf-8")
                    tmp.replace(path)
                    changed += 1
            else:
                if bak.is_file():
                    shutil.copy2(bak, path)
                    restored += 1
        if not bypass and restored == 0:
            return {"ok": False, "error": "没有 workbench 备份，无法还原", "restored": 0}
        return {
            "ok": True,
            "bypass": bypass,
            "changed": changed,
            "hits": hits,
            "restored": restored,
            "message": (f"已还原 {restored} 个 workbench 文件" if restored else None),
            "files": [str(p) for p in files],
        }
    except PermissionError:
        return {
            "ok": False,
            "error": "workbench 文件被占用，请先关闭 Cursor 再注入",
            "changed": changed,
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc), "changed": changed}
