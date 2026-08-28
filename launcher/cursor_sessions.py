"""Cursor 登录会话列表与踢下线（移植自 ai-tools-mng + BajieAsk cursor-dashboard-api）。"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import requests

from .token_utils import UA, parse_token, session_id_from_token

SESSIONS_URL = "https://cursor.com/api/auth/sessions"
REVOKE_URL = "https://cursor.com/api/auth/sessions/revoke"
TIMEOUT = 30

REVOKE_TYPE_MAP = {
    "SESSION_TYPE_WEB": 1,
    "SESSION_TYPE_CLIENT": 2,
    "SESSION_TYPE_MOBILE": 10,
    "SESSION_TYPE_CHROME_EXTENSION": 11,
}

SESSION_TYPE_LABELS = {
    "SESSION_TYPE_WEB": "Web",
    "SESSION_TYPE_CLIENT": "Desktop App",
    "SESSION_TYPE_MOBILE": "Mobile",
    "SESSION_TYPE_CHROME_EXTENSION": "Extension",
}


def _session_token_string(raw: str) -> str:
    user_id, jwt, _ = parse_token(raw)
    return f"{user_id}::{jwt}"


def _list_headers(session_token: str) -> dict[str, str]:
    parts = session_token.split("::", 1)
    user_id = parts[0] if len(parts) > 1 else ""
    access = parts[1] if len(parts) > 1 else session_token
    cookies = [f"WorkosCursorSessionToken={quote(session_token, safe='')}"]
    if user_id:
        cookies.append(f"cursor-web-target-synced-user={user_id}")
    return {
        "Cookie": "; ".join(cookies),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Authorization": f"Bearer {access}",
        "Referer": "https://cursor.com/dashboard/settings",
    }


def _revoke_headers(session_token: str) -> dict[str, str]:
    headers = _list_headers(session_token)
    headers.update(
        {
            "Accept": "*/*",
            "Origin": "https://cursor.com",
            "Referer": "https://cursor.com/cn/dashboard/settings",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
    )
    return headers


def _pick_str(data: dict, keys: list[str]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _pick_bool(data: dict, keys: list[str]) -> bool | None:
    for key in keys:
        if key in data and isinstance(data[key], bool):
            return data[key]
    return None


def _pick_location(data: dict) -> str | None:
    direct = _pick_str(data, ["location", "geo_location", "geoLocation", "place"])
    if direct:
        return direct
    parts = [_pick_str(data, [k]) for k in ("city", "region", "state", "country")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _normalize_session(raw: dict, current_session_id: str | None) -> dict | None:
    session_id = _pick_str(raw, ["id", "session_id", "sessionId"])
    if not session_id:
        return None
    session_type = _pick_str(raw, ["type", "session_type", "sessionType"])
    is_current = _pick_bool(raw, ["is_current", "isCurrent", "current"])
    if is_current is None and current_session_id:
        is_current = session_id == current_session_id
    return {
        "id": session_id,
        "sessionType": session_type,
        "typeLabel": SESSION_TYPE_LABELS.get(session_type or "", session_type or "未知"),
        "ipAddress": _pick_str(raw, ["ip_address", "ipAddress", "ip"]),
        "location": _pick_location(raw),
        "device": _pick_str(
            raw,
            ["device_name", "deviceName", "device", "client_name", "clientName", "os", "browser", "user_agent", "userAgent"],
        ),
        "lastActiveAt": _pick_str(raw, ["last_active_at", "lastActiveAt", "last_seen_at", "lastSeenAt", "updated_at", "updatedAt"]),
        "createdAt": _pick_str(raw, ["created_at", "createdAt"]),
        "isCurrent": bool(is_current),
        "raw": raw,
    }


def _headers(cookie: str, *, post: bool = False) -> dict[str, str]:
    # 兼容旧调用：cookie 形如 WorkosCursorSessionToken=...
    if cookie.startswith("WorkosCursorSessionToken="):
        token = cookie.split("=", 1)[1]
        headers = _list_headers(token) if "::" in token or "%3A%3A" in token else {}
        if not headers:
            headers = {
                "Cookie": cookie,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://cursor.com/dashboard/settings",
                "User-Agent": UA,
            }
    else:
        headers = _list_headers(cookie)
    if post:
        headers = _revoke_headers(cookie if "::" in cookie else _session_token_string(cookie))
    return headers


def _error_message(body: str) -> str | None:
    try:
        data = json.loads(body)
    except Exception:
        return None
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        return str(msg) if msg else None
    if isinstance(err, str):
        return err
    return None


def _cookie_from_account_token(token: str) -> str:
    session_token = _session_token_string(token)
    return f"WorkosCursorSessionToken={quote(session_token, safe='')}"


def list_sessions(token: str, proxies: dict | None = None) -> list[dict]:
    session_token = _session_token_string(token)
    resp = requests.get(
        SESSIONS_URL,
        headers=_list_headers(session_token),
        timeout=TIMEOUT,
        proxies=proxies or {},
    )
    body = resp.text
    if "authenticator.cursor.sh" in resp.url:
        raise RuntimeError("会话已失效，cursor.com 跳转到登录页")
    if not resp.ok:
        msg = _error_message(body)
        raise RuntimeError(msg or f"拉取会话失败 HTTP {resp.status_code}")
    data = resp.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(_error_message(body) or "拉取会话失败")
    current_id = session_id_from_token(token)
    items = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, dict):
            normalized = _normalize_session(item, current_id)
            if normalized:
                out.append(normalized)
    return out


def revoke_session(token: str, session_id: str, session_type: str | None = None, proxies: dict | None = None) -> None:
    session_token = _session_token_string(token)
    payload: dict[str, Any] = {"session_id": session_id}
    mapped = REVOKE_TYPE_MAP.get(session_type or "", None)
    if mapped is not None:
        payload["type"] = mapped
    elif session_type:
        payload["type"] = session_type
    resp = requests.post(
        REVOKE_URL,
        headers=_revoke_headers(session_token),
        json=payload,
        timeout=TIMEOUT,
        proxies=proxies or {},
    )
    if "authenticator.cursor.sh" in resp.url:
        raise RuntimeError("会话已失效，无法踢下线")
    if not resp.ok:
        msg = _error_message(resp.text)
        raise RuntimeError(msg or f"踢下线失败 HTTP {resp.status_code}")


def revoke_all_except(
    token: str,
    keep_ids: set[str],
    sessions: list[dict] | None = None,
    delay_seconds: float = 0.35,
    proxies: dict | None = None,
) -> dict:
    """批量踢设备；keep_ids 内的会话绝不踢（含 isCurrent）。"""
    all_sessions = sessions if sessions is not None else list_sessions(token, proxies=proxies)
    protected = set(keep_ids)
    for session in all_sessions:
        if session.get("isCurrent"):
            protected.add(session["id"])

    revoked: list[str] = []
    skipped: list[str] = []
    errors: list[dict] = []

    for session in all_sessions:
        sid = session["id"]
        if sid in protected:
            skipped.append(sid)
            continue
        try:
            revoke_session(token, sid, session.get("sessionType"), proxies=proxies)
            revoked.append(sid)
            if delay_seconds > 0:
                time.sleep(delay_seconds)
        except Exception as exc:
            errors.append({"id": sid, "error": str(exc)})

    return {
        "ok": True,
        "revoked": revoked,
        "skipped": skipped,
        "errors": errors,
        "total": len(all_sessions),
    }
