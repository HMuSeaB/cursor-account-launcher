"""读写本机 Cursor 登录态与机器码。"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
import uuid

from .token_utils import parse_token

_KEYS = {
    "token": "cursorAuth/accessToken",
    "email": "cursorAuth/cachedEmail",
    "membership": "cursorAuth/stripeMembershipType",
    "refresh": "cursorAuth/refreshToken",
}

WORKOS_SESSION_DB_KEYS = (
    "cursorAuth/workosCursorSessionToken",
    "cursorAuth/workOsCursorSessionToken",
    "cursorAuth/cachedWorkosSessionToken",
    "cursorAuth/webSessionToken",
)

USER_ID_KEYS = (
    "cursorAuth/cachedUserId",
    "cursorAuth/userId",
    "cursorAuth/openIdUserId",
    "cursorAuth/authId",
)


def cursor_root() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "Cursor")


def state_db_path() -> str:
    return os.path.join(cursor_root(), "User", "globalStorage", "state.vscdb")


def settings_json_path() -> str:
    return os.path.join(cursor_root(), "User", "settings.json")


def storage_json_path() -> str:
    return os.path.join(cursor_root(), "User", "globalStorage", "storage.json")


def machineid_path() -> str:
    return os.path.join(cursor_root(), "machineid")


def _decode_jwt_payload(jwt: str) -> dict:
    try:
        segment = jwt.split(".")[1]
        segment = segment.replace("-", "+").replace("_", "/")
        segment += "=" * (-len(segment) % 4)
        return json.loads(base64.b64decode(segment).decode("utf-8", "replace"))
    except Exception:
        return {}


def _normalize_session_token(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = re.sub(r"^WorkosCursorSessionToken=", "", text, flags=re.I).strip()
    text = text.replace("%3A%3A", "::").replace("%3a%3a", "::")
    if "WorkosCursorSessionToken=" in text:
        match = re.search(r"WorkosCursorSessionToken=([^;\s]+)", text, re.I)
        if match:
            text = match.group(1).strip().replace("%3A%3A", "::")
    if "::" not in text:
        return None
    parts = text.split("::", 1)
    if len(parts) != 2 or len(parts[1]) < 40:
        return None
    return f"{parts[0].strip()}::{parts[1].strip()}"


def _read_db_values(conn: sqlite3.Connection) -> dict[str, str]:
    out: dict[str, str] = {}
    for field, key in _KEYS.items():
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        if row and row[0] is not None:
            out[field] = str(row[0]).strip()
    for key in WORKOS_SESSION_DB_KEYS:
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        if row and row[0] is not None:
            out[f"ws:{key}"] = str(row[0]).strip()
    for key in USER_ID_KEYS:
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        if row and row[0] is not None:
            out[f"uid:{key}"] = str(row[0]).strip()
    return out


def _compose_ws_token(access_token: str, values: dict[str, str]) -> str | None:
    user_id = None
    claims = _decode_jwt_payload(access_token)
    sub = str(claims.get("sub") or "")
    if sub:
        user_id = sub.split("|")[-1].strip()
        if user_id.startswith("auth0|"):
            user_id = user_id[6:]
    if not user_id or not user_id.startswith("user_"):
        for key, val in values.items():
            if key.startswith("uid:") and val and "@" not in val and val.startswith("user_"):
                user_id = val
                break
    if user_id and access_token:
        composed = f"{user_id}::{access_token}"
        if _normalize_session_token(composed):
            return composed
    return None


def _find_ws_token_in_db(conn: sqlite3.Connection) -> str | None:
    for key in WORKOS_SESSION_DB_KEYS:
        row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
        if row and row[0]:
            token = _normalize_session_token(str(row[0]))
            if token:
                return token
    try:
        rows = conn.execute(
            "SELECT value FROM ItemTable WHERE typeof(value)='text' "
            "AND instr(lower(value), 'workoscursorsessiontoken=') > 0 "
            "AND key NOT LIKE 'terminal.%' AND lower(key) NOT LIKE '%workbench.%' LIMIT 8"
        ).fetchall()
        for row in rows:
            token = _normalize_session_token(str(row[0]))
            if token:
                return token
    except Exception:
        pass
    return None


def read_local_account() -> dict | None:
    path = state_db_path()
    if not os.path.isfile(path):
        return None
    uri = "file:{}?mode=ro".format(path.replace("\\", "/"))
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=8)
        conn.execute("PRAGMA busy_timeout=8000")
    except Exception:
        try:
            conn = sqlite3.connect(path, timeout=8)
            conn.execute("PRAGMA busy_timeout=8000")
        except Exception:
            return None
    try:
        values = _read_db_values(conn)
        access = values.get("token")
        if not access:
            return None

        ws_token = _find_ws_token_in_db(conn) or _compose_ws_token(access, values)
        email = values.get("email") or ""
        return {
            "token": ws_token or access,
            "accessToken": access,
            "wsToken": ws_token,
            "hasWsToken": bool(ws_token),
            "email": email,
            "membership": values.get("membership"),
            "refreshToken": values.get("refresh"),
        }
    finally:
        conn.close()


def write_local_account(access_token: str, email: str, refresh_token: str | None = None) -> None:
    path = state_db_path()
    if not os.path.isfile(path):
        raise RuntimeError("未找到本机 Cursor state.vscdb")
    conn = sqlite3.connect(path, timeout=8)
    try:
        cur = conn.cursor()

        def put(key: str, value: str) -> None:
            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (key, value),
            )

        put("cursorAuth/accessToken", access_token)
        put("cursorAuth/cachedEmail", email or "")
        put("cursor.accessToken", access_token)
        put("cursor.email", email or "")
        if refresh_token:
            put("cursorAuth/refreshToken", refresh_token)
        else:
            cur.execute("DELETE FROM ItemTable WHERE key=?", ("cursorAuth/refreshToken",))
        conn.commit()
    finally:
        conn.close()


def _rand_hex64() -> str:
    return os.urandom(32).hex()


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def reset_machine_ids() -> dict:
    service_id = str(uuid.uuid4())
    ids = {
        "telemetry.machineId": _rand_hex64(),
        "telemetry.macMachineId": _rand_hex64(),
        "telemetry.devDeviceId": str(uuid.uuid4()),
        "telemetry.sqmId": "{" + str(uuid.uuid4()).upper() + "}",
    }
    sj = storage_json_path()
    try:
        data = json.load(open(sj, "r", encoding="utf-8")) if os.path.isfile(sj) else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(ids)
    _atomic_write(sj, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    db = state_db_path()
    if os.path.isfile(db):
        conn = sqlite3.connect(db, timeout=8)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                ("storage.serviceMachineId", service_id),
            )
            conn.commit()
        finally:
            conn.close()
    try:
        _atomic_write(machineid_path(), service_id.encode("utf-8"))
    except Exception:
        pass
    return {"serviceMachineId": service_id}
