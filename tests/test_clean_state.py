"""干净基线：同版本可还原，跨版本拒绝覆盖。"""

import json
from pathlib import Path

from launcher.workbench.clean import (
    backup_version_matches,
    files_look_clean,
    pin_clean_now,
    restore_pinned_files,
    restore_to_clean,
)


def _install(tmp_path: Path, version: str, body: str = "clean-body") -> tuple[Path, Path, Path]:
    app = tmp_path / "resources" / "app"
    wb = app / "out" / "vs" / "workbench"
    host_dir = wb / "api" / "node"
    host_dir.mkdir(parents=True)
    desktop = wb / "workbench.desktop.main.js"
    desktop.write_text(body, encoding="utf-8")
    host = host_dir / "extensionHostProcess.js"
    host.write_text("host-clean", encoding="utf-8")
    product = app / "product.json"
    product.write_text(json.dumps({"version": version, "checksums": {}}), encoding="utf-8")
    return app, desktop, host


def test_pin_skips_launcher_markers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app, desktop, host = _install(tmp_path, "2.0.0", "/*MODEL_SHOW_MAX_V1*/")
    res = pin_clean_now([desktop], host, _app / "product.json")
    assert res["skipped"] is True
    assert res["reason"] == "dirty"
    assert res["pinned"] is False


def test_pin_and_restore_same_version_keeps_product_version(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app, desktop, host = _install(tmp_path, "2.0.0", "clean-body")
    product = app / "product.json"
    pinned = pin_clean_now([desktop], host, product)
    assert pinned["created"] is True
    assert pinned["sameVersion"] is True

    desktop.write_text("patched-body", encoding="utf-8")
    product.write_text(json.dumps({"version": "2.0.0", "checksums": {"keep": "1"}}), encoding="utf-8")
    restored = restore_pinned_files([desktop], host, product)
    assert restored["ok"] is True
    assert desktop.read_text(encoding="utf-8") == "clean-body"
    assert json.loads(product.read_text(encoding="utf-8"))["version"] == "2.0.0"


def test_restore_refuses_other_version(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app, desktop, host = _install(tmp_path, "2.0.0", "clean-body")
    product = app / "product.json"
    assert pin_clean_now([desktop], host, product)["created"] is True

    desktop.write_text("newer-install", encoding="utf-8")
    product.write_text(json.dumps({"version": "3.0.0"}), encoding="utf-8")
    restored = restore_pinned_files([desktop], host, product)
    assert restored["skipped"] is True
    assert restored["reason"] == "version-mismatch"
    assert desktop.read_text(encoding="utf-8") == "newer-install"
    assert backup_version_matches(Path(restored.get("path", "")), product) is False


def test_backup_version_must_match(tmp_path):
    app, _desktop, _host = _install(tmp_path, "2.0.0")
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "product.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
    assert backup_version_matches(backup, app / "product.json") is False
    (backup / "product.json").write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    assert backup_version_matches(backup, app / "product.json") is True


def test_files_look_clean_rejects_sand_marker(tmp_path):
    _app, desktop, host = _install(tmp_path, "2.0.0", "/*SAND_DIRECT_INFERENCE_STREAM_V1*/")
    ok, why = files_look_clean([desktop], host)
    assert ok is False
    assert "Grok Bot" in why


def test_restore_to_clean_does_not_overlay_other_version(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app, desktop, host = _install(tmp_path, "3.0.0", "current-clean")
    product = app / "product.json"

    from launcher.workbench import clean as clean_mod

    dest = clean_mod.clean_dir()
    (dest / "workbench.desktop.main.js").write_text("OLD", encoding="utf-8")
    (dest / "manifest.json").write_text(
        json.dumps({"version": "1.0.0", "files": ["workbench.desktop.main.js"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(clean_mod, "is_cursor_running", lambda: False)
    monkeypatch.setattr(
        clean_mod,
        "resolve_layout",
        lambda: (None, app, [desktop]),
    )
    monkeypatch.setattr(
        "launcher.sand_stream.restore",
        lambda *args, **kwargs: {"ok": True, "skipped": True, "message": "无 Bot"},
    )
    monkeypatch.setattr(
        "launcher.model_unlock.restore",
        lambda: {"ok": True, "skipped": True, "message": "无解锁"},
    )
    monkeypatch.setattr(
        "launcher.ctxwin.ctxwin_status",
        lambda: {"patched": False},
    )
    monkeypatch.setattr(
        "launcher.ctxwin.host_js_path",
        lambda _root: host,
    )
    monkeypatch.setattr(
        "launcher.bot_gateway_ctl.is_gateway_mode",
        lambda: False,
    )
    monkeypatch.setattr(
        "launcher.bot_gateway_ctl.gateway_process_status",
        lambda: {"running": False},
    )

    out = restore_to_clean()
    assert out["ok"] is True
    assert desktop.read_text(encoding="utf-8") == "current-clean"
    assert any(step["id"] == "snapshot" and step["skipped"] for step in out["steps"])
