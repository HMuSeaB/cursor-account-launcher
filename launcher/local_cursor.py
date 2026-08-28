"""读写本机 Cursor 登录态与机器码（对齐 FlyCursor / BajieAsk 指纹字段）。"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
import time
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

FINGERPRINT_STORAGE_KEYS = (
    "telemetry.machineId",
    "telemetry.macMachineId",
    "telemetry.devDeviceId",
    "telemetry.sqmId",
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


def _open_db(readonly: bool = False) -> sqlite3.Connection:
    path = state_db_path()
    if not os.path.isfile(path):
        raise RuntimeError("未找到本机 Cursor state.vscdb")
    if readonly:
        uri = "file:{}?mode=ro".format(path.replace("\\", "/"))
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=8)
        except Exception:
            conn = sqlite3.connect(path, timeout=8)
    else:
        conn = sqlite3.connect(path, timeout=15)
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def wait_state_db_ready(timeout_seconds: float = 12.0) -> None:
    """Cursor 退出后等 state.vscdb 可写，避免半关着写库导致切号失败。"""
    path = state_db_path()
    if not os.path.isfile(path):
        raise RuntimeError("未找到本机 Cursor state.vscdb")
    deadline = time.monotonic() + timeout_seconds
    last_err = None
    while time.monotonic() < deadline:
        try:
            conn = sqlite3.connect(path, timeout=2)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("SELECT 1 FROM ItemTable LIMIT 1")
                conn.commit()
            finally:
                conn.close()
            return
        except Exception as exc:
            last_err = exc
            time.sleep(0.25)
    raise RuntimeError(f"state.vscdb 仍被占用，请完全退出 Cursor 后再试（{last_err}）")


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
    try:
        conn = _open_db(readonly=True)
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
            "fingerprint": read_fingerprint(),
        }
    finally:
        conn.close()


def peek_local_identity() -> dict:
    """只读本机正在用的邮箱 / userId，不导入账号、不碰 token。"""
    out = {"email": "", "userId": ""}
    try:
        conn = _open_db(readonly=True)
    except Exception:
        return out
    try:
        for field, key in (
            ("email", "cursorAuth/cachedEmail"),
            ("userId", "cursorAuth/cachedUserId"),
        ):
            row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
            if row and row[0]:
                value = str(row[0]).strip()
                if field == "userId" and value.startswith("auth0|"):
                    value = value.split("|", 1)[-1]
                out[field] = value
        return out
    except Exception:
        return out
    finally:
        conn.close()


def write_local_account(
    token: str,
    email: str,
    refresh_token: str | None = None,
    membership: str | None = None,
    *,
    keep_refresh_if_missing: bool = True,
) -> dict:
    """写入本机登录态。token 可为 JWT 或 user_xxx::jwt。

    对齐 FlyCursor 会写的关键键；切号时若删掉 refreshToken，Cursor 常会重新鉴权并多出 Desktop。
    """
    wait_state_db_ready()
    user_id, jwt, claims = parse_token(token)
    email = (email or claims.get("email") or "").strip()
    membership = (membership or "").strip() or None
    ws = _normalize_session_token(token)
    if not ws and user_id:
        ws = f"{user_id}::{jwt}"

    conn = _open_db(readonly=False)
    try:
        cur = conn.cursor()

        def put(key: str, value: str) -> None:
            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (key, value),
            )

        put("cursorAuth/accessToken", jwt)
        put("cursorAuth/cachedEmail", email or "")
        put("cursorAuth/email", email or "")
        put("cursor.accessToken", jwt)
        put("cursor.email", email or "")
        put("cursorAuth/cachedUserId", user_id)
        put("cursorAuth/userId", user_id)
        put("cursorAuth/authId", f"auth0|{user_id}" if not user_id.startswith("auth0|") else user_id)
        put("cursorAuth/isLoggedIn", "true")
        put("cursorAuth/isAuthenticated", "true")
        put("cursorAuth/isAuthorized", "true")
        if membership:
            put("cursorAuth/stripeMembershipType", membership)

        if refresh_token:
            put("cursorAuth/refreshToken", refresh_token)
        elif not keep_refresh_if_missing:
            cur.execute("DELETE FROM ItemTable WHERE key=?", ("cursorAuth/refreshToken",))
        # keep_refresh_if_missing=True：保留库里旧 refresh（同账号续登更稳）

        if ws:
            put("cursorAuth/workosCursorSessionToken", ws)
            put("cursorAuth/cachedWorkosSessionToken", ws)

        conn.commit()
    finally:
        conn.close()

    # 回读校验
    local = read_local_account()
    if not local or not local.get("accessToken"):
        raise RuntimeError("写入后无法读回 accessToken，切号可能失败")
    if local["accessToken"] != jwt:
        raise RuntimeError("写入校验失败：accessToken 未生效")
    return {"ok": True, "userId": user_id, "email": email, "hasWsToken": bool(ws)}


def _rand_hex64() -> str:
    return os.urandom(32).hex()


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def read_fingerprint() -> dict:
    """读取本机 6 项设备指纹（FlyCursor / BajieAsk 同款字段）。"""
    out = {
        "machineId": None,
        "telemetryMachineId": None,
        "macMachineId": None,
        "devDeviceId": None,
        "sqmId": None,
        "serviceMachineId": None,
        "machineGuid": None,
    }
    try:
        if os.path.isfile(machineid_path()):
            mid = open(machineid_path(), "r", encoding="utf-8").read().strip()
            if mid:
                out["machineId"] = mid
                out["serviceMachineId"] = mid
    except Exception:
        pass
    try:
        sj = storage_json_path()
        if os.path.isfile(sj):
            data = json.load(open(sj, "r", encoding="utf-8"))
            if isinstance(data, dict):
                out["telemetryMachineId"] = data.get("telemetry.machineId") or None
                out["macMachineId"] = data.get("telemetry.macMachineId") or None
                out["devDeviceId"] = data.get("telemetry.devDeviceId") or None
                out["sqmId"] = data.get("telemetry.sqmId") or None
    except Exception:
        pass
    try:
        conn = _open_db(readonly=True)
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key=?",
                ("storage.serviceMachineId",),
            ).fetchone()
            if row and row[0]:
                out["serviceMachineId"] = str(row[0]).strip()
                if not out["machineId"]:
                    out["machineId"] = out["serviceMachineId"]
        finally:
            conn.close()
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import winreg

            access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
            if value:
                out["machineGuid"] = str(value)
        except Exception:
            pass
    return out


def generate_fingerprint() -> dict:
    service_id = str(uuid.uuid4())
    return {
        "machineId": service_id,
        "telemetryMachineId": _rand_hex64(),
        "macMachineId": str(uuid.uuid4()),
        "devDeviceId": str(uuid.uuid4()),
        "sqmId": "{" + str(uuid.uuid4()).upper() + "}",
        "serviceMachineId": service_id,
        # 默认不改系统 MachineGuid（需管理员且副作用大）；FlyCursor 可选改
        "machineGuid": None,
    }


def write_fingerprint(ids: dict) -> dict:
    """写入账号绑定的机器码。缺字段则跳过该项。"""
    wait_state_db_ready()
    errors: list[str] = []
    telemetry_mid = ids.get("telemetryMachineId") or ids.get("machineId")
    storage_patch = {}
    if telemetry_mid:
        storage_patch["telemetry.machineId"] = str(telemetry_mid)
    for src, key in (
        ("macMachineId", "telemetry.macMachineId"),
        ("devDeviceId", "telemetry.devDeviceId"),
        ("sqmId", "telemetry.sqmId"),
    ):
        if ids.get(src):
            storage_patch[key] = str(ids[src])

    if storage_patch:
        sj = storage_json_path()
        try:
            data = json.load(open(sj, "r", encoding="utf-8")) if os.path.isfile(sj) else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.update(storage_patch)
        try:
            _atomic_write(sj, json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8"))
        except Exception as exc:
            errors.append(f"storage.json: {exc}")

    service_id = ids.get("serviceMachineId") or ids.get("machineId")
    if service_id:
        try:
            conn = _open_db(readonly=False)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    ("storage.serviceMachineId", str(service_id)),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"serviceMachineId: {exc}")
        try:
            _atomic_write(machineid_path(), str(service_id).encode("utf-8"))
        except Exception as exc:
            errors.append(f"machineid: {exc}")

    return {"ok": not errors, "errors": errors, "ids": {k: ids.get(k) for k in (
        "machineId", "telemetryMachineId", "macMachineId", "devDeviceId", "sqmId", "serviceMachineId"
    )}}


def reset_machine_ids() -> dict:
    """生成并写入新指纹（会产生新 Desktop 设备）。"""
    ids = generate_fingerprint()
    result = write_fingerprint(ids)
    result["serviceMachineId"] = ids["serviceMachineId"]
    return result
