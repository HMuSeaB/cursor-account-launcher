"""本机探测：userId 信 JWT.sub，导入时保留 WS 前缀。"""

from __future__ import annotations

import base64
import json
import sqlite3

from launcher.accounts import JWT_RE, WS_RE, tokens_from_text
from launcher.account_store import AccountStore
from launcher.local_cursor import peek_local_identity, read_local_account


def _b64url(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fake_jwt(sub: str) -> str:
    token = f"{_b64url({'alg': 'HS256', 'typ': 'JWT'})}.{_b64url({'sub': sub})}.fakesigxxxxxx"
    assert JWT_RE.search(token)
    return token


def _write_state_db(path, rows: dict[str, str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany("INSERT INTO ItemTable (key, value) VALUES (?, ?)", list(rows.items()))
        conn.commit()
    finally:
        conn.close()


def test_peek_local_identity_uses_jwt_sub_not_stale_cached_user(tmp_path, monkeypatch):
    jwt = fake_jwt("auth0|user_newacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt,
            "cursorAuth/cachedUserId": "user_oldacct",
            "cursorAuth/cachedEmail": "old@x.com",
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    ident = peek_local_identity()
    assert ident["userId"] == "user_newacct"
    assert ident["email"] == ""


def test_tokens_from_text_does_not_drop_ws_prefix_for_wrapped_jwt():
    jwt = fake_jwt("auth0|user_abc123")
    ws = f"user_abc123::{jwt}"
    assert WS_RE.search(ws)

    tokens = [token for _, token in tokens_from_text(ws)]
    assert ws in tokens
    assert jwt not in tokens

    other = fake_jwt("auth0|user_other")
    mixed = tokens_from_text(f"{ws}\n{other}")
    mixed_tokens = [token for _, token in mixed]
    assert ws in mixed_tokens
    assert other in mixed_tokens
    assert jwt not in mixed_tokens


def test_add_text_keeps_ws_token_instead_of_inner_jwt(tmp_path, monkeypatch):
    monkeypatch.setattr("launcher.accounts._app_dir", lambda: str(tmp_path))
    jwt = fake_jwt("auth0|user_abc123")
    ws = f"user_abc123::{jwt}"

    store = AccountStore()
    added = store.add_text(ws)
    assert added and added[0]["id"] == "user_abc123"
    item = store.get("user_abc123")
    assert item is not None
    assert item["token"] == ws
    assert store.list()[0]["hasWsToken"] is True


def test_read_local_account_ignores_other_account_ws_token(tmp_path, monkeypatch):
    jwt_new = fake_jwt("auth0|user_newacct")
    jwt_old = fake_jwt("auth0|user_oldacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt_new,
            "cursorAuth/cachedUserId": "user_oldacct",
            "cursorAuth/workosCursorSessionToken": f"user_oldacct::{jwt_old}",
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    acct = read_local_account()
    assert acct is not None
    assert acct["accessToken"] == jwt_new
    assert acct["wsToken"] == f"user_newacct::{jwt_new}"
    assert acct["hasWsToken"] is True
