"""MCP 管理模块单元测试：扫描、禁用与安全删除。"""

from __future__ import annotations

import json
from pathlib import Path

from launcher.mcp_manager import (
    delete_mcp_server,
    list_mcp_servers,
    toggle_mcp_server,
)


def test_list_and_toggle_mcp_servers(tmp_path, monkeypatch):
    # 模拟全局 .cursor/mcp.json
    global_dir = tmp_path / ".cursor"
    global_dir.mkdir()
    global_mcp = global_dir / "mcp.json"
    global_mcp.write_text(
        json.dumps({
            "mcpServers": {
                "Tiancai": {
                    "command": "node.exe",
                    "args": ["server.js"],
                    "disabled": False,
                },
                "DisabledServer": {
                    "command": "python.exe",
                    "disabled": True,
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    # 扫描
    servers = list_mcp_servers(auto_detect_cwd=False)
    assert len(servers) == 2
    names = {s["name"] for s in servers}
    assert "Tiancai" in names
    assert "DisabledServer" in names

    tiancai = next(s for s in servers if s["name"] == "Tiancai")
    assert tiancai["disabled"] is False
    assert tiancai["scope"] == "global"

    # 切换禁用
    res = toggle_mcp_server(str(global_mcp), "Tiancai", True)
    assert res["ok"] is True
    assert res["disabled"] is True
    assert Path(global_mcp).name + ".bak" in res["backupPath"]

    # 验证写回
    after = json.loads(global_mcp.read_text(encoding="utf-8"))
    assert after["mcpServers"]["Tiancai"]["disabled"] is True

    # 切换回启用
    res2 = toggle_mcp_server(str(global_mcp), "Tiancai", False)
    assert res2["ok"] is True
    assert res2["disabled"] is False
    after2 = json.loads(global_mcp.read_text(encoding="utf-8"))
    assert after2["mcpServers"]["Tiancai"]["disabled"] is False


def test_delete_mcp_server_with_backup(tmp_path, monkeypatch):
    global_dir = tmp_path / ".cursor"
    global_dir.mkdir()
    global_mcp = global_dir / "mcp.json"
    global_mcp.write_text(
        json.dumps({
            "mcpServers": {
                "ServerToDelete": {"command": "test.exe"},
                "ServerToKeep": {"command": "keep.exe"},
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    del_res = delete_mcp_server(str(global_mcp), "ServerToDelete")
    assert del_res["ok"] is True
    assert "bak-purge-" in del_res["backupPath"]
    assert Path(del_res["backupPath"]).is_file()

    # 确认原文件仅剩 ServerToKeep
    data = json.loads(global_mcp.read_text(encoding="utf-8"))
    assert "ServerToDelete" not in data["mcpServers"]
    assert "ServerToKeep" in data["mcpServers"]


def test_toggle_nonexistent_server_fails(tmp_path):
    fake_file = tmp_path / "mcp.json"
    fake_file.write_text('{"mcpServers": {}}', encoding="utf-8")
    res = toggle_mcp_server(str(fake_file), "GhostServer", True)
    assert res["ok"] is False
    assert "未找到服务" in res["error"]
