"""Cursor Launcher 主入口：pywebview + 本地 API。"""

from __future__ import annotations

import json
import os
import sys

import webview

from launcher.account_store import AccountStore, SessionGuardStore
from launcher.cursor_process import close_cursor, is_cursor_running, resolve_install, save_cursor_path, start_cursor
from launcher.cursor_proxy import ProxyConfig, apply_proxy, read_current_proxy
from launcher.cursor_sessions import list_sessions, revoke_session, revoke_all_except
from launcher.cursor_usage import refresh_account_usage
from launcher.session_keep import pick_auto_keep_sessions, sessions_to_revoke
from launcher.local_cursor import read_local_account, reset_machine_ids, write_local_account
from launcher.session_guard import SessionGuardService
from launcher.token_utils import parse_token


def _app_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _state_path(name: str) -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "CursorLauncher", name)


def _read_json(name: str, default):
    try:
        with open(_state_path(name), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(name: str, data) -> None:
    path = _state_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class Api:
    def __init__(self) -> None:
        self._store = AccountStore()
        self._guard_store = SessionGuardStore()
        self._window: webview.Window | None = None
        self._guard = SessionGuardService(self._store, self._guard_store, self._on_guard_event)
        self._guard.start()

    def _on_guard_event(self, payload: dict) -> None:
        if self._window is not None:
            try:
                self._window.evaluate_js(
                    f"window.dispatchEvent(new CustomEvent('guard-event', {{detail: {json.dumps(payload, ensure_ascii=False)}}}))"
                )
            except Exception:
                pass

    def _request_proxies(self) -> dict:
        cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
        if not cfg.enabled:
            return {}
        url = cfg.http_proxy_url()
        return {"http": url, "https": url}

    # ---- 账号 ----

    def list_accounts(self) -> list:
        return self._store.list()

    def get_account_detail(self, account_id: str) -> dict:
        detail = self._store.get_detail(account_id)
        if not detail:
            return {"ok": False, "error": "账号不存在"}
        return {"ok": True, "account": detail}

    def update_account(self, account_id: str, meta: dict) -> dict:
        updated = self._store.update_meta(
            account_id,
            email=meta.get("email"),
            password=meta.get("password"),
            group=meta.get("group"),
            tags=meta.get("tags"),
            remark=meta.get("remark"),
        )
        if not updated:
            return {"ok": False, "error": "账号不存在"}
        return {"ok": True, "account": updated}

    def refresh_account(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        result = refresh_account_usage(item["token"], proxies=self._request_proxies())
        if not result.get("ok"):
            self._store.update_usage_snapshot(account_id, {"err": result.get("error"), "ok": False})
            return {"ok": False, "error": result.get("error")}
        account = self._store.update_usage_snapshot(account_id, result)
        return {"ok": True, "account": account}

    def refresh_all_accounts(self) -> dict:
        refreshed = []
        errors = []
        for acct in self._store.list():
            res = self.refresh_account(acct["id"])
            if res.get("ok"):
                refreshed.append(acct["id"])
            else:
                errors.append({"id": acct["id"], "error": res.get("error")})
        return {"ok": True, "refreshed": refreshed, "errors": errors, "accounts": self._store.list()}

    def list_account_filters(self) -> dict:
        return {"groups": self._store.list_groups(), "tags": self._store.list_tags()}

    def import_text(self, text: str) -> dict:
        added = self._store.add_text(text or "")
        return {"added": len(added), "accounts": self._store.list()}

    def import_files(self) -> dict:
        paths = None
        try:
            if self._window is not None:
                paths = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=("JSON 文件 (*.json)", "文本文件 (*.txt)", "所有文件 (*.*)"),
                )
        except Exception:
            paths = None
        if not paths:
            return {"added": 0, "accounts": self._store.list()}
        added = self._store.add_json_files(list(paths))
        return {"added": len(added), "accounts": self._store.list()}

    def detect_local_account(self) -> dict:
        acct = read_local_account()
        if not acct or not acct.get("token"):
            return {"ok": False, "error": "未检测到本机 Cursor 登录"}
        touched = self._store.add_text(acct["token"])
        account_id = touched[0]["id"] if touched else None
        email = acct.get("email")
        if account_id and email and "@" in email:
            self._store.set_label(account_id, email)
        return {"ok": True, "id": account_id, "email": email, "accounts": self._store.list()}

    def remove_account(self, account_id: str) -> list:
        self._store.remove(account_id)
        return self._store.list()

    # ---- 启动 / 切号 ----

    def cursor_status(self) -> dict:
        try:
            layout = resolve_install()
            return {
                "ok": True,
                "running": is_cursor_running(),
                "path": str(layout.install_root),
                "executable": str(layout.executable),
                "version": layout.version,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "running": is_cursor_running()}

    def set_cursor_path(self, path: str) -> dict:
        try:
            info = save_cursor_path(path or "auto")
            layout = resolve_install()
            info.update({"executable": str(layout.executable), "version": layout.version})
            return {"ok": True, **info}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def launch_ide(self, account_id: str | None = None, reset_machine_id: bool = False) -> dict:
        try:
            layout = resolve_install()
            proxy_cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
            apply_proxy(proxy_cfg)

            if account_id:
                item = self._store.get(account_id)
                if not item:
                    return {"ok": False, "error": "账号不存在"}
                user_id, jwt, claims = parse_token(item["token"])
                email = item.get("label") or claims.get("email") or user_id
                close_cursor(layout)
                write_local_account(jwt, email)
                if reset_machine_id:
                    reset_machine_ids()
            start_cursor(layout)
            return {"ok": True, "launched": True, "classic": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- 代理 ----

    def get_proxy(self) -> dict:
        saved = _read_json("proxy.json", ProxyConfig().to_dict())
        current = read_current_proxy()
        return {"saved": saved, "cursorSettings": current}

    def save_proxy(self, config: dict) -> dict:
        cfg = ProxyConfig.from_dict(config)
        _write_json("proxy.json", cfg.to_dict())
        try:
            applied = apply_proxy(cfg)
            return {"ok": True, "config": cfg.to_dict(), "applied": applied}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "config": cfg.to_dict()}

    def apply_proxy_now(self) -> dict:
        cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
        try:
            return {"ok": True, **apply_proxy(cfg)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---- 会话 ----

    def list_sessions(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        token = item["token"]
        if "::" not in token and "%3A%3A" not in token:
            return {"ok": False, "error": "会话 API 需要 ws token（user_xxx::eyJ...），请用完整会话 token 导入"}
        try:
            sessions = list_sessions(token)
            guard = self._guard_store.get(account_id)
            picked = pick_auto_keep_sessions(sessions, token)
            return {
                "ok": True,
                "sessions": sessions,
                "guard": guard,
                "autoKeepIds": picked["keepIds"],
                "keepReasons": picked["reasons"],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def revoke_session(self, account_id: str, session_id: str, session_type: str | None = None) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        try:
            revoke_session(item["token"], session_id, session_type)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_session_guard(self, account_id: str) -> dict:
        return {"ok": True, "guard": self._guard_store.get(account_id)}

    def save_session_guard(
        self,
        account_id: str,
        enabled: bool,
        keep_session_ids: list,
        interval_seconds: int = 300,
        mode: str = "whitelist",
    ) -> dict:
        guard = self._guard_store.save(
            account_id,
            enabled,
            keep_session_ids,
            interval_seconds,
            mode=mode,
        )
        if enabled and mode == "auto_kick":
            item = self._store.get(account_id)
            if item:
                try:
                    sessions = list_sessions(item["token"])
                    self._guard_store.set_baseline(account_id, [s["id"] for s in sessions])
                    guard = self._guard_store.get(account_id)
                except Exception:
                    pass
        return {"ok": True, "guard": guard}

    def run_session_guard(self, account_id: str) -> dict:
        return self._guard.run_once(account_id)

    def suggest_keep_sessions(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        token = item["token"]
        if "::" not in token and "%3A%3A" not in token:
            return {"ok": False, "error": "会话 API 需要 ws token（user_xxx::eyJ...），请用完整会话 token 导入"}
        try:
            sessions = list_sessions(token)
            picked = pick_auto_keep_sessions(sessions, token)
            return {"ok": True, "sessions": sessions, "keepIds": picked["keepIds"], "reasons": picked["reasons"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def revoke_other_sessions(self, account_id: str, keep_session_ids: list | None = None) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        token = item["token"]
        if "::" not in token and "%3A%3A" not in token:
            return {"ok": False, "error": "会话 API 需要 ws token（user_xxx::eyJ...）"}
        try:
            sessions = list_sessions(token)
            if keep_session_ids:
                keep = set(keep_session_ids)
            else:
                keep = set(pick_auto_keep_sessions(sessions, token)["keepIds"])
            targets = sessions_to_revoke(sessions, keep)
            if not targets:
                return {"ok": True, "revoked": [], "message": "没有需要踢掉的设备", "keepIds": sorted(keep)}
            result = revoke_all_except(token, keep, sessions=sessions)
            result["keepIds"] = sorted(keep)
            result["targetCount"] = len(targets)
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main() -> None:
    api = Api()
    window = webview.create_window(
        "Cursor Launcher",
        resource_path(os.path.join("web", "index.html")),
        js_api=api,
        width=1080,
        height=760,
        min_size=(900, 640),
        background_color="#E8F0FE",
    )
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()
