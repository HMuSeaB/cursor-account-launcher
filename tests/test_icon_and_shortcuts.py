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
    data = (ROOT / "assets" / "icon.ico").read_bytes()
    _reserved, kind, count = struct.unpack_from("<HHH", data)
    assert kind == 1
    assert count >= 4
