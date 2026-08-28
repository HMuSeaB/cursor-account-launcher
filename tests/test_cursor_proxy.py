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
    args = proxy_chromium_args(cfg)
    assert args[0] == "--proxy-server=http://127.0.0.1:7890"
    assert "--disable-quic" in args
    assert "--disable-features=Http3" in args
    assert proxy_env(ProxyConfig(enabled=False)) == {}
    assert proxy_chromium_args(ProxyConfig(enabled=False)) == []


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
