"""Token 解析与 Cursor 会话 Cookie 构造。"""

from __future__ import annotations

import base64
import json
import re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _b64url_json(segment: str) -> dict:
    segment = segment.replace("-", "+").replace("_", "/")
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.b64decode(segment).decode("utf-8", "replace"))


def parse_token(raw: str) -> tuple[str, str, dict]:
    """解析 token → (user_id, access_jwt, claims)。支持 ws token 与裸 JWT。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("空 token")
    text = re.sub(r"^WorkosCursorSessionToken=", "", text, flags=re.I).strip()
    sep = "::" if "::" in text else ("%3A%3A" if "%3A%3A" in text else None)
    pasted_uid = None
    jwt = text
    if sep:
        left, _, right = text.partition(sep)
        pasted_uid = left.strip()
        jwt = right.strip()
    claims: dict = {}
    try:
        claims = _b64url_json(jwt.split(".")[1])
    except Exception:
        claims = {}
    sub = str(claims.get("sub", ""))
    from_sub = sub.split("|")[-1] if sub else ""
    user_id = from_sub if from_sub.startswith("user_") else (pasted_uid or "")
    if not user_id.startswith("user_"):
        raise ValueError("无法解析 user id")
    return user_id, jwt, claims


def session_cookie(user_id: str, jwt: str) -> str:
    return f"WorkosCursorSessionToken={user_id}%3A%3A{jwt}"


def session_id_from_token(raw: str) -> str | None:
    """从 token JWT payload 提取 workosSessionId（用于标记本机会话）。"""
    text = (raw or "").strip()
    sep = "::" if "::" in text else ("%3A%3A" if "%3A%3A" in text else None)
    jwt = text.partition(sep)[2] if sep else text
    try:
        payload = _b64url_json(jwt.split(".")[1])
    except Exception:
        return None
    for key in ("workosSessionId", "workos_session_id", "sid", "session_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def email_from_claims(claims: dict) -> str:
    for key in ("email", "user_email", "preferred_username", "name"):
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return value.strip()
    return ""
