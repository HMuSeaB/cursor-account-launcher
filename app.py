"""Cursor Launcher 主入口：pywebview + 本地 API。"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import webview

from launcher.account_store import AccountStore, SessionGuardStore
from launcher.ctxwin import ctxwin_apply as run_ctxwin_apply
from launcher.ctxwin import ctxwin_restore as run_ctxwin_restore
from launcher.ctxwin import ctxwin_status as read_ctxwin_status
from launcher.cursor_process import (
    close_cursor,
    compact_cursor_state,
    compact_precheck,
    is_cursor_running,
    light_workspace_dir,
    resolve_install,
    save_cursor_path,
    start_cursor,
)
from launcher.cursor_proxy import ProxyConfig, apply_proxy, read_current_proxy
from launcher.proxy_detect import detect_local_proxies, probe_direct, probe_proxy
from launcher.cursor_sessions import list_sessions, revoke_session, revoke_all_except
from launcher.cursor_usage import fetch_model_usage, refresh_account_usage
from launcher.session_keep import merge_keep_ids, pick_auto_keep_sessions, sessions_to_revoke
from launcher.local_cursor import (
    generate_fingerprint,
    read_fingerprint,
    read_local_account,
    reset_machine_ids,
    wait_state_db_ready,
    write_fingerprint,
    write_local_account,
)
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
        self._guard = SessionGuardService(
            self._store,
            self._guard_store,
            self._on_guard_event,
            proxies_fn=self._session_proxies,
        )
        self._guard.start()
        self._compact_lock = threading.Lock()
        self._compact_progress = {"busy": False, "pct": 0, "phase": "", "message": ""}

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

    def _session_proxies(self) -> dict:
        return self._request_proxies()

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

    def fetch_account_model_usage(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        result = fetch_model_usage(item["token"], proxies=self._request_proxies())
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error") or "获取失败"}
        return {
            "ok": True,
            "modelUsage": {
                "periodStartMs": result.get("periodStartMs"),
                "periodEndMs": result.get("periodEndMs"),
                "included": result.get("included"),
                "onDemand": result.get("onDemand"),
            },
        }

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
        if account_id and acct.get("refreshToken"):
            self._store.set_refresh_token(account_id, acct["refreshToken"])
        # 探测时绑定当前机器码，后续切回该号可复用，避免多出 Desktop
        if account_id:
            fp = acct.get("fingerprint") or read_fingerprint()
            if fp.get("machineId") or fp.get("serviceMachineId"):
                existing = self._store.get_device_ids(account_id)
                if not existing.get("machineId") and not existing.get("serviceMachineId"):
                    self._store.set_device_ids(account_id, fp)
        return {
            "ok": True,
            "id": account_id,
            "email": email,
            "hasWsToken": bool(acct.get("hasWsToken")),
            "wsToken": acct.get("wsToken") or "",
            "accounts": self._store.list(),
        }

    def sync_ws_token(self, account_id: str) -> dict:
        """从本机 state.vscdb 同步 WS Token 到已存账号。"""
        local = read_local_account()
        if not local or not local.get("token"):
            return {"ok": False, "error": "未检测到本机 Cursor 登录"}
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}

        ws = local.get("wsToken") or local.get("token") or ""
        if "::" not in ws and "%3A%3A" not in ws.upper():
            return {"ok": False, "error": "本机仅有 access_token，请先在 Cursor 网页完成登录后再试"}

        try:
            local_uid, _, _ = parse_token(ws)
            acct_uid, _, _ = parse_token(item["token"])
            if local_uid != acct_uid:
                return {
                    "ok": False,
                    "error": f"本机账号 ({local_uid}) 与所选账号 ({acct_uid}) 不一致",
                }
        except Exception:
            pass

        updated = self._store.update_token(account_id, ws)
        if not updated:
            return {"ok": False, "error": "更新 token 失败"}
        if local.get("refreshToken"):
            self._store.set_refresh_token(account_id, local["refreshToken"])
        fp = local.get("fingerprint") or read_fingerprint()
        if fp.get("machineId") or fp.get("serviceMachineId"):
            if not self._store.get_device_ids(account_id):
                self._store.set_device_ids(account_id, fp)
        detail = self._store.get_detail(account_id) or updated
        return {"ok": True, "account": detail, "hasWsToken": True}

    def remove_account(self, account_id: str) -> list:
        self._store.remove(account_id)
        return self._store.list()

    def export_accounts(
        self,
        account_ids: list | None = None,
        include_secrets: bool = False,
        fmt: str = "json",
    ) -> dict:
        ids = list(account_ids or [])
        if not ids:
            ids = [a["id"] for a in self._store.list()]
        rows: list[dict] = []
        for aid in ids:
            detail = self._store.get_detail(aid)
            if not detail:
                continue
            row = {
                "id": detail["id"],
                "email": detail.get("email") or detail.get("label") or detail["id"],
                "label": detail.get("label") or "",
                "group": detail.get("group") or "未分组",
                "tags": list(detail.get("tags") or []),
                "remark": detail.get("remark") or "",
                "hasWsToken": bool(detail.get("hasWsToken")),
                "membershipType": detail.get("membershipType") or "",
                "usageLine": detail.get("usageLine") or "",
                "costUsd": detail.get("costUsd"),
                "costMaxUsd": detail.get("costMaxUsd"),
                "usagePct": detail.get("usagePct"),
                "apiPercentUsed": detail.get("apiPercentUsed"),
                "autoPercentUsed": detail.get("autoPercentUsed"),
                "periodCostUsd": detail.get("periodCostUsd"),
                "requestCount30d": detail.get("requestCount30d"),
                "lastRefreshed": detail.get("lastRefreshed"),
            }
            if include_secrets:
                row["token"] = detail.get("token") or ""
                password = detail.get("password") or ""
                if password:
                    row["password"] = password
            rows.append(row)

        if not rows:
            return {"ok": False, "error": "没有可导出的账号"}

        export_fmt = (fmt or "json").lower()
        default_name = (
            "cursor-accounts-export.csv" if export_fmt == "csv" else "cursor-accounts-export.json"
        )
        path = None
        try:
            if self._window is not None:
                if export_fmt == "csv":
                    file_types = ("CSV (*.csv)", "所有文件 (*.*)")
                else:
                    file_types = ("JSON (*.json)", "所有文件 (*.*)")
                path = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=default_name,
                    file_types=file_types,
                )
        except Exception:
            path = None
        if not path:
            return {"ok": False, "cancelled": True, "count": len(rows)}
        out_path = path[0] if isinstance(path, (list, tuple)) else path

        try:
            if export_fmt == "csv":
                import csv

                headers = [
                    "id",
                    "email",
                    "group",
                    "tags",
                    "remark",
                    "membershipType",
                    "usageLine",
                    "costUsd",
                    "costMaxUsd",
                    "usagePct",
                    "lastRefreshed",
                ]
                if include_secrets:
                    headers.extend(["token", "password"])
                with open(out_path, "w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        flat = dict(row)
                        flat["tags"] = ",".join(flat.get("tags") or [])
                        writer.writerow(flat)
            else:
                payload = {
                    "version": 1,
                    "includeSecrets": include_secrets,
                    "accounts": rows,
                }
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
            return {"ok": True, "count": len(rows), "path": str(out_path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "count": len(rows)}

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

    def ctxwin_status(self) -> dict:
        try:
            return read_ctxwin_status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ctxwin_apply(self) -> dict:
        try:
            return run_ctxwin_apply()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def ctxwin_restore(self) -> dict:
        try:
            return run_ctxwin_restore()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def launch_ide(
        self,
        account_id: str | None = None,
        reset_machine_id: bool = False,
        force: bool = False,
        machine_mode: str = "bind",
        light: bool = False,
    ) -> dict:
        """切号启动。light=True 时关 GPU、打开空工作区，适合打游戏挂机。"""
        try:
            if light:
                force = True
            if not account_id and is_cursor_running() and not force:
                return {
                    "ok": False,
                    "alreadyRunning": True,
                    "error": "Cursor 已在运行。继续将启动新实例。",
                }
            layout = resolve_install()
            proxy_cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
            if proxy_cfg.apply_on_launch:
                applied = apply_proxy(proxy_cfg)
                if not applied.get("ok"):
                    return {"ok": False, "error": applied.get("error") or "代理注入失败"}

            mode = (machine_mode or "bind").lower()
            if reset_machine_id:
                mode = "reset"

            if account_id:
                item = self._store.get(account_id)
                if not item:
                    return {"ok": False, "error": "账号不存在"}
                user_id, jwt, claims = parse_token(item["token"])
                email = item.get("label") or item.get("email") or claims.get("email") or user_id
                refresh = self._store.get_refresh_token(account_id) or None
                membership = item.get("membershipType") or None

                close_cursor(layout)
                wait_state_db_ready()

                if mode == "reset":
                    reset_machine_ids()
                    self._store.set_device_ids(account_id, read_fingerprint())
                elif mode == "bind":
                    bound = self._store.get_device_ids(account_id)
                    if bound.get("machineId") or bound.get("serviceMachineId") or bound.get("telemetryMachineId"):
                        write_fingerprint(bound)
                    else:
                        fp = read_fingerprint()
                        if not (fp.get("machineId") or fp.get("serviceMachineId")):
                            fp = generate_fingerprint()
                            write_fingerprint(fp)
                        self._store.set_device_ids(account_id, fp)

                write_local_account(
                    item["token"],
                    email,
                    refresh_token=refresh,
                    membership=str(membership) if membership else None,
                    keep_refresh_if_missing=True,
                )
                time.sleep(0.4)
            elif light and is_cursor_running():
                close_cursor(layout)
                wait_state_db_ready()

            start_cursor(layout, light=bool(light))
            return {
                "ok": True,
                "launched": True,
                "classic": True,
                "light": bool(light),
                "workspace": str(light_workspace_dir()) if light else "",
                "machineMode": mode if account_id else "none",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def close_ide(self) -> dict:
        """关掉 Cursor，腾出内存。账号仍留在启动器。"""
        try:
            if not is_cursor_running():
                return {"ok": True, "running": False, "closed": False}
            layout = resolve_install()
            close_cursor(layout)
            wait_state_db_ready()
            return {"ok": True, "running": is_cursor_running(), "closed": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "running": is_cursor_running()}

    def compact_precheck(self) -> dict:
        try:
            return compact_precheck()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def compact_progress(self) -> dict:
        return dict(self._compact_progress)

    def compact_start(self) -> dict:
        pre = compact_precheck()
        if not pre.get("ok"):
            return pre
        with self._compact_lock:
            if self._compact_progress.get("busy"):
                return {"ok": False, "error": "正在压缩，请稍候"}
            self._compact_progress = {
                "busy": True,
                "pct": 1,
                "phase": "start",
                "message": f"准备压缩 {pre.get('sizeMb', 0)}MB…",
            }
        threading.Thread(target=self._run_compact, daemon=True).start()
        return {"ok": True, "started": True, "sizeMb": pre.get("sizeMb"), "backupMb": pre.get("backupMb")}

    def compact_cursor_state(self) -> dict:
        """占用时立即返回；真正压缩请走 compact_start，避免卡住界面。"""
        return self.compact_precheck()

    def _run_compact(self) -> None:
        def on_progress(payload: dict) -> None:
            with self._compact_lock:
                self._compact_progress = {"busy": True, **payload}
            self._emit_compact(self._compact_progress)

        try:
            result = compact_cursor_state(on_progress=on_progress)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        done = {
            "busy": False,
            "pct": 100 if result.get("ok") else int(self._compact_progress.get("pct") or 0),
            "phase": "done" if result.get("ok") else "error",
            "message": (
                f"压缩完成 {result.get('beforeMb')}MB → {result.get('afterMb')}MB，现在可以打开 Cursor"
                if result.get("ok")
                else (result.get("error") or "压缩失败")
            ),
            "result": result,
        }
        with self._compact_lock:
            self._compact_progress = done
        self._emit_compact(done)

    def _emit_compact(self, payload: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('compact-progress', {detail: "
                + json.dumps(payload, ensure_ascii=False)
                + "}))"
            )
        except Exception:
            pass

    # ---- 代理 ----

    def get_proxy(self) -> dict:
        saved = _read_json("proxy.json", ProxyConfig().to_dict())
        current = read_current_proxy()
        return {"saved": saved, "cursorSettings": current}

    def detect_proxy(self, probe: bool = True) -> dict:
        try:
            return detect_local_proxies(probe=bool(probe))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_proxy_latency(
        self,
        proxy_type: str | None = None,
        host: str | None = None,
        port: int | None = None,
        enabled: bool | None = None,
    ) -> dict:
        """测试当前/指定代理到 cursor.com 的延迟。"""
        try:
            cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
            use_enabled = cfg.enabled if enabled is None else bool(enabled)
            ptype = proxy_type or cfg.proxy_type or "http"
            phost = host or cfg.host or "127.0.0.1"
            pport = int(port or cfg.port or 7890)
            if not use_enabled:
                direct = probe_direct()
                return {"ok": True, "mode": "direct", **direct}
            result = probe_proxy(ptype, phost, pport)
            return {"ok": True, "mode": "proxy", **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_proxy(self, config: dict) -> dict:
        cfg = ProxyConfig.from_dict(config)
        _write_json("proxy.json", cfg.to_dict())
        try:
            applied = apply_proxy(cfg)
            if not applied.get("ok"):
                return {"ok": False, "error": applied.get("error") or "代理写入失败", "config": cfg.to_dict()}
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
        try:
            sessions = list_sessions(token, proxies=self._session_proxies())
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
        token = item["token"]
        from launcher.token_utils import session_id_from_token

        current_id = session_id_from_token(token)
        if current_id and session_id == current_id:
            return {"ok": False, "error": "不能踢掉当前 Token 对应的会话，否则会掉号"}
        if session_type == "SESSION_TYPE_CLIENT":
            return {
                "ok": False,
                "error": "Desktop 默认受保护，防止误踢本机。请到网页 Cursor 设置里手动 Revoke。",
                "protected": True,
            }
        try:
            revoke_session(
                token,
                session_id,
                session_type,
                proxies=self._session_proxies(),
            )
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
                    sessions = list_sessions(item["token"], proxies=self._session_proxies())
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
        try:
            sessions = list_sessions(token, proxies=self._session_proxies())
            picked = pick_auto_keep_sessions(sessions, token)
            return {"ok": True, "sessions": sessions, "keepIds": picked["keepIds"], "reasons": picked["reasons"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def revoke_other_sessions(self, account_id: str, keep_session_ids: list | None = None) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        token = item["token"]
        proxies = self._session_proxies()
        try:
            sessions = list_sessions(token, proxies=proxies)
            # 用户勾选 ∪ 自动保护（全部 Desktop + Token 会话），禁止用空名单覆盖保护
            keep = merge_keep_ids(sessions, token, keep_session_ids)
            targets = sessions_to_revoke(sessions, keep)
            if not targets:
                return {"ok": True, "revoked": [], "message": "没有需要踢掉的设备", "keepIds": sorted(keep)}
            result = revoke_all_except(token, keep, sessions=sessions, proxies=proxies)
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
        background_color="#ECEAE6",
    )
    api._window = window
    webview.start()


if __name__ == "__main__":
    main()
