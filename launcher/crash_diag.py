"""从 Cursor 日志里归因崩溃，尤其是刚装的插件。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_EXT_FOLDER_RE = re.compile(r"^(.+?)-(\d+\.\d+\.\d+.*)$")

_PATTERNS: tuple[tuple[str, re.Pattern[str], str, str], ...] = (
    (
        "workbench_syntax",
        re.compile(
            r"SyntaxError: Unexpected token.*workbench\.(desktop|glass)\.main\.js|"
            r"workbench\.(desktop|glass)\.main\.js.*(?:SyntaxError|Unexpected token)",
            re.I,
        ),
        "critical",
        "workbench 语法错误（补丁/黑屏类）",
    ),
    (
        "extension_activate_fail",
        re.compile(r"Activating extension ['\"]([^'\"]+)['\"] failed[:\s]*(.*)", re.I),
        "critical",
        "扩展激活失败",
    ),
    (
        "native_abi",
        re.compile(r"compiled against a different Node\.js version|NODE_MODULE_VERSION", re.I),
        "critical",
        "原生模块和当前 Cursor 的 Node ABI 不一致",
    ),
    (
        "cannot_find_module",
        re.compile(r"Cannot find module ['\"]([^'\"]+)['\"]", re.I),
        "warn",
        "扩展缺文件或原生模块没装上",
    ),
    (
        "version_dll",
        re.compile(r"version\.dll|Failed to load .*(\.dll)", re.I),
        "critical",
        "DLL 注入失败（常见于进程代理）",
    ),
    (
        "extension_host_crash",
        re.compile(r"Extension host (terminated unexpectedly|exited unexpectedly|died)|ERROR_EXTENSION_HOST_TIMEOUT", re.I),
        "critical",
        "扩展宿主崩溃",
    ),
    (
        "oom",
        re.compile(r"heap out of memory|Allocation failed|FATAL ERROR:.*JavaScript", re.I),
        "critical",
        "内存耗尽",
    ),
    (
        "gpu_crash",
        re.compile(r"GPU process (exited|crash)|gpu_process_host", re.I),
        "warn",
        "GPU 进程崩溃（可试轻量启动关 GPU）",
    ),
    (
        "renderer_crash",
        re.compile(r"Renderer process (crash|gone)|RESULT_CODE_KILLED_BAD_MESSAGE", re.I),
        "warn",
        "渲染进程崩溃",
    ),
)

_KIND_RANK = {
    "workbench_syntax": 0,
    "extension_activate_fail": 1,
    "native_abi": 2,
    "cannot_find_module": 3,
    "version_dll": 4,
    "extension_host_crash": 5,
    "oom": 6,
    "gpu_crash": 7,
    "renderer_crash": 8,
}

_SEV_RANK = {"critical": 0, "warn": 1, "info": 2}


def cursor_user_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys_platform() == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Cursor"


def sys_platform() -> str:
    import sys

    return sys.platform


def extensions_root() -> Path:
    return Path.home() / ".cursor" / "extensions"


def logs_root() -> Path:
    return cursor_user_root() / "logs"


def _parse_ext_id(folder_name: str, package_json: Path | None) -> str:
    if package_json and package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8-sig"))
            name = str(data.get("name") or "").strip()
            publisher = str(data.get("publisher") or "").strip()
            if publisher and name:
                return f"{publisher}.{name}" if "." not in name else name
            if name:
                return name
        except Exception:
            pass
    match = _EXT_FOLDER_RE.match(folder_name)
    return match.group(1) if match else folder_name


def analyze_extensions(root: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        pkg = child / "package.json"
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        rows.append(
            {
                "id": _parse_ext_id(child.name, pkg if pkg.is_file() else None),
                "folder": child.name,
                "path": str(child),
                "mtime": mtime,
                "installedAt": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
            }
        )
    rows.sort(key=lambda item: item["mtime"], reverse=True)
    return rows[:limit]


def analyze_log_text(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern, severity, title in _PATTERNS:
        for match in pattern.finditer(text):
            snippet = match.group(0)[:240]
            ext_id = ""
            detail = snippet
            if kind == "extension_activate_fail":
                ext_id = match.group(1)
                detail = (match.group(2) or "").strip()[:240]
            elif kind == "cannot_find_module":
                detail = match.group(1)
            key = (kind, ext_id or snippet)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "kind": kind,
                    "severity": severity,
                    "title": title,
                    "extensionId": ext_id,
                    "detail": detail,
                    "snippet": snippet,
                }
            )
    return findings


def summarize_crash(
    findings: list[dict[str, Any]],
    extensions: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(
        findings,
        key=lambda item: (
            _SEV_RANK.get(item.get("severity") or "info", 9),
            _KIND_RANK.get(item.get("kind") or "", 99),
        ),
    )
    likely = ordered[:6]
    headline = "日志里没有明显的崩溃特征"
    advice = "若刚装插件后坏了：在 Cursor 用 --disable-extensions 启动，再逐个启用定位。"
    if likely:
        top = likely[0]
        ext = top.get("extensionId") or ""
        if ext:
            headline = f"插件 {ext} {top.get('title')}"
            advice = f"先禁用或卸载 {ext}，再用启动器开 IDE。仍崩再看 workbench / DLL。"
        else:
            headline = str(top.get("title") or headline)
            if top.get("kind") == "workbench_syntax":
                advice = "关 IDE → 设置里点「修复黑屏」或急救还原 workbench。"
            elif top.get("kind") == "gpu_crash":
                advice = "用启动器「轻量启动」（关 GPU）。"
            elif top.get("kind") == "version_dll":
                advice = "关 IDE → 设置危险区删除 / 还原 DLL。"
            elif top.get("kind") == "extension_host_crash":
                recent = [e.get("id") for e in extensions[:5] if e.get("id")]
                if recent:
                    advice = "扩展宿主崩了。最近安装：" + "、".join(recent) + "。先禁用这些再开。"
                else:
                    advice = "扩展宿主崩了。用 --disable-extensions 启动排查插件。"
    return {
        "ok": True,
        "headline": headline,
        "advice": advice,
        "likely": likely,
        "findings": ordered,
    }


def _iter_log_files(root: Path, *, sessions: int = 3) -> list[Path]:
    if not root.is_dir():
        return []
    dirs = sorted(
        [p for p in root.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:sessions]
    files: list[Path] = []
    for folder in dirs:
        for path in folder.rglob("*.log"):
            files.append(path)
    return files


def _read_tail(path: Path, max_bytes: int = 1_500_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def diagnose(
    *,
    logs_dir: Path | None = None,
    extensions_dir: Path | None = None,
) -> dict[str, Any]:
    logs_dir = logs_dir or logs_root()
    extensions_dir = extensions_dir or extensions_root()
    extensions = analyze_extensions(extensions_dir)
    files = _iter_log_files(logs_dir)
    chunks: list[str] = []
    used: list[str] = []
    for path in files:
        text = _read_tail(path)
        if not text:
            continue
        chunks.append(text)
        used.append(str(path))
    combined = "\n".join(chunks)
    findings = analyze_log_text(combined)
    summary = summarize_crash(findings, extensions)
    summary.update(
        {
            "logsDir": str(logs_dir),
            "extensionsDir": str(extensions_dir),
            "logFiles": used[:20],
            "recentExtensions": extensions[:12],
            "scannedBytes": len(combined.encode("utf-8", errors="ignore")),
        }
    )
    if not files:
        summary["headline"] = "找不到 Cursor 日志目录"
        summary["advice"] = f"预期路径：{logs_dir}"
    return summary
