"""cursor_sessions 解析回归。"""

from launcher.cursor_sessions import _normalize_session


def test_normalize_session_uses_session_id_field():
    raw = {
        "sessionId": "abc123session",
        "type": "SESSION_TYPE_WEB",
        "createdAt": "2026-08-03T04:06:25.000Z",
    }
    item = _normalize_session(raw, None)
    assert item is not None
    assert item["id"] == "abc123session"
    assert item["sessionType"] == "SESSION_TYPE_WEB"
    assert item["typeLabel"] == "Web"


def test_normalize_session_marks_current_by_id():
    raw = {
        "sessionId": "current-one",
        "type": "SESSION_TYPE_CLIENT",
        "createdAt": "2026-08-03T04:06:25.000Z",
    }
    item = _normalize_session(raw, "current-one")
    assert item is not None
    assert item["isCurrent"] is True
    assert item["typeLabel"] == "Desktop App"
