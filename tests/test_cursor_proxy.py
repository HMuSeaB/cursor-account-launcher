"""cursor_proxy 单元测试。"""

from launcher.cursor_proxy import _load_settings, _strip_json_comments


def test_strip_comments_preserves_http_url():
    raw = '{\n  "http.proxy": "http://127.0.0.1:7890"\n}\n'
    cleaned = _strip_json_comments(raw)
    assert "http://127.0.0.1:7890" in cleaned


def test_load_settings_reads_proxy_url():
    data = _load_settings()
    if not data:
        return
    proxy = data.get("http.proxy")
    if proxy:
        assert proxy.startswith("http")
