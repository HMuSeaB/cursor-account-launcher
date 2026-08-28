"""cursor_update helpers."""

from pathlib import Path

from launcher.cursor_update import apply_disable_updates, read_update_status, restore_updates


def test_apply_disable_updates_writes_settings(tmp_path, monkeypatch):
    settings = tmp_path / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"cursorYc.mode":"local"}\n', encoding="utf-8")

    monkeypatch.setattr("launcher.local_cursor.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_proxy.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_update._load_config", lambda: {})
    monkeypatch.setattr(
        "launcher.cursor_update.update_config",
        lambda **kw: {"disableAutoUpdate": kw.get("disableAutoUpdate")},
    )

    install = tmp_path / "cursor"
    tools = install / "tools"
    tools.mkdir(parents=True)
    updater = tools / "inno_updater.exe"
    updater.write_bytes(b"fake")

    res = apply_disable_updates(install)
    assert res["ok"] is True
    import json

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["update.mode"] == "none"
    assert data["update.enableWindowsBackgroundUpdates"] is False
    assert data["cursorYc.mode"] == "local"
    assert not updater.is_file()
    assert (tools / "inno_updater.exe.disabled").is_file()


def test_read_update_status_detects_disabled(tmp_path, monkeypatch):
    settings = tmp_path / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        '{"update.mode":"none","update.enableWindowsBackgroundUpdates":false}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("launcher.local_cursor.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_proxy.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_update._load_config", lambda: {"disableAutoUpdate": True})

    install = tmp_path / "cursor"
    tools = install / "tools"
    tools.mkdir(parents=True)
    (tools / "inno_updater.exe.disabled").write_bytes(b"x")

    st = read_update_status(install)
    assert st["settingsBlocked"] is True
    assert st["innoUpdaterDisabled"] is True


def test_restore_updates(tmp_path, monkeypatch):
    settings = tmp_path / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        '{"update.mode":"none","update.enableWindowsBackgroundUpdates":false,"keep":1}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("launcher.local_cursor.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_proxy.settings_json_path", lambda: str(settings))
    monkeypatch.setattr("launcher.cursor_update.update_config", lambda **kw: kw)

    install = tmp_path / "cursor"
    tools = install / "tools"
    tools.mkdir(parents=True)
    (tools / "inno_updater.exe.disabled").write_bytes(b"x")

    res = restore_updates(install)
    assert res["ok"] is True
    import json

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "update.mode" not in data
    assert data["keep"] == 1
    assert (tools / "inno_updater.exe").is_file()
