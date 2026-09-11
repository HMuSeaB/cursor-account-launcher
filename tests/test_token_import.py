"""号商/聊天记录式粘贴：自动识别 token、拼回折行、带上邮箱。"""

from __future__ import annotations

import base64
import json

from launcher.account_store import AccountStore
from launcher.accounts import parse_account_dump, tokens_from_text


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fake_jwt(sub: str, extra: str = "x" * 80) -> str:
    payload = {"sub": sub, "pad": extra}
    token = f"{_b64url({'alg': 'HS256', 'typ': 'JWT'})}.{_b64url(payload)}.fakesigxxxxxx"
    return token


def _wrap(token: str, at: int = 28) -> str:
    return token[:at] + "\n" + token[at:]


def test_parse_dump_pairs_email_with_ws_token():
    jwt_a = fake_jwt("auth0|user_aaa111")
    jwt_b = fake_jwt("auth0|user_bbb222")
    dump = (
        "第21个：ThomasMcguire52974@hotmail.com\n"
        f"user_aaa111::{jwt_a}\n"
        "重置时间：2026-09-12 20:46\n"
        "第22个：linda.mccoy388485@hotmail.com\n"
        f"user_bbb222::{jwt_b}\n"
        "重置时间：2026-09-12 20:47\n"
    )
    rows = parse_account_dump(dump)
    assert [(t, email) for _, t, email in rows] == [
        (f"user_aaa111::{jwt_a}", "ThomasMcguire52974@hotmail.com"),
        (f"user_bbb222::{jwt_b}", "linda.mccoy388485@hotmail.com"),
    ]


def test_parse_dump_stitches_chat_wrapped_jwt():
    jwt = fake_jwt("auth0|user_wrap99")
    ws = f"user_wrap99::{jwt}"
    dump = "第1个：wrap@example.com\n" + _wrap(ws, 40) + "\n重置时间：2026-09-12 20:54\n"
    rows = parse_account_dump(dump)
    assert len(rows) == 1
    prio, token, email = rows[0]
    assert prio == 5
    assert token == ws
    assert email == "wrap@example.com"


def test_tokens_from_text_without_stitch_does_not_keep_full_wrapped_ws():
    jwt = fake_jwt("auth0|user_wrap99")
    ws = f"user_wrap99::{jwt}"
    wrapped = _wrap(ws, 40)
    tokens = [t for _, t in tokens_from_text(wrapped)]
    assert ws not in tokens


def test_email_does_not_leak_onto_next_account():
    jwt_a = fake_jwt("auth0|user_one")
    jwt_b = fake_jwt("auth0|user_two")
    dump = f"a@x.com\nuser_one::{jwt_a}\nuser_two::{jwt_b}\n"
    rows = parse_account_dump(dump)
    by_token = {t: email for _, t, email in rows}
    assert by_token[f"user_one::{jwt_a}"] == "a@x.com"
    assert by_token[f"user_two::{jwt_b}"] == ""


def test_add_text_stores_pasted_email_as_label(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.accounts._app_dir", lambda: str(tmp_path))
    jwt = fake_jwt("auth0|user_mailme")
    dump = f"第3个：mailme@outlook.com\nuser_mailme::{jwt}\n"
    store = AccountStore()
    added = store.add_text(dump)
    assert added and added[0]["id"] == "user_mailme"
    item = store.get("user_mailme")
    assert item["email"] == "mailme@outlook.com"
    assert item["label"] == "mailme@outlook.com"
    assert item["token"] == f"user_mailme::{jwt}"


def test_consecutive_complete_tokens_are_not_glued():
    jwt_a = fake_jwt("auth0|user_one")
    jwt_b = fake_jwt("auth0|user_two")
    dump = f"user_one::{jwt_a}\nuser_two::{jwt_b}\n"
    rows = parse_account_dump(dump)
    assert [t for _, t, _ in rows] == [f"user_one::{jwt_a}", f"user_two::{jwt_b}"]


def test_add_text_keeps_ws_prefix_when_dump_also_contains_inner_jwt(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.accounts._app_dir", lambda: str(tmp_path))
    jwt = fake_jwt("auth0|user_keepws")
    ws = f"user_keepws::{jwt}"
    store = AccountStore()
    added = store.add_text(f"keep@x.com\n{ws}\n")
    assert added[0]["id"] == "user_keepws"
    assert store.get("user_keepws")["token"] == ws
    assert store.list()[0]["hasWsToken"] is True


class _Resp:
    def __init__(self, status: int, body="", json_data=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = body
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


def _patch_get(monkeypatch, fn):
    from launcher import cursor_usage as cu

    monkeypatch.setattr(cu.requests, "get", fn)
    return cu


def test_refresh_error_401_says_token_invalid_with_status(monkeypatch):
    cu = _patch_get(monkeypatch, lambda *a, **k: _Resp(401, "unauthorized"))
    out = cu.refresh_account_usage("user_x::" + fake_jwt("auth0|user_x"), extras=False, resolve_email=False)
    assert out["ok"] is False
    assert "登录失效" in out["error"]
    assert "401" in out["error"]


def test_refresh_error_404_reports_status_code(monkeypatch):
    cu = _patch_get(monkeypatch, lambda *a, **k: _Resp(404, "not found"))
    out = cu.refresh_account_usage("user_x::" + fake_jwt("auth0|user_x"), extras=False, resolve_email=False)
    assert out["ok"] is False
    assert "404" in out["error"]


def test_refresh_error_timeout_is_not_an_exception(monkeypatch):
    import requests

    def boom(*_a, **_k):
        raise requests.exceptions.ReadTimeout("slow")

    cu = _patch_get(monkeypatch, boom)
    out = cu.refresh_account_usage("user_x::" + fake_jwt("auth0|user_x"), extras=False, resolve_email=False)
    assert out["ok"] is False
    assert "超时" in out["error"]


def test_refresh_error_connection_mentions_network(monkeypatch):
    import requests

    def boom(*_a, **_k):
        raise requests.exceptions.ConnectionError("refused")

    cu = _patch_get(monkeypatch, boom)
    out = cu.refresh_account_usage("user_x::" + fake_jwt("auth0|user_x"), extras=False, resolve_email=False)
    assert out["ok"] is False
    assert "无法连接" in out["error"]


def test_token_expiry_from_claims():
    from launcher.token_utils import token_expiry_ms

    assert token_expiry_ms({"exp": 1_800_000_000}) == 1_800_000_000_000
    assert token_expiry_ms({"exp": "1800000000"}) == 1_800_000_000_000
    assert token_expiry_ms({}) == 0
    assert token_expiry_ms({"exp": "abc"}) == 0


def test_quick_refresh_skips_sand_and_period(monkeypatch):
    from launcher import cursor_usage as cu

    monkeypatch.setattr(
        cu,
        "fetch_usage_summary",
        lambda *a, **k: {"email": "a@x.com", "individualUsage": {}},
    )

    def boom(*_a, **_k):
        raise AssertionError("extra endpoint should be skipped")

    monkeypatch.setattr(cu, "fetch_sand_usage", boom)
    monkeypatch.setattr(cu, "fetch_period_stats", boom)
    out = cu.refresh_account_usage("dummy", extras=False, resolve_email=False)
    assert out["ok"] is True
    assert out["email"] == "a@x.com"
