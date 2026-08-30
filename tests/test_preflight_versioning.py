"""preflight / autofix / versioning unit tests."""

import json

from launcher.versioning import LAUNCHER_VERSION, _parse_semver
from launcher.workbench.autofix import plan_autofix
from launcher.workbench.preflight import validate_content


def test_semver_compare():
    assert _parse_semver("1.3.5") > _parse_semver("1.3.4")
    assert _parse_semver("v1.3.4") == _parse_semver("1.3.4")
    assert LAUNCHER_VERSION


def test_preflight_rejects_broken_and_imbalance():
    bad = "hideMaxToggle:!1;/*MODEL_SHOW_MAX_V1*/ {{{"
    issues = validate_content(bad)
    assert any("hideMaxToggle" in i or "括号" in i for i in issues)


def test_preflight_length_guard():
    original = "x" * 10000 + "{}"
    shortened = "x" * 100
    issues = validate_content(shortened, original=original)
    assert any("缩短" in i or "过短" in i for i in issues)


def test_plan_autofix_not_circular_when_nested_in_report():
    """模拟 diagnostic 把 autofix 挂回 report 后仍可 json 序列化。"""
    report = {
        "ok": True,
        "cursorRunning": False,
        "layers": {"gateway": 1},
        "modelUnlock": {"installed": True, "maxOnly": True, "corrupted": False},
        "ctxwin": {"patched": True},
        "proxy": {
            "preference": {"enabled": True, "bypass_gateway": False},
            "live": {"argvProxyServer": "socks5://127.0.0.1:7891"},
        },
    }
    report["autofix"] = plan_autofix(report)
    json.dumps(report)  # must not raise Circular reference
    assert "diagnostic" not in report["autofix"]
