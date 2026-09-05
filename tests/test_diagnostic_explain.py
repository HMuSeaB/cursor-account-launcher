"""模型墙 / 旧版风格诊断文案：纯函数，不读真实 Cursor 安装。"""

from launcher.cursor_process import _is_main_cursor_cmd, classic_launch_status
from launcher.workbench.diagnostic import (
    classify_extension_name,
    explain_classic_style,
    explain_model_wall,
    find_gateway_extensions,
)
from launcher.workbench.layers import scan_content


def test_classify_extension_names():
    assert classify_extension_name("local.cursor-yc-3.4.9") == "yc"
    assert classify_extension_name("henxinfwq.sub2api-cursor-0.2.97") == "sub2api"
    assert classify_extension_name("bajie.bajie-chat-0.7.31") == "other"
    assert classify_extension_name("cursor-yc-bajie-1.0.0") == "yc"
    assert classify_extension_name("unrelated-theme-9") == ""


def test_wall_yc_present_even_if_other_flags():
    wall = explain_model_wall(gateway_hits=2, stripped=True, upgraded=True)
    assert wall["present"] is True
    assert wall["active"] == "yc"
    assert wall["canRestoreGateway"] is False
    assert "YC" in wall["title"]
    assert wall["yc"]["hits"] == 2


def test_wall_sub2api_is_not_missing_bajie():
    wall = explain_model_wall(
        gateway_hits=0,
        stripped=False,
        upgraded=False,
        sub2api_hits=1,
        sub2api_endpoint="https://localhost:46549",
        extensions={"yc": ["local.cursor-yc-3.4.9"], "sub2api": ["henxinfwq.sub2api-cursor-0.2.97"], "other": []},
    )
    assert wall["present"] is True
    assert wall["active"] == "sub2api"
    assert wall["canRestoreGateway"] is False
    assert "46549" in wall["why"]
    assert "窄" in wall["title"] or "窄" in wall["why"]
    assert "误报" in wall["why"]
    assert "YC" in wall["action"]


def test_wall_both_is_conflict():
    wall = explain_model_wall(
        gateway_hits=13,
        stripped=False,
        upgraded=False,
        sub2api_hits=1,
        sub2api_endpoint="https://localhost:46549",
        extensions={"yc": ["local.cursor-yc-3.4.9"], "sub2api": ["henxinfwq.sub2api-cursor-0.2.97"], "other": []},
    )
    assert wall["present"] is True
    assert wall["active"] == "both"
    assert wall["cause"] == "conflict"
    assert wall["canRestoreGateway"] is False
    assert "叠" in wall["title"]


def test_wall_stripped_with_backup():
    wall = explain_model_wall(
        gateway_hits=0,
        stripped=True,
        upgraded=False,
        has_bajie_backup=True,
        extension_ids=["cursor-yc-bajie-1.0.0"],
    )
    assert wall["present"] is False
    assert wall["active"] == "none"
    assert wall["cause"] == "stripped"
    assert wall["canRestoreGateway"] is True
    assert "改回官方" in wall["why"]
    assert "不要重装" in wall["action"] or "不要重装" in wall["why"]
    assert "YC 扩展还在" in wall["why"]


def test_wall_upgraded_without_backup():
    wall = explain_model_wall(
        gateway_hits=0,
        stripped=False,
        upgraded=True,
        previous_version="3.12.30",
        current_version="3.18.9",
        has_bajie_backup=False,
        updates_blocked=False,
    )
    assert wall["cause"] == "upgraded"
    assert wall["active"] == "none"
    assert "3.12.30" in wall["why"]
    assert "3.18.9" in wall["why"]
    assert "重装" in wall["why"]
    assert wall["canRestoreGateway"] is False
    assert "自动更新" in wall["action"]
    assert "没扫到 YC 扩展" in wall["why"]


def test_wall_overwritten_has_backup():
    wall = explain_model_wall(
        gateway_hits=0,
        stripped=False,
        upgraded=False,
        has_bajie_backup=True,
        extension_ids=["publisher.cursor-gateway-2"],
    )
    assert wall["cause"] == "overwritten"
    assert wall["canRestoreGateway"] is True
    assert "备份" in wall["why"]
    assert "恢复 YC" in wall["action"] or "bajie" in wall["action"].casefold()


