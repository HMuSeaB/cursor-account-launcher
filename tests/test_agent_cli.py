"""Agent CLI：API Key 校验、路径解析、启动命令。"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher.agent_cli import (
    API_KEY_RE,
    build_powershell_command,
    normalize_api_key,
    resolve_agent_cli,
    validate_api_key,
)
from launcher.account_store import AccountStore


def test_validate_api_key_accepts_crsr():
    key = "crsr_" + ("a" * 64)
    assert validate_api_key(key) == key
    assert API_KEY_RE.match(key)


def test_validate_api_key_rejects_jwt_and_empty():
    with pytest.raises(ValueError):
        validate_api_key("")
    with pytest.raises(ValueError):
        validate_api_key("eyJhbGciOiJIUzI1NiJ9.xxx.yyy")
    with pytest.raises(ValueError):
        validate_api_key("cursor_not_crsr")


def test_build_powershell_command_quotes_key_and_prompt(tmp_path):
    agent = tmp_path / "agent.cmd"
    agent.write_text("@echo off\n", encoding="utf-8")
    key = "crsr_" + ("b" * 32)
    cmd = build_powershell_command(
        agent=agent,
        api_key=key,
        cwd=str(tmp_path),
        prompt="fix it's broken",
    )
    assert f"$env:CURSOR_API_KEY = '{key}'" in cmd
    assert "Set-Location -LiteralPath" in cmd
    assert "fix it''s broken" in cmd
    assert str(agent) in cmd


def test_resolve_prefers_localappdata_cursor_agent(tmp_path, monkeypatch):
    root = tmp_path / "cursor-agent"
    root.mkdir()
    launcher = root / "agent.cmd"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("launcher.agent_cli.shutil.which", lambda _name: str(tmp_path / "other" / "agent.exe"))
    assert resolve_agent_cli() == launcher


def test_resolve_falls_back_to_versioned_exe(tmp_path, monkeypatch):
    root = tmp_path / "cursor-agent" / "versions" / "2026.09.07-12-00-00-abcdef"
    root.mkdir(parents=True)
    exe = root / "agent.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("launcher.agent_cli.shutil.which", lambda _name: None)
    assert resolve_agent_cli() == exe


def test_account_store_api_key_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    store = AccountStore()
    uid = "user_cli_test"
    store._items[uid] = {
        "id": uid,
        "label": "cli@test.com",
        "token": "user_cli_test::eyJ.fake.sig",
        "_prio": 5,
        "email": "cli@test.com",
        "passwordEnc": "",
        "refreshTokenEnc": "",
        "apiKeyEnc": "",
        "group": "未分组",
        "tags": [],
        "remark": "",
        "createdAt": 1,
        "deviceIds": {},
    }
    key = "crsr_" + ("c" * 40)
    updated = store.set_api_key(uid, key)
    assert updated is not None
    assert updated["hasApiKey"] is True
    assert store.get_api_key(uid) == key
    detail = store.get_detail(uid)
    assert detail["apiKey"] == key
    store.set_api_key(uid, "")
    assert store.get_api_key(uid) == ""
    assert store.list()[0]["hasApiKey"] is False


def test_normalize_strips():
    assert normalize_api_key("  crsr_abc  ") == "crsr_abc"
