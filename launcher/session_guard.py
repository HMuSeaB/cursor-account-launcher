"""会话守卫：whitelist（保留名单）与 auto_kick（踢新设备，移植自 BajieAsk）。"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .accounts import AccountStore, SessionGuardStore
from .cursor_sessions import list_sessions, revoke_session

NEW_DEVICE_BURST_THRESHOLD = 3
MAX_CONSECUTIVE_ERRORS = 3


class SessionGuardService:
    def __init__(
        self,
        accounts: AccountStore,
        guard_store: SessionGuardStore,
        on_event: Callable[[dict], None] | None = None,
        proxies_fn: Callable[[], dict] | None = None,
    ) -> None:
        self._accounts = accounts
        self._guard_store = guard_store
        self._on_event = on_event
        self._proxies_fn = proxies_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors: dict[str, int] = {}

    def _proxies(self) -> dict:
        if not self._proxies_fn:
            return {}
        try:
            return self._proxies_fn() or {}
        except Exception:
            return {}

    def _emit(self, payload: dict) -> None:
        if self._on_event:
            try:
                self._on_event(payload)
            except Exception:
                pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="session-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self, account_id: str) -> dict:
        account = self._accounts.get(account_id)
        if not account:
            return {"ok": False, "error": "账号不存在"}
        cfg = self._guard_store.get(account_id)
        token = account["token"]
        mode = cfg.get("mode") or "whitelist"
        try:
            sessions = list_sessions(token, proxies=self._proxies())
        except Exception as exc:
            self._bump_error(account_id)
            return {"ok": False, "error": str(exc), "mode": mode}

        self._errors[account_id] = 0
        if mode == "auto_kick":
            return self._run_auto_kick(account_id, token, sessions, cfg)
        return self._run_whitelist(account_id, token, sessions, cfg)

    def _run_whitelist(self, account_id: str, token: str, sessions: list[dict], cfg: dict) -> dict:
        keep = set(cfg.get("keepSessionIds") or [])
        revoked, kept, errors = [], [], []
        for session in sessions:
            sid = session["id"]
            if session.get("isCurrent") or sid in keep:
                kept.append(sid)
                continue
            try:
                revoke_session(token, sid, session.get("sessionType"), proxies=self._proxies())
                revoked.append(sid)
            except Exception as exc:
                errors.append({"id": sid, "error": str(exc)})
        result = {
            "ok": True,
            "mode": "whitelist",
            "accountId": account_id,
            "revoked": revoked,
            "kept": kept,
            "errors": errors,
            "total": len(sessions),
        }
        self._emit({"type": "guard_run", **result})
        return result

    def _run_auto_kick(self, account_id: str, token: str, sessions: list[dict], cfg: dict) -> dict:
        baseline = set(cfg.get("baselineSessionIds") or [])
        if not baseline:
            baseline = {s["id"] for s in sessions}
            self._guard_store.set_baseline(account_id, list(baseline))

        current_ids = {s["id"] for s in sessions}
        new_sessions = [s for s in sessions if s["id"] not in baseline]
        if len(new_sessions) > NEW_DEVICE_BURST_THRESHOLD:
            self._bump_error(account_id)
            return {
                "ok": False,
                "mode": "auto_kick",
                "error": f"burst_detected:{len(new_sessions)}",
                "accountId": account_id,
                "total": len(sessions),
            }

        revoked, errors = [], []
        for session in new_sessions:
            sid = session["id"]
            try:
                revoke_session(token, sid, session.get("sessionType"), proxies=self._proxies())
                revoked.append(sid)
            except Exception as exc:
                errors.append({"id": sid, "error": str(exc)})

        if revoked:
            try:
                sessions = list_sessions(token, proxies=self._proxies())
            except Exception:
                sessions = [s for s in sessions if s["id"] not in revoked]
        baseline = {s["id"] for s in sessions}
        self._guard_store.set_baseline(account_id, list(baseline))

        result = {
            "ok": True,
            "mode": "auto_kick",
            "accountId": account_id,
            "revoked": revoked,
            "baselineSize": len(baseline),
            "errors": errors,
            "total": len(sessions),
        }
        self._emit({"type": "guard_run", **result})
        return result

    def _bump_error(self, account_id: str) -> None:
        count = self._errors.get(account_id, 0) + 1
        self._errors[account_id] = count
        if count >= MAX_CONSECUTIVE_ERRORS:
            cfg = self._guard_store.get(account_id)
            self._guard_store.save(
                account_id,
                enabled=False,
                keep_session_ids=cfg.get("keepSessionIds") or [],
                interval_seconds=cfg.get("intervalSeconds") or 300,
                mode=cfg.get("mode") or "whitelist",
                baseline_session_ids=cfg.get("baselineSessionIds") or [],
            )
            self._emit({"type": "guard_disabled", "accountId": account_id, "reason": "circuit_open"})

    def _loop(self) -> None:
        while not self._stop.is_set():
            for account_id, cfg in self._guard_store.list_enabled():
                if self._stop.is_set():
                    break
                self.run_once(account_id)
                interval = int(cfg.get("intervalSeconds") or 300)
                self._stop.wait(min(interval, 60))
            self._stop.wait(30)