def test_wall_missing():
    wall = explain_model_wall(gateway_hits=0, stripped=False, upgraded=False)
    assert wall["cause"] == "missing"
    assert wall["active"] == "none"
    assert wall["canRestoreGateway"] is False
    assert "官方目录" in wall["why"]
    assert "不要重装" in wall["action"]


def test_wall_stripped_beats_upgraded_when_neither_patch():
    wall = explain_model_wall(gateway_hits=0, stripped=True, upgraded=True, has_bajie_backup=True)
    assert wall["cause"] == "stripped"
    assert wall["active"] == "none"


def test_scan_sub2api_endpoint():
    snippet = (
        'const sub2apiNormalize=/*[SUB2API_CURSOR_BRIDGE_ENDPOINT]*/'
        '(base,url="https://localhost:46549")=>{return r}'
        "/*[SUB2API_CURSOR_GATEWAY_MEMBERSHIP]*/"
    )
    scan = scan_content(snippet)
    assert scan.gateway_hits == 0
    assert scan.sub2api_hits == 1
    assert scan.sub2api_endpoint == "https://localhost:46549"
    assert scan.sub2api_markers >= 2


def test_classic_lost_when_running_without_flag():
    st = explain_classic_style(
        {"running": True, "lost": True, "usingClassic": False, "sampled": 1}
    )
    assert st["lost"] is True
    assert "覆盖" in st["title"]
    assert "--classic" in st["why"]
    assert "启动器" in st["action"]


def test_classic_ok_when_flag_present():
    st = explain_classic_style(
        {"running": True, "lost": False, "usingClassic": True, "sampled": 1}
    )
    assert st["lost"] is False
    assert "还在" in st["title"]


def test_classic_not_running_does_not_claim_lost():
    st = explain_classic_style(
        {"running": False, "lost": True, "usingClassic": False, "sampled": 0}
    )
    assert st["lost"] is False
    assert "启动器" in st["title"]


def test_classic_unknown_when_running_but_unreadable():
    st = explain_classic_style(
        {"running": True, "lost": False, "usingClassic": None, "sampled": 3}
    )
    assert st["lost"] is False
    assert "无法判定" in st["title"]


def test_main_cmd_ignores_gpu_child():
    assert _is_main_cursor_cmd(r"C:\Cursor\Cursor.exe --type=gpu-process") is False
    assert _is_main_cursor_cmd(r"C:\Tools\cursor\Cursor.exe") is True
    assert _is_main_cursor_cmd(r'"C:\Tools\cursor\Cursor.exe" --classic') is True
    assert _is_main_cursor_cmd("") is False


def test_classic_launch_status_injected_lines():
    lost = classic_launch_status(command_lines=[r"C:\Cursor\Cursor.exe"])
    assert lost["lost"] is True
    assert lost["usingClassic"] is False

    ok = classic_launch_status(command_lines=[r"C:\Cursor\Cursor.exe --classic"])
    assert ok["lost"] is False
    assert ok["usingClassic"] is True

    gpu = classic_launch_status(command_lines=[r"C:\Cursor\Cursor.exe --type=gpu-process"])
    assert gpu["usingClassic"] is None
    assert gpu["lost"] is False


def test_find_gateway_extensions(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ext = home / ".cursor" / "extensions"
    (ext / "local.cursor-yc-3.4.9").mkdir(parents=True)
    (ext / "henxinfwq.sub2api-cursor-0.2.97").mkdir()
    (ext / "bajie.bajie-chat-0.7.31").mkdir()
    (ext / "unrelated-theme-9").mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("APPDATA", raising=False)
    found = find_gateway_extensions()
    assert found["yc"] == ["local.cursor-yc-3.4.9"]
    assert found["sub2api"] == ["henxinfwq.sub2api-cursor-0.2.97"]
    assert found["other"] == ["bajie.bajie-chat-0.7.31"]
