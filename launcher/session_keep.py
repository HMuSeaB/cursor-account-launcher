"""会话保留策略：绝不误踢本机 Desktop / Token 对应会话。"""

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
    """选出默认应保留的会话。

    安全策略（JWT 往往对不上 sessionId，不能只留「最新 Desktop」）：
    - Token 对应会话（若能解析）
    - 标记为 isCurrent 的会话
    - **全部** Desktop App（SESSION_TYPE_CLIENT）——「踢其它」默认只清 Web/其它端
    - 最近一条 Web（方便网页端继续用）
    """
    current_id = session_id_from_token(token)
    keep_ids: set[str] = set()
    reasons: dict[str, str] = {}

    if current_id:
        keep_ids.add(current_id)
        reasons[current_id] = "本机 Token 会话"

    for session in sessions:
        sid = session.get("id")
        if not sid:
            continue
        if session.get("isCurrent"):
            keep_ids.add(sid)
            reasons[sid] = reasons.get(sid, "本机当前会话")

    web_sessions = [s for s in sessions if s.get("sessionType") == WEB_TYPE]
    client_sessions = [s for s in sessions if s.get("sessionType") == CLIENT_TYPE]

    for desktop in client_sessions:
        sid = desktop["id"]
        keep_ids.add(sid)
        if sid not in reasons:
            reasons[sid] = "Desktop App（默认保留，防误踢本机）"

    if web_sessions:
        newest_web = max(web_sessions, key=_time_key)
        keep_ids.add(newest_web["id"])
        if newest_web["id"] not in reasons:
            reasons[newest_web["id"]] = "最近活跃的 Web 会话"

    return {
        "keepIds": sorted(keep_ids),
        "reasons": reasons,
        "currentSessionId": current_id,
    }


def merge_keep_ids(
    sessions: list[dict],
    token: str,
    user_keep_ids: list[str] | set[str] | None = None,
) -> set[str]:
    """用户勾选 ∪ 自动保护名单。自动保护不可被取消。"""
    auto = pick_auto_keep_sessions(sessions, token)
    keep = set(auto["keepIds"])
    if user_keep_ids:
        keep.update(str(x) for x in user_keep_ids if x)
    for session in sessions:
        if session.get("isCurrent") and session.get("id"):
            keep.add(session["id"])
    return keep


def sessions_to_revoke(sessions: list[dict], keep_ids: set[str]) -> list[dict]:
    out = []
    for session in sessions:
        sid = session.get("id")
        if not sid or sid in keep_ids:
            continue
        if session.get("isCurrent"):
            continue
        # 硬保护：即使用户取消勾选，也不批量踢 Desktop
        if session.get("sessionType") == CLIENT_TYPE:
            continue
        out.append(session)
    return out
