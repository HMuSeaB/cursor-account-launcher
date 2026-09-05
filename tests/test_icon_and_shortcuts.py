"""App icon renderer and shortcut helpers."""

from pathlib import Path

from launcher.shortcuts import _ps_quote, create_shortcuts, is_frozen, shortcut_status

ROOT = Path(__file__).resolve().parent.parent


def test_ps_quote_escapes_single_quotes():
    assert _ps_quote(r"C:\O'Brien\app.exe") == r"'C:\O''Brien\app.exe'"


def test_source_run_cannot_create_shortcuts():
    assert is_frozen() is False
    st = shortcut_status()
    assert st["ok"] is True
    assert st["canCreate"] is False
    assert st["exe"] == ""
    denied = create_shortcuts(desktop=True)
    assert denied["ok"] is False


def test_versioned_icon_persist_uses_version_in_name(tmp_path, monkeypatch):
    from launcher.shortcuts import versioned_icon
    from launcher.versioning import LAUNCHER_VERSION

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    dest = versioned_icon(persist=True)
    assert dest is not None
    assert dest.is_file()
    assert dest.name == f"icon-{LAUNCHER_VERSION}.ico"
    assert dest.stat().st_size > 1000


def test_icon_location_prefers_versioned_file(tmp_path, monkeypatch):
    from launcher.shortcuts import _icon_location

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("launcher.shortcuts.is_frozen", lambda: True)
    loc = _icon_location(tmp_path / "CursorLauncher.exe")
    assert loc.endswith(",0")
    assert "icon-" in loc
    assert "CursorLauncher.exe,0" not in loc


def test_icon_assets_exist():
    ico = ROOT / "assets" / "icon.ico"
    png = ROOT / "assets" / "icon.png"
    web = ROOT / "web" / "icon.png"
    assert ico.is_file() and ico.stat().st_size > 1000
    assert png.is_file() and png.stat().st_size > 1000
    assert web.is_file() and web.stat().st_size > 200


def test_render_icon_rgba():
    import importlib.util
    import struct

    spec = importlib.util.spec_from_file_location("make_icon", ROOT / "scripts" / "make_icon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    img = mod.render_icon(64)
    assert img.mode == "RGBA"
    assert img.size == (64, 64)
    small = mod.render_icon(16)
    assert small.size == (16, 16)
    # 16px 必须带播放键，不能只剩一根竖条（资源管理器列表视图用这一档）
    px = small.getpixel((10, 8))
    assert px[3] > 200
    assert px[0] + px[1] + px[2] > 400
    data = (ROOT / "assets" / "icon.ico").read_bytes()
    _reserved, kind, count = struct.unpack_from("<HHH", data)
    assert kind == 1
    assert count >= 4
