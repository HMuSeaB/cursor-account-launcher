"""会话保留策略：只留本机 Web + Desktop，不误踢自己。"""

from __future__ import annotations

from .token_utils import session_id_from_token

WEB_TYPE = "SESSION_TYPE_WEB"
CLIENT_TYPE = "SESSION_TYPE_CLIENT"


def _time_key(session: dict) -> str:
    for key in ("lastActiveAt", "createdAt"):
        value = session.get(key)
        if value:
            return str(value)
    raw = session.get("raw") or {}
    for key in ("last_active_at", "lastActiveAt", "created_at", "createdAt", "updated_at", "updatedAt"):
        if raw.get(key):
            return str(raw[key])
    return ""


def pick_auto_keep_sessions(sessions: list[dict], token: str) -> dict:
    """自动选出应保留的会话：本机 Desktop（token 对应）+ 最近活跃的 Web 各 1 个。"""
    current_id = session_id_from_token(token)
    keep_ids: set[str] = set()
    reasons: dict[str, str] = {}

    if current_id:
        keep_ids.add(current_id)
        reasons[current_id] = "本机 Desktop（Token 会话）"

    for session in sessions:
        sid = session.get("id")
        if not sid:
            continue
        if session.get("isCurrent"):
            keep_ids.add(sid)
            reasons[sid] = reasons.get(sid, "本机当前会话")

    web_sessions = [s for s in sessions if s.get("sessionType") == WEB_TYPE]
    client_sessions = [s for s in sessions if s.get("sessionType") == CLIENT_TYPE]

    if web_sessions:
        newest_web = max(web_sessions, key=_time_key)
        keep_ids.add(newest_web["id"])
        if newest_web["id"] not in reasons:
            reasons[newest_web["id"]] = "最近活跃的 Web 会话"

    if client_sessions:
        desktop = None
        if current_id:
            desktop = next((s for s in client_sessions if s["id"] == current_id), None)
        if not desktop:
            desktop = next((s for s in client_sessions if s.get("isCurrent")), None)
        if not desktop:
            desktop = max(client_sessions, key=_time_key)
        keep_ids.add(desktop["id"])
        if desktop["id"] not in reasons:
            reasons[desktop["id"]] = "本机 Desktop 客户端"

    return {
        "keepIds": sorted(keep_ids),
        "reasons": reasons,
        "currentSessionId": current_id,
    }


def sessions_to_revoke(sessions: list[dict], keep_ids: set[str]) -> list[dict]:
    out = []
    for session in sessions:
        sid = session.get("id")
        if not sid or sid in keep_ids:
            continue
        if session.get("isCurrent"):
            continue
        out.append(session)
    return out
