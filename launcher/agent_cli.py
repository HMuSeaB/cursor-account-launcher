"""定位并启动 Cursor Agent CLI（带 crsr_ API Key）。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NEW_CONSOLE = 0x00000010

API_KEY_RE = re.compile(r"^crsr_[A-Za-z0-9]{16,}$")


def normalize_api_key(raw: str | None) -> str:
    return (raw or "").strip()


def validate_api_key(raw: str | None) -> str:
    key = normalize_api_key(raw)
    if not key:
        raise ValueError("API Key 为空")
    if not API_KEY_RE.match(key):
        raise ValueError("需要 Cursor API Key（crsr_…）")
    return key


def _cursor_agent_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "cursor-agent"


def _newest_version_dir(versions: Path) -> Path | None:
    if not versions.is_dir():
        return None
    dirs = [p for p in versions.iterdir() if p.is_dir()]
    if not dirs:
        return None
    dirs.sort(key=lambda p: p.name, reverse=True)
    return dirs[0]


def resolve_agent_cli() -> Path | None:
    """优先 %LOCALAPPDATA%\\cursor-agent，避免 PATH 上同名的其它 agent。"""
    root = _cursor_agent_root()
    for name in ("agent.cmd", "cursor-agent.cmd", "agent.ps1", "cursor-agent.ps1", "agent.exe"):
        path = root / name
        if path.is_file():
            return path
    version_dir = _newest_version_dir(root / "versions")
    if version_dir is not None:
        for name in ("agent.exe", "cursor-agent.exe", "agent.cmd", "cursor-agent.cmd"):
            path = version_dir / name
            if path.is_file():
                return path
    for name in ("cursor-agent", "agent"):
        found = shutil.which(name)
        if not found:
            continue
        path = Path(found)
        # PATH 命中时尽量确认是 Cursor 安装树，避免误开 grok 等同名工具
        parts = {p.lower() for p in path.parts}
        if "cursor-agent" in parts or "cursor" in parts:
            return path
    return None


def _ps_single_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def build_powershell_command(
    *,
    agent: Path,
    api_key: str,
    cwd: str | None = None,
    prompt: str | None = None,
) -> str:
    lines = [
        f"$env:CURSOR_API_KEY = {_ps_single_quote(api_key)}",
    ]
    if cwd:
        lines.append(f"Set-Location -LiteralPath {_ps_single_quote(cwd)}")
    agent_str = str(agent)
    text = (prompt or "").strip()
    invoke = f"& {_ps_single_quote(agent_str)}"
    if text:
        invoke += f" {_ps_single_quote(text)}"
    lines.append(invoke)
    lines.append('if ($LASTEXITCODE -ne 0) { Write-Host "" ; Write-Host "[Cursor Launcher] Agent 已退出 (Exit Code: $LASTEXITCODE)。" -ForegroundColor Yellow }')
    return "; ".join(lines)


def launch_agent_cli(
    *,
    api_key: str,
    cwd: str | None = None,
    prompt: str | None = None,
) -> dict:
    try:
        key = validate_api_key(api_key)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    agent = resolve_agent_cli()
    if agent is None:
        return {
            "ok": False,
            "error": "未找到 Cursor Agent CLI。请先安装：irm 'https://cursor.com/install?win32=true' | iex",
        }
    workdir = (cwd or "").strip() or None
    if workdir and not Path(workdir).is_dir():
        return {"ok": False, "error": f"工作目录不存在：{workdir}"}
    command = build_powershell_command(agent=agent, api_key=key, cwd=workdir, prompt=prompt)
    args = [
        "powershell.exe",
        "-NoLogo",
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]
    try:
        kwargs: dict = {
            "args": args,
            "cwd": workdir or None,
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NEW_CONSOLE
        subprocess.Popen(**kwargs)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "launched": True,
        "agentPath": str(agent),
        "cwd": workdir or "",
        "hasPrompt": bool((prompt or "").strip()),
    }
