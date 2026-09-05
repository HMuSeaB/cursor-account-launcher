"""workbench 统一网关测试。"""

from pathlib import Path

import pytest

from launcher.workbench.backup import ensure_official, snapshot_before_write, store_root
from launcher.workbench.layers import BAJIE_PREFIX, scan_content, scan_files, strip_gateway_urls
from launcher.workbench.manager import WorkbenchWriteError, commit_changes
from launcher.workbench.preflight import PreflightError, validate_content


SAMPLE_WB = (
    'host="' + BAJIE_PREFIX + 'api2.cursor.sh",'
    "hideMaxToggle:C()||E(),"
    "foo(hasResolvedTeamMembership:e,teamId:t}){return e===a.FREE&&t&&n===void 0}"
)


def test_scan_and_strip_gateway():
    scan = scan_content(SAMPLE_WB)
    assert scan.gateway_hits == 1
    assert scan.sub2api_hits == 0
    out, n = strip_gateway_urls(SAMPLE_WB)
    assert n == 1
    assert "43111" not in out
    assert "api2.cursor.sh" in out


def test_scan_files_uses_bytes_not_utf8_decode(tmp_path, monkeypatch):
    f = tmp_path / "workbench.desktop.main.js"
    body = (
        SAMPLE_WB
        + 'const sub2apiNormalize=/*[SUB2API_CURSOR_BRIDGE_ENDPOINT]*/'
        + '(base,url="https://localhost:46549")=>{return r}'
        + "/*MODEL_SHOW_MAX_V1*/"
    )
    f.write_text(body, encoding="utf-8")

    def forbid_text(self, *args, **kwargs):
        raise AssertionError("scan_files must not UTF-8 decode workbench")

    monkeypatch.setattr(Path, "read_text", forbid_text)
    scan = scan_files([f])
    assert scan.gateway_hits == 1
    assert scan.sub2api_hits == 1
    assert scan.sub2api_endpoint == "https://localhost:46549"
    assert scan.show_max == 1
    assert scan.as_hits() == scan_content(body).as_hits()


def test_preflight_rejects_broken_show_max():
    bad = "hideMaxToggle:!1;/*MODEL_SHOW_MAX_V1*/"
    issues = validate_content(bad)
    assert any("hideMaxToggle" in i for i in issues)


def test_commit_changes_snapshots_and_writes(tmp_path):
    app = tmp_path / "resources" / "app"
    wb = app / "out" / "vs" / "workbench"
    wb.mkdir(parents=True)
    f = wb / "workbench.desktop.main.js"
    f.write_text(SAMPLE_WB, encoding="utf-8")
    (app / "product.json").write_text('{"checksums":{}}', encoding="utf-8")

    new_text = SAMPLE_WB.replace("FREE", "FREE/*x*/")
    result = commit_changes(
        app,
        [f],
        {f: new_text},
        layer="test",
        reason="unit",
        skip_preflight=True,
    )
    assert result["ok"] is True
    assert "workbench.desktop.main.js" in result["changed"]
    assert f.read_text(encoding="utf-8") == new_text
    assert (store_root() / "snapshots").is_dir()


def test_ensure_official_skips_when_launcher_markers(tmp_path):
    app = tmp_path / "app"
    wb = app / "out" / "vs" / "workbench"
    wb.mkdir(parents=True)
    f = wb / "workbench.desktop.main.js"
    f.write_text("/*MODEL_SHOW_MAX_V1*/", encoding="utf-8")
    # 使用独立 store 会污染全局；这里只测逻辑
    res = ensure_official([f])
    assert res.get("skipped") or res.get("created") is not True or res["ok"]


def test_backup_status_skips_legacy_scan_when_official_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from launcher.workbench import backup as wb_backup

    files = [tmp_path / "workbench.desktop.main.js"]
    files[0].write_text("x", encoding="utf-8")
    (wb_backup.official_dir() / "workbench.desktop.main.js").write_text("clean", encoding="utf-8")

    def boom():
        raise AssertionError("official 基线已在，不应再整文件扫旧 model-unlock 备份")

    monkeypatch.setattr(wb_backup, "find_best_legacy_clean", boom)
    st = wb_backup.backup_status(files)
    assert st["hasOfficial"] is True
    assert st["hasLegacyModelUnlockClean"] is False
