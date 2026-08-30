"""cursor_proxy 单元测试。"""

from pathlib import Path

from launcher.cursor_process import _with_extra_args, launch_args
from launcher.cursor_proxy import (
    ProxyConfig,
    _strip_json_comments,
    merge_argv_proxy,
    proxy_chromium_args,
    proxy_env,
)


def test_strip_comments_preserves_http_url():
    raw = '{\n  "http.proxy": "http://127.0.0.1:7890"\n}\n'
    cleaned = _strip_json_comments(raw)
    assert "http://127.0.0.1:7890" in cleaned


def test_merge_argv_sets_chromium_proxy_and_keeps_crash_id():
    cfg = ProxyConfig(enabled=True, proxy_type="http", host="127.0.0.1", port=7890)
    out = merge_argv_proxy({"crash-reporter-id": "abc", "locale": "zh-cn"}, cfg)
    assert out["crash-reporter-id"] == "abc"
    assert out["locale"] == "zh-cn"
    assert out["proxy-server"] == "http://127.0.0.1:7890"
    assert "localhost" in out["proxy-bypass-list"]


def test_merge_argv_socks_uses_socks5_not_socks5h():
    cfg = ProxyConfig(enabled=True, proxy_type="socks5", host="127.0.0.1", port=7891)
    out = merge_argv_proxy({}, cfg)
    assert out["proxy-server"] == "socks5://127.0.0.1:7891"


def test_merge_argv_disable_removes_proxy_keys():
    cfg = ProxyConfig(enabled=False)
    out = merge_argv_proxy({"proxy-server": "http://127.0.0.1:7890", "locale": "zh-cn"}, cfg)
    assert "proxy-server" not in out
    assert out["locale"] == "zh-cn"


def test_proxy_env_and_args_for_bridge_process():
    cfg = ProxyConfig(enabled=True, proxy_type="http", host="127.0.0.1", port=7890)
    env = proxy_env(cfg)
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["NO_PROXY"].startswith("localhost")
    assert "," in env["NO_PROXY"]
    args = proxy_chromium_args(cfg)
    assert args[0] == "--proxy-server=http://127.0.0.1:7890"
    assert "--disable-quic" in args
    assert "--disable-features=Http3" in args
    assert proxy_env(ProxyConfig(enabled=False)) == {}
    assert proxy_chromium_args(ProxyConfig(enabled=False)) == []


def test_settings_no_proxy_must_be_array_not_string(tmp_path, monkeypatch):
    from launcher import cursor_proxy as cp

    settings = tmp_path / "settings.json"
    settings.write_text("{\n  \"editor.fontSize\": 14\n}\n", encoding="utf-8")
    argv = tmp_path / "argv.json"
    argv.write_text('{\n\t"crash-reporter-id": "keep"\n}\n', encoding="utf-8")
    monkeypatch.setattr(cp, "settings_json_path", lambda: str(settings))
    monkeypatch.setattr(cp, "argv_json_path", lambda: argv)

    cfg = ProxyConfig(enabled=True, proxy_type="socks5", host="127.0.0.1", port=7891)
    res = cp.apply_proxy(cfg)
    assert res["ok"] is True
    data = __import__("json").loads(settings.read_text(encoding="utf-8"))
    assert isinstance(data["http.noProxy"], list)
    assert "localhost" in data["http.noProxy"]
    assert isinstance(data["http.noProxy"][0], str)


def test_normalize_repairs_string_no_proxy():
    from launcher.cursor_proxy import normalize_settings_no_proxy

    settings = {"http.noProxy": "localhost,127.0.0.1,::1"}
    assert normalize_settings_no_proxy(settings) is True
    assert settings["http.noProxy"] == ["localhost", "127.0.0.1", "::1"]


def test_from_dict_defaults_proxy_disabled():
    cfg = ProxyConfig.from_dict({})
    assert cfg.enabled is False


