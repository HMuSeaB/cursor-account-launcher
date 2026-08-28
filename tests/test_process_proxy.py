"""process_proxy 单元测试。"""

from pathlib import Path

from launcher.process_proxy import (
    MARKER,
    build_hook_config,
    deploy_process_proxy,
    remove_process_proxy,
    status,
)


def test_build_hook_config_socks5_blocks_udp():
    cfg = build_hook_config(host="127.0.0.1", port=7891, proxy_type="socks5")
    assert cfg["_managed_by"] == MARKER
    assert cfg["proxy"] == {"host": "127.0.0.1", "port": 7891, "type": "socks5"}
    assert cfg["proxy_rules"]["udp_mode"] == "block"
    assert cfg["child_injection_mode"] == "inherit"
    assert "Cursor.exe" in cfg["target_processes"]


def test_build_hook_config_http_alias():
    cfg = build_hook_config(host="10.0.0.1", port=7890, proxy_type="HTTP")
    assert cfg["proxy"]["type"] == "http"
    assert cfg["proxy"]["port"] == 7890


def test_deploy_and_remove_roundtrip(tmp_path, monkeypatch):
    dll_src = tmp_path / "src" / "version.dll"
    dll_src.parent.mkdir()
    dll_src.write_bytes(b"fake-dll")
    install = tmp_path / "cursor"
    install.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()

    monkeypatch.setattr(
        "launcher.process_proxy._state_dir",
        lambda: cache,
    )
    monkeypatch.setattr(
        "launcher.process_proxy.DEFAULT_DLL_CANDIDATES",
        (dll_src,),
    )
    monkeypatch.setattr(
        "launcher.process_proxy.resolve_dll_source",
        lambda explicit=None: Path(explicit) if explicit else dll_src,
    )

    res = deploy_process_proxy(install, host="127.0.0.1", port=7891, proxy_type="socks5")
    assert res.get("ok") is True, res
    assert (install / "version.dll").is_file()
    assert (install / "config.json").is_file()
    st = status(install)
    assert st["installed"] is True
    assert st["managed"] is True

    gone = remove_process_proxy(install)
    assert gone["ok"] is True
    assert gone["removed"] is True
    assert not (install / "version.dll").exists()
    assert not (install / "config.json").exists()


def test_remove_skips_unmanaged_dll(tmp_path):
    install = tmp_path / "cursor"
    install.mkdir()
    (install / "version.dll").write_bytes(b"other")
    (install / "config.json").write_text('{"_managed_by":"SomeoneElse"}\n', encoding="utf-8")
    res = remove_process_proxy(install)
    assert res["ok"] is False
    assert (install / "version.dll").is_file()
