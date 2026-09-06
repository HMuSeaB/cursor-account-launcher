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


def test_peek_local_identity_drops_email_when_cached_and_cursor_disagree(tmp_path, monkeypatch):
    jwt = fake_jwt("auth0|user_freeacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt,
            "cursorAuth/cachedUserId": "user_freeacct",
            "cursorAuth/cachedEmail": "pro@x.com",
            "cursor.email": "free@x.com",
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    ident = peek_local_identity()
    assert ident["userId"] == "user_freeacct"
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


def test_write_local_account_drops_other_user_refresh(tmp_path, monkeypatch):
    from launcher.local_cursor import write_local_account

    jwt_old = fake_jwt("auth0|user_oldacct")
    jwt_new = fake_jwt("auth0|user_newacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt_old,
            "cursorAuth/cachedUserId": "user_oldacct",
            "cursorAuth/cachedEmail": "old@x.com",
            "cursorAuth/refreshToken": jwt_old,
            "cursorAuth/workosCursorSessionToken": f"user_oldacct::{jwt_old}",
            "cursorAuth/workOsCursorSessionToken": f"user_oldacct::{jwt_old}",
            "cursorAuth/cachedWorkosSessionToken": f"user_oldacct::{jwt_old}",
            "cursorAuth/webSessionToken": f"user_oldacct::{jwt_old}",
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    write_local_account(
        jwt_new,
        "new@x.com",
        refresh_token=None,
        membership="pro",
        keep_refresh_if_missing=True,
    )
    conn = sqlite3.connect(db)
    try:
        rows = dict(conn.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        conn.close()
    assert rows["cursorAuth/accessToken"] == jwt_new
    assert rows["cursorAuth/cachedEmail"] == "new@x.com"
    assert rows["cursorAuth/cachedUserId"] == "user_newacct"
    assert rows["cursorAuth/stripeMembershipType"] == "pro"
    assert rows["cursorAuth/refreshToken"] == jwt_new
    expected_ws = f"user_newacct::{jwt_new}"
    assert rows["cursorAuth/workosCursorSessionToken"] == expected_ws
    assert rows["cursorAuth/workOsCursorSessionToken"] == expected_ws
    assert rows["cursorAuth/cachedWorkosSessionToken"] == expected_ws
    assert rows["cursorAuth/webSessionToken"] == expected_ws


def test_write_local_account_keeps_same_user_refresh(tmp_path, monkeypatch):
    from launcher.local_cursor import write_local_account

    jwt = fake_jwt("auth0|user_same")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt,
            "cursorAuth/cachedUserId": "user_same",
            "cursorAuth/refreshToken": jwt,
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    write_local_account(jwt, "same@x.com", refresh_token=None, keep_refresh_if_missing=True)
    conn = sqlite3.connect(db)
    try:
        rows = dict(conn.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        conn.close()
    assert rows["cursorAuth/refreshToken"] == jwt


def test_write_local_account_drops_stale_refresh_when_access_already_matches(tmp_path, monkeypatch):
    from launcher.local_cursor import write_local_account

    jwt_old = fake_jwt("auth0|user_oldacct")
    jwt_new = fake_jwt("auth0|user_newacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(
        db,
        {
            "cursorAuth/accessToken": jwt_new,
            "cursorAuth/cachedUserId": "user_newacct",
            "cursorAuth/refreshToken": jwt_old,
        },
    )
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    write_local_account(jwt_new, "new@x.com", refresh_token=None, keep_refresh_if_missing=True)
    conn = sqlite3.connect(db)
    try:
        rows = dict(conn.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        conn.close()
    assert rows["cursorAuth/accessToken"] == jwt_new
    assert rows["cursorAuth/refreshToken"] == jwt_new


def test_write_local_account_rejects_foreign_refresh_token(tmp_path, monkeypatch):
    from launcher.local_cursor import write_local_account

    jwt_old = fake_jwt("auth0|user_oldacct")
    jwt_new = fake_jwt("auth0|user_newacct")
    db = tmp_path / "state.vscdb"
    _write_state_db(db, {"cursorAuth/accessToken": jwt_old, "cursorAuth/refreshToken": jwt_old})
    monkeypatch.setattr("launcher.local_cursor.state_db_path", lambda: str(db))

    write_local_account(
        jwt_new,
        "new@x.com",
        refresh_token=jwt_old,
        keep_refresh_if_missing=True,
    )
    conn = sqlite3.connect(db)
    try:
        rows = dict(conn.execute("SELECT key, value FROM ItemTable").fetchall())
    finally:
        conn.close()
    assert rows["cursorAuth/refreshToken"] == jwt_new