def test_snapshot_and_restore_proxy_files(tmp_path, monkeypatch):
    from launcher import cursor_proxy as cp

    settings = tmp_path / "settings.json"
    settings.write_text(
        '{\n  "editor.fontSize": 14,\n  "http.proxy": "http://old:1"\n}\n',
        encoding="utf-8",
    )
    argv = tmp_path / "argv.json"
    argv.write_text('{\n\t"crash-reporter-id": "keep",\n\t"locale": "zh-cn"\n}\n', encoding="utf-8")
    bak = tmp_path / "proxy-backups"
    bak.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cp, "settings_json_path", lambda: str(settings))
    monkeypatch.setattr(cp, "argv_json_path", lambda: argv)
    monkeypatch.setattr(cp, "_proxy_backup_dir", lambda: bak)

    cfg = ProxyConfig(enabled=True, proxy_type="socks5", host="127.0.0.1", port=7891)
    res = cp.apply_proxy(cfg)
    assert res["ok"] is True
    assert bak.joinpath("settings-proxy-keys.json").is_file()
    data = __import__("json").loads(settings.read_text(encoding="utf-8"))
    assert data["http.proxy"].startswith("socks5")
    assert isinstance(data["http.noProxy"], list)

    undone = cp.restore_proxy_files()
    assert undone["ok"] is True
    restored = __import__("json").loads(settings.read_text(encoding="utf-8"))
    assert restored.get("http.proxy") == "http://old:1"
    assert "http.noProxy" not in restored
    assert restored["editor.fontSize"] == 14
    argv_text = argv.read_text(encoding="utf-8")
    assert "crash-reporter-id" in argv_text
    assert "proxy-server" not in argv_text or "keep" in argv_text



def test_proxy_flags_insert_before_light_workspace():
    folder = str(Path("C:/tmp/light"))
    args = _with_extra_args(
        ["--classic", "--disable-gpu", folder],
        ("--proxy-server=http://127.0.0.1:7890",),
        light=True,
    )
    assert args[-1] == folder
    assert "--proxy-server=http://127.0.0.1:7890" in args
    assert launch_args(light=False) == ["--classic"]


def test_apply_argv_proxy_roundtrip(tmp_path):
    from launcher.cursor_proxy import apply_argv_proxy

    path = tmp_path / "argv.json"
    path.write_text('{\n\t"crash-reporter-id": "keep-me",\n\t"locale": "zh-cn"\n}\n', encoding="utf-8")
    cfg = ProxyConfig(enabled=True, host="127.0.0.1", port=7890)
    res = apply_argv_proxy(cfg, path)
    assert res["ok"] is True
    text = path.read_text(encoding="utf-8")
    assert "keep-me" in text
    assert "proxy-server" in text
    assert "127.0.0.1:7890" in text


def test_strip_bajie_urls_restores_official_hosts():
    from launcher.bajie_route import strip_bajie_urls

    src = (
        'Upt="https://127.0.0.1:43111/__bajie/api2.cursor.sh",'
        '$pt="https://127.0.0.1:43111/__bajie/agent.api5.cursor.sh"'
    )
    out, n = strip_bajie_urls(src)
    assert n == 2
    assert out == 'Upt="https://api2.cursor.sh",$pt="https://agent.api5.cursor.sh"'
    assert "43111" not in out


def test_detect_patch_finds_bajie(tmp_path):
    from launcher.bajie_route import BAJIE_PREFIX, detect_patch

    root = tmp_path / "cursor"
    wb = root / "resources" / "app" / "out" / "vs" / "workbench"
    wb.mkdir(parents=True)
    f = wb / "workbench.desktop.main.js"
    f.write_text(f'host="{BAJIE_PREFIX}api2.cursor.sh"', encoding="utf-8")
    st = detect_patch(root)
    assert st["ok"] is True
    assert st["patched"] is True
    assert st["hits"] == 1


def test_detect_patch_clean_workbench(tmp_path):
    from launcher.bajie_route import detect_patch

    root = tmp_path / "cursor"
    wb = root / "resources" / "app" / "out" / "vs" / "workbench"
    wb.mkdir(parents=True)
    f = wb / "workbench.desktop.main.js"
    f.write_text('host="https://api2.cursor.sh"', encoding="utf-8")
    st = detect_patch(root)
    assert st["patched"] is False
    assert st["hits"] == 0
