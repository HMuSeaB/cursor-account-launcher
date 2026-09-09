"""bot_gateway 骨架单测。"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from bot_gateway.config import (
    GatewayConfigError,
    load_upstream,
    parse_upstream,
    redacted_summary,
)
from bot_gateway.server import STREAM_PATH, GatewayState, make_server
from bot_gateway.upstream import _filter_request_headers


def test_parse_upstream_ok():
    cfg = parse_upstream(
        {
            "version": 1,
            "baseUrl": "https://box.example/gw",
            "token": "tok-abc",
            "relayPath": STREAM_PATH,
            "headers": {"x-anyrun-network-token": "n"},
            "accountFingerprint": "deadbeef",
            "refresh": {"accessToken": "secret", "backendUrl": "https://api.example"},
        },
        source_path="mem",
    )
    assert cfg.base_url == "https://box.example/gw"
    assert cfg.token == "tok-abc"
    assert "x-anyrun-network-token" in cfg.headers
    assert cfg.stream_url.endswith(STREAM_PATH)
    summary = redacted_summary(cfg)
    assert summary["configured"] is True
    assert "token" not in summary
    assert "secret" not in json.dumps(summary)
    assert summary["hasRefresh"] is True


def test_parse_upstream_rejects_http_base():
    with pytest.raises(GatewayConfigError):
        parse_upstream({"version": 1, "baseUrl": "http://insecure", "token": "x"})


def test_load_upstream_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "missing.json"
    monkeypatch.setenv("BOT_GATEWAY_UPSTREAM", str(path))
    assert load_upstream() is None


def test_load_upstream_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "upstream.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "baseUrl": "https://box.example",
                "token": "t",
                "relayPath": STREAM_PATH,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_GATEWAY_UPSTREAM", str(path))
    cfg = load_upstream()
    assert cfg is not None
    assert cfg.token == "t"


def test_filter_strips_hop_by_hop():
    out = _filter_request_headers(
        {"Host": "127.0.0.1", "Authorization": "Bearer x", "Content-Length": "3"}
    )
    assert "Host" not in out
    assert "Content-Length" not in out
    assert out["Authorization"] == "Bearer x"


def test_health_and_stream_without_upstream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("BOT_GATEWAY_UPSTREAM", str(tmp_path / "none.json"))
    # force state reload via make_server
    httpd = make_server("127.0.0.1", 0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert payload["ok"] is True
        assert payload["ready"] is False
        assert payload["streamPath"] == STREAM_PATH

        conn.request("POST", STREAM_PATH, body=b"{}", headers={"Content-Type": "application/json"})
        resp2 = conn.getresponse()
        body2 = json.loads(resp2.read().decode("utf-8"))
        assert resp2.status == 503
        assert body2["ok"] is False
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_gateway_state_reload_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("BOT_GATEWAY_UPSTREAM", str(bad))
    state = GatewayState()
    assert state.upstream is None
    assert state.load_error
    health = state.health()
    assert health["ready"] is False


def test_parse_ensure_sandbox_fields():
    from bot_gateway.provision import _pb_tag, _pb_varint, parse_ensure_sandbox

    def pb_str(field: int, text: str) -> bytes:
        raw = text.encode("utf-8")
        return _pb_tag(field, 2) + _pb_varint(len(raw)) + raw

    def pb_uint(field: int, value: int) -> bytes:
        return _pb_tag(field, 0) + _pb_varint(value)

    body = (
        pb_str(10, "https://box.example/gw")
        + pb_str(11, "short-ticket")
        + pb_str(4, "net-tok")
        + pb_uint(13, 3)
    )
    parsed = parse_ensure_sandbox(body)
    assert parsed["baseUrl"] == "https://box.example/gw"
    assert parsed["token"] == "short-ticket"
    assert parsed["networkToken"] == "net-tok"
    assert parsed["runState"] == 3


def test_write_upstream_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot_gateway.config import load_upstream, write_upstream_dict

    path = tmp_path / "upstream.json"
    monkeypatch.setenv("BOT_GATEWAY_UPSTREAM", str(path))
    write_upstream_dict(
        {
            "version": 1,
            "baseUrl": "https://box.example",
            "token": "secret-ticket",
            "relayPath": STREAM_PATH,
        },
        path=path,
    )
    cfg = load_upstream()
    assert cfg is not None
    assert cfg.token == "secret-ticket"
    dumped = path.read_text(encoding="utf-8")
    assert "secret-ticket" in dumped  # file holds the ticket
    summary = redacted_summary(cfg)
    assert "secret-ticket" not in json.dumps(summary)


def test_gateway_mode_enable_requires_upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from launcher import bot_gateway_ctl as ctl

    monkeypatch.setattr(
        ctl,
        "status",
        lambda: {"ok": True, "conflictDirect": False, "upstream": {"configured": False}},
    )
    res = ctl.enable_redirect()
    assert res["ok"] is False
    assert "Box 票" in res["error"]


def test_write_mode_is_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from launcher import bot_gateway_ctl as ctl

    monkeypatch.setattr(ctl, "default_config_dir", lambda: tmp_path)
    ctl.write_mode(True, listen="http://127.0.0.1:8765")
    assert ctl.is_gateway_mode() is True
    ctl.write_mode(False)
    assert ctl.is_gateway_mode() is False


def test_connect_stream_has_end_frame():
    from bot_gateway.box_mount import connect_stream_has_end_frame

    # empty data frame + end frame (flag 0x02), length 0
    body = b"\x00\x00\x00\x00\x00" + b"\x02\x00\x00\x00\x00"
    assert connect_stream_has_end_frame(body) is True
    assert connect_stream_has_end_frame(b"\x00\x00\x00\x00\x00") is False
    assert connect_stream_has_end_frame(b"\x00\x00\x00\x00\x01") is False  # truncated


def test_find_agent_id_in_record():
    from bot_gateway.box_mount import find_agent_id_in_record

    assert find_agent_id_in_record({"agentId": "a-1", "id": "other"}) == "a-1"
    assert find_agent_id_in_record({"nested": {"id": "fallback-id"}}) == "fallback-id"
    assert find_agent_id_in_record({}) == ""


def test_cursor_inject_roundtrip():
    from bot_gateway.cursor_inject import (
        MARKER,
        ORIGINALS,
        InjectError,
        apply_to_content,
        foreign_markers_in,
        remove_from_content,
    )

    host = (
        "applyAuthorization(e,t){return a(this,void 0,void 0,function*(){"
        "var n,r,o,s,i,a,l,c,u,d,m,p;if(t.overrideAuthToken){doStuff()}"
    )
    local = (
        "applyAuthorization(e,t){return a(this,void 0,void 0,function*(){"
        "var n,r,s,o,i,a,l,u,m,c,d,p;if(t.overrideAuthToken){doStuff()}"
    )
    content = "//hdr\n" + host + "\n" + local + "\n//end\n"
    patched, n = apply_to_content(content)
    assert n == 2
    assert MARKER in patched
    assert "CursorLauncher" in patched
    assert "listen.json" in patched
    # idempotent
    again, n2 = apply_to_content(patched)
    assert n2 == 0
    assert again == patched
    restored, stripped = remove_from_content(patched)
    assert stripped == 2
    assert MARKER not in restored
    assert ORIGINALS[0] in restored
    assert ORIGINALS[1] in restored

    with pytest.raises(InjectError):
        apply_to_content("x/*SAND_DIRECT_INFERENCE_STREAM_V1*/" + ORIGINALS[0] + "y")
    assert foreign_markers_in("/*SAND_GROK_BOX_RELAY_AUTH_V1*/") == [
        "/*SAND_GROK_BOX_RELAY_AUTH_V1*/"
    ]


def test_write_listen_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from bot_gateway import cursor_inject as inj

    path = tmp_path / "listen.json"
    monkeypatch.setenv("BOT_GATEWAY_LISTEN_CONFIG", str(path))
    out = inj.write_listen_config(host="127.0.0.1", port=8765)
    assert out == path
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["baseUrl"] == "http://127.0.0.1:8765"
    assert data["relayPath"].startswith("/sand-stream-relay/")
