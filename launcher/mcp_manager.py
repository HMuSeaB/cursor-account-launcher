"""Cursor 插件与 CLI MCP 服务管理：扫描、启停与安全删除。"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path


def _get_global_mcp_path() -> Path:
    user_home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return Path(user_home) / ".cursor" / "mcp.json"


def _get_candidate_mcp_paths(
    workspace: str | None = None,
    auto_detect_cwd: bool = True,
) -> list[tuple[str, Path]]:
    """返回候选 mcp.json 路径列表：(scope, path)。"""
    paths: list[tuple[str, Path]] = []
    
    # 1. 用户全局（影响 Cursor IDE 和独立 CLI）
    global_path = _get_global_mcp_path()
    paths.append(("global", global_path))
    
    # 2. 指定的工作区
    if workspace:
        w_path = Path(workspace).resolve() / ".cursor" / "mcp.json"
        if (w_path != global_path) and (("workspace", w_path) not in paths):
            paths.append(("workspace", w_path))

    # 3. 常见工作区候选（如启动器所在的父目录或当前目录）
    if auto_detect_cwd and not workspace:
        cwd = Path.cwd().resolve()
        for candidate_root in (cwd, cwd.parent):
            cand = candidate_root / ".cursor" / "mcp.json"
            if cand.is_file() and (cand != global_path):
                entry = ("workspace", cand)
                if entry not in paths:
                    paths.append(entry)

    return paths


def _clean_json_comments(text: str) -> str:
    """去除简易的 // 单行注释与末尾悬挂逗号，提高容错率。"""
    # 去除 // 开头的单行注释
    cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    # 去除形如 , } 或 , ] 的末尾悬挂逗号
    cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
    return cleaned


def _read_mcp_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        try:
            return json.loads(content)
        except Exception:
            return json.loads(_clean_json_comments(content))
    except Exception:
        return {}


