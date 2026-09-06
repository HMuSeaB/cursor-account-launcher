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


def test_preflight_allows_minified_js_already_unbalanced():
    """3.18+ workbench 含正则字面量，粗括号扫描对原文就会 mismatch；不能因此拒绝 MAX。"""
    from launcher.workbench.preflight import _balance_score

    original = "var r=/)/;const o={hideMaxToggle:C()||E()};" + ("x" * 2000)
    patched = original.replace(
        "hideMaxToggle:C()||E()",
        "hideMaxToggle:!1/*MODEL_SHOW_MAX_V1*//*ORIG:C()||E()*/",
    )
    orig_bal = _balance_score(original)
    assert orig_bal["ok"] == 0
    issues = validate_content(patched, original=original)
    assert not any("括号" in i for i in issues)


def test_preflight_rejects_when_patch_worsens_balance():
    original = "const o={ok:!0};" + ("x" * 2000)
    patched = original + "{{{"
    issues = validate_content(patched, original=original)
    assert any("失衡" in i or "括号" in i for i in issues)


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


def test_plan_autofix_sub2api_counts_as_gateway():
    report = {
        "ok": True,
        "cursorRunning": False,
        "layers": {"gateway": 0, "sub2api": 1},
        "modelUnlock": {"installed": True, "maxOnly": True, "corrupted": False},
        "ctxwin": {"patched": True},
        "proxy": {
            "preference": {"enabled": True, "bypass_gateway": False},
            "live": {"argvProxyServer": "socks5://127.0.0.1:7891"},
        },
    }
    plan = plan_autofix(report)
    assert plan["ready"] is True
    assert not any(s["id"] == "gateway" for s in plan["steps"])


def test_plan_autofix_missing_wall_is_manual_extension_only():
    report = {
        "ok": True,
        "cursorRunning": False,
        "layers": {"gateway": 0, "sub2api": 0},
        "modelUnlock": {"installed": True, "maxOnly": True, "corrupted": False},
        "ctxwin": {"patched": True},
        "proxy": {
            "preference": {"enabled": True, "bypass_gateway": False},
            "live": {"argvProxyServer": "socks5://127.0.0.1:7891"},
        },
    }
    plan = plan_autofix(report)
    gw = [s for s in plan["steps"] if s["id"] == "gateway"]
    assert len(gw) == 1
    assert gw[0].get("manual") is True
    assert gw[0].get("inspectOnly") is True
    assert "检查" in gw[0]["label"]
    assert plan["ready"] is True


def test_note_cursor_version_ignores_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from launcher.versioning import cursor_upgrade_status, note_cursor_version

    first = note_cursor_version("3.18.9")
    assert first["upgraded"] is False
    assert first["needsRepatch"] is False

    unread = note_cursor_version("?")
    assert unread["upgraded"] is False
    assert unread.get("unreadable") is True
    st = cursor_upgrade_status()
    assert st["lastVersion"] == "3.18.9"
    assert st["needsRepatch"] is False


def test_note_cursor_version_does_not_treat_question_mark_as_previous(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from launcher.versioning import note_cursor_version

    store = tmp_path / "CursorLauncher"
    store.mkdir(parents=True)
    (store / "cursor-version.json").write_text(
        '{"lastVersion":"?","previousVersion":"?","needsRepatch":true}\n',
        encoding="utf-8",
    )
    out = note_cursor_version("3.18.9")
    assert out["upgraded"] is False
    assert out["needsRepatch"] is False
    assert out["version"] == "3.18.9"
    assert out["previousVersion"] == ""


def test_note_cursor_version_real_upgrade_still_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from launcher.versioning import note_cursor_version

    note_cursor_version("3.12.30")
    out = note_cursor_version("3.18.9")
    assert out["upgraded"] is True
    assert out["needsRepatch"] is True
    assert out["previousVersion"] == "3.12.30"


def test_read_version_empty_when_product_missing(tmp_path):
    from launcher.cursor_process import _read_version

    assert _read_version(tmp_path) == ""


def test_read_version_falls_back_to_package_json(tmp_path):
    from launcher.cursor_process import _read_version

    app = tmp_path / "resources" / "app"
    app.mkdir(parents=True)
    (app / "package.json").write_text('{"version":"3.18.9"}', encoding="utf-8")
    assert _read_version(tmp_path) == "3.18.9"
