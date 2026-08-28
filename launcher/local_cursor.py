"""读写本机 Cursor 登录态与机器码。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid

_KEYS = {
    "token": "cursorAuth/accessToken",
    "email": "cursorAuth/cachedEmail",
    "membership": "cursorAuth/stripeMembershipType",
}


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


def read_local_account() -> dict | None:
    path = state_db_path()
    if not os.path.isfile(path):
        return None
    uri = "file:{}?mode=ro&immutable=1".format(path.replace("\\", "/"))
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except Exception:
        return None
    try:
        out = {}
        for field, key in _KEYS.items():
            row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
            out[field] = row[0] if row else None
    finally:
        conn.close()
    if not out.get("token"):
        return None
    return out


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