def _write_mcp_file(path: Path, data: dict, backup_suffix: str = ".bak") -> Path:
    """安全原子写入并先创建备份。"""
    if path.is_file():
        bak_path = path.with_name(path.name + backup_suffix)
        shutil.copy2(path, bak_path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        bak_path = path

    temp_file = path.with_suffix(".tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temp_file.write_text(text, encoding="utf-8")
    temp_file.replace(path)
    return bak_path


def _detect_associated_dirs(server_name: str, server_conf: dict) -> list[str]:
    """探测该 MCP 服务可能产生在 ~/.cursor/ 下的独立数据/服务目录。"""
    dirs: list[str] = []
    user_cursor = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~")) / ".cursor"
    if not user_cursor.is_dir():
        return dirs

    candidates = [
        user_cursor / f"{server_name}-server",
        user_cursor / f"{server_name}-messages",
        user_cursor / f"{server_name}-daemon",
        user_cursor / server_name,
    ]

    # 从 args 或 env 中抓取可能存在的绝对路径
    tokens: list[str] = []
    for arg in server_conf.get("args") or []:
        if isinstance(arg, str):
            tokens.append(arg)
    for v in (server_conf.get("env") or {}).values():
        if isinstance(v, str):
            tokens.append(v)

    for token in tokens:
        # 寻找形如 C:/.../.cursor/xxx 的路径
        match = re.search(r"([A-Za-z]:[\\/][^\"';,\r\n]+)", token)
        if match:
            cand = Path(match.group(1))
            if cand.is_dir() and str(user_cursor).lower() in str(cand).lower() and cand != user_cursor:
                candidates.append(cand)

    seen = set()
    for c in candidates:
        try:
            if c.is_dir() and str(c) not in seen:
                # 严格限制：只清理 .cursor 根目录下的专属子文件夹，绝不越界
                if c.parent.resolve() == user_cursor.resolve():
                    dirs.append(str(c))
                    seen.add(str(c))
        except Exception:
            continue

    return dirs


def list_mcp_servers(
    workspace: str | None = None,
    auto_detect_cwd: bool = True,
) -> list[dict]:
    """扫描所有发现的 mcp.json 并汇总服务列表。"""
    candidates = _get_candidate_mcp_paths(workspace, auto_detect_cwd=auto_detect_cwd)
    servers: list[dict] = []

    for scope, path in candidates:
        if not path.is_file():
            continue
        data = _read_mcp_file(path)
        mcp_servers = data.get("mcpServers")
        if not isinstance(mcp_servers, dict):
            continue

        for name, conf in mcp_servers.items():
            if not isinstance(conf, dict):
                continue

            disabled = bool(conf.get("disabled", False))
            command = str(conf.get("command") or "")
            args = list(conf.get("args") or [])
            env = dict(conf.get("env") or {})
            
            # 判断是否疑似第三方扩展插件注入
            lower_name = name.lower()
            cmd_lower = command.lower()
            args_str = " ".join(str(a) for a in args).lower()
            is_plugin = any(
                k in lower_name or k in cmd_lower or k in args_str
                for k in ("tiancai", "tc-mcp", "bajie", "salak", "grok", ".cursor")
            )

            extra_dirs = _detect_associated_dirs(name, conf)

            servers.append({
                "id": f"{scope}:{path}:{name}",
                "name": name,
                "scope": scope,
                "scopeLabel": "全局配置 (CLI & IDE)" if scope == "global" else "工作区配置",
                "filePath": str(path),
                "command": command,
                "args": args,
                "env": env,
                "disabled": disabled,
                "isPlugin": is_plugin,
                "extraDirs": extra_dirs,
            })

    return servers


def toggle_mcp_server(file_path: str, server_name: str, disabled: bool) -> dict:
    """一键切换 MCP 服务的禁用/启用状态。"""
    target = Path(file_path).resolve()
    if not target.is_file():
        return {"ok": False, "error": f"配置文件不存在: {file_path}"}

    data = _read_mcp_file(target)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or server_name not in servers:
        return {"ok": False, "error": f"在 {target.name} 中未找到服务: {server_name}"}

    if not isinstance(servers[server_name], dict):
        return {"ok": False, "error": f"服务 {server_name} 配置格式非法"}

    servers[server_name]["disabled"] = bool(disabled)
    try:
        bak = _write_mcp_file(target, data, backup_suffix=".bak")
        return {
            "ok": True,
            "serverName": server_name,
            "disabled": bool(disabled),
            "filePath": str(target),
            "backupPath": str(bak),
        }
    except Exception as exc:
        return {"ok": False, "error": f"写入配置失败: {exc}"}


def delete_mcp_server(
    file_path: str,
    server_name: str,
    cleanup_data: bool = False,
) -> dict:
    """彻底从配置文件中移除 MCP 服务，并生成带时间戳的安全备份。"""
    target = Path(file_path).resolve()
    if not target.is_file():
        return {"ok": False, "error": f"配置文件不存在: {file_path}"}

    data = _read_mcp_file(target)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or server_name not in servers:
        return {"ok": False, "error": f"在 {target.name} 中未找到服务: {server_name}"}

    conf = servers[server_name]
    associated_dirs = _detect_associated_dirs(server_name, conf) if isinstance(conf, dict) else []

    # 1. 彻底删除配置节点并写入
    del servers[server_name]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    purge_bak_suffix = f".bak-purge-{timestamp}"
    try:
        bak = _write_mcp_file(target, data, backup_suffix=purge_bak_suffix)
    except Exception as exc:
        return {"ok": False, "error": f"保存删除改动失败: {exc}"}

    # 2. 如果勾选了清理数据，且探测到了安全作用域内的子目录，则归档或清理
    cleaned_dirs: list[str] = []
    if cleanup_data and associated_dirs:
        for d in associated_dirs:
            dp = Path(d)
            if dp.is_dir():
                try:
                    # 优先重命名为 .deleted_<timestamp>，避免误删无法恢复
                    trash_name = dp.with_name(f"{dp.name}.deleted_{timestamp}")
                    dp.rename(trash_name)
                    cleaned_dirs.append(f"{dp.name} -> {trash_name.name}")
                except Exception as exc:
                    cleaned_dirs.append(f"{dp.name} (清理失败: {exc})")

    return {
        "ok": True,
        "serverName": server_name,
        "filePath": str(target),
        "backupPath": str(bak),
        "cleanedDirs": cleaned_dirs,
    }
