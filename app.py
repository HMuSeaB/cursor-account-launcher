"""Cursor Launcher 主入口：pywebview + 本地 API。"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import webview

from launcher.account_store import (
    AccountStore,
    SessionGuardStore,
    canonical_machine_id,
    short_machine_id,
    sort_account_rows,
)
from launcher.ctxwin import ctxwin_apply as run_ctxwin_apply
from launcher.ctxwin import ctxwin_restore as run_ctxwin_restore
from launcher.ctxwin import ctxwin_status as read_ctxwin_status
from launcher.model_unlock import apply as run_model_unlock_apply
from launcher.model_unlock import repair_corrupted as run_model_unlock_repair
from launcher.model_unlock import restore as run_model_unlock_restore
from launcher.model_unlock import set_membership_setting
from launcher.model_unlock import status as read_model_unlock_status
from launcher.model_unlock import sync_storage_membership
from launcher.sand_stream import apply as run_sand_stream_apply
from launcher.sand_stream import restore as run_sand_stream_restore
from launcher.sand_stream import status as read_sand_stream_status
from launcher.cursor_process import (
    close_cursor,
    compact_cursor_state,
    compact_precheck,
    configured_cursor_path,
    is_cursor_running,
    light_workspace_dir,
    list_cursor_processes,
    resolve_install,
    save_cursor_path,
    start_cursor,
    trim_cursor_memory,
    update_config,
    _load_config,
)
from launcher.cursor_proxy import (
    ProxyConfig,
    apply_proxy,
    proxy_backup_status,
    proxy_chromium_args,
    proxy_env,
    read_current_proxy,
    restore_proxy_files,
)
from launcher.bajie_route import apply_bajie_route, detect_patch
from launcher.api_patches import PatchesApiMixin
from launcher.process_proxy import (
    deploy_process_proxy,
    emergency_cleanup,
    remove_process_proxy,
    restore_process_proxy,
    status as process_proxy_status,
)
from launcher.cursor_update import apply_disable_updates, read_update_status, restore_updates
from launcher.proxy_detect import detect_local_proxies, probe_direct, probe_proxy
from launcher.cursor_sessions import list_sessions, revoke_session, revoke_all_except
from launcher.cursor_usage import fetch_model_usage, refresh_account_usage
from launcher.session_keep import merge_keep_ids, pick_auto_keep_sessions, sessions_to_revoke
from launcher.local_cursor import (
    generate_fingerprint,
    peek_local_identity,
    peek_local_machine_short,
    read_fingerprint,
    read_local_account,
    reset_machine_ids,
    wait_state_db_ready,
    write_fingerprint,
    write_local_account,
)
from launcher.window_state import attach_window_persistence, load_window_geom
from launcher.session_guard import SessionGuardService
from launcher.shortcuts import (
    create_shortcuts as make_shortcut_links,
    is_frozen as launcher_is_frozen,
    mark_shortcut_prompted,
    refresh_shortcut_icons as refresh_shortcut_icon_links,
    shortcut_status as get_shortcut_status,
)
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


class Api(PatchesApiMixin):
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
        self._job_lock = threading.Lock()
        self._job_progress = {
            "busy": False,
            "pct": 0,
            "phase": "",
            "message": "",
            "job": "",
            "result": None,
        }

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
        ident = peek_local_identity()
        last_id = str(_load_config().get("lastAccountId") or "")
        return sort_account_rows(
            self._store.list(),
            local_user_id=ident.get("userId") or "",
            local_email=ident.get("email") or "",
            last_id=last_id,
        )

    def get_account_detail(self, account_id: str) -> dict:
        detail = self._store.get_detail(account_id)
        if not detail:
            return {"ok": False, "error": "账号不存在"}
        local = read_fingerprint()
        bound = canonical_machine_id(detail.get("deviceIds"))
        live = canonical_machine_id(local)
        detail["machineMatch"] = bool(bound and live and bound == live)
        detail["localMachineShort"] = short_machine_id(local)
        return {"ok": True, "account": detail}

    def rotate_account_machine(self, account_id: str) -> dict:
        """生成新指纹并绑到该账号。若该号正是本机登录，立刻写入（需 IDE 已关）。"""
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        ident = peek_local_identity()
        is_local = bool(ident.get("userId") and ident["userId"] == account_id)
        if is_local and is_cursor_running():
            return {"ok": False, "error": "请先关闭 IDE，再更换本机正在使用的机器码"}
        ids = generate_fingerprint()
        self._store.set_device_ids(account_id, ids)
        wrote_local = False
        if is_local:
            result = write_fingerprint(ids)
            if not result.get("ok"):
                return {
                    "ok": False,
                    "error": "已保存到启动器，但写入本机失败：" + "；".join(result.get("errors") or []),
                    "account": self._store.get_detail(account_id),
                }
            wrote_local = True
        detail = self._store.get_detail(account_id)
        if not detail:
            return {"ok": False, "error": "绑定失败"}
        live = canonical_machine_id(read_fingerprint())
        bound = canonical_machine_id(detail.get("deviceIds"))
        detail["machineMatch"] = bool(bound and live and bound == live)
        detail["localMachineShort"] = short_machine_id(read_fingerprint())
        return {
            "ok": True,
            "account": detail,
            "wroteLocal": wrote_local,
            "machineIdShort": short_machine_id(ids),
        }

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
        items = self._store.list()
        for idx, acct in enumerate(items):
            if idx > 0:
                time.sleep(0.35)  # 平滑请求间隔，避免单 IP 突发高频探测被官方 WAF 判定号池
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
        # 已是完整 token，不要走 add_text：正则会再抠出内层 JWT，同优先级下顶掉 WS 前缀。
        touched = self._store._ingest([(5, acct["token"])])
        account_id = touched[0]["id"] if touched else None
        email = acct.get("email")
        if account_id and email and "@" in email:
            self._store.set_label(account_id, email)
        access = acct.get("accessToken") or ""
        refresh = acct.get("refreshToken") or ""
        if account_id and refresh and refresh != access:
            self._store.set_refresh_token(account_id, refresh)
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
        refresh = local.get("refreshToken") or ""
        access = local.get("accessToken") or ""
        if refresh and refresh != access:
            self._store.set_refresh_token(account_id, refresh)
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
        identity = peek_local_identity()
        try:
            layout = resolve_install()
            procs = list_cursor_processes()
            total_mb = round(sum(p.get("wsMb") or 0 for p in procs), 1)
            return {
                "ok": True,
                "running": bool(procs),
                "path": str(layout.install_root),
                "executable": str(layout.executable),
                "configuredPath": configured_cursor_path(),
                "version": layout.version,
                "memoryMb": total_mb,
                "processCount": len(procs),
                "localEmail": identity.get("email") or "",
                "localUserId": identity.get("userId") or "",
                "localMachineShort": peek_local_machine_short(),
                "lastAccountId": str(_load_config().get("lastAccountId") or ""),
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "running": is_cursor_running(),
                "localEmail": identity.get("email") or "",
                "localUserId": identity.get("userId") or "",
                "localMachineShort": peek_local_machine_short(),
                "lastAccountId": str(_load_config().get("lastAccountId") or ""),
            }

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

    def model_unlock_status(self) -> dict:
        try:
            return read_model_unlock_status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def model_unlock_apply(self, membership_level: str | None = None, max_only: bool = False) -> dict:
        try:
            return run_model_unlock_apply(membership_level, max_only=max_only)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def model_unlock_set_membership(self, level: str) -> dict:
        try:
            set_membership_setting(level)
            return read_model_unlock_status()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def model_unlock_sync_storage(self, level: str | None = None) -> dict:
        try:
            return sync_storage_membership(level)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def model_unlock_repair(self) -> dict:
        try:
            return run_model_unlock_repair()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def model_unlock_restore(self) -> dict:
        try:
            return run_model_unlock_restore()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def sand_stream_status(self, profile: str = "full", include_subagent: bool = True) -> dict:
        try:
            return read_sand_stream_status(profile=profile, include_subagent=include_subagent)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def sand_stream_apply(self, profile: str = "full", include_subagent: bool = True) -> dict:
        try:
            return run_sand_stream_apply(profile=profile, include_subagent=include_subagent)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def sand_stream_restore(self) -> dict:
        try:
            return run_sand_stream_restore()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def patch_job_progress(self) -> dict:
        with self._job_lock:
            return dict(self._job_progress)

    def sand_stream_apply_start(self, profile: str = "full", include_subagent: bool = True) -> dict:
        return self._start_patch_job(
            "sand-apply",
            lambda cb: run_sand_stream_apply(
                profile=profile, include_subagent=include_subagent, on_progress=cb
            ),
            "正在写入 Grok Bot…",
        )

    def sand_stream_restore_start(self) -> dict:
        return self._start_patch_job(
            "sand-restore",
            lambda cb: run_sand_stream_restore(on_progress=cb),
            "正在还原 Grok Bot…",
        )

    def ctxwin_apply_start(self) -> dict:
        def job(cb):
            steps = [{"id": "host", "label": "extensionHostProcess.js", "status": "run", "detail": ""}]
            cb({"pct": 28, "message": "正在改写 500k 回包…", "steps": steps, "phase": "run"})
            result = run_ctxwin_apply()
            ok = bool(result.get("ok"))
            steps[0]["status"] = "done" if ok else "fail"
            steps[0]["detail"] = "500k 回包" if ok else (result.get("error") or "失败")
            cb({"pct": 92, "message": result.get("message") or "500k 回包已处理", "steps": steps})
            return result

        return self._start_patch_job("ctxwin-apply", job, "正在启用 500k…")

    def ctxwin_restore_start(self) -> dict:
        def job(cb):
            steps = [{"id": "host", "label": "extensionHostProcess.js", "status": "run", "detail": ""}]
            cb({"pct": 28, "message": "正在还原官方回包…", "steps": steps, "phase": "run"})
            result = run_ctxwin_restore()
            ok = bool(result.get("ok"))
            steps[0]["status"] = "done" if ok else "fail"
            steps[0]["detail"] = "已还原" if ok else (result.get("error") or "失败")
            cb({"pct": 92, "message": result.get("message") or "500k 已还原", "steps": steps})
            return result

        return self._start_patch_job("ctxwin-restore", job, "正在还原 500k…")

    def model_unlock_apply_start(self, membership_level: str | None = None, max_only: bool = False) -> dict:
        label = "正在解锁 MAX…" if max_only else "正在完整解锁…"
        detail = "MAX 开关" if max_only else "完整解锁"

        def job(cb):
            steps = [{"id": "wb", "label": "workbench.desktop.main.js", "status": "run", "detail": ""}]
            cb({"pct": 28, "message": label, "steps": steps, "phase": "run"})
            result = run_model_unlock_apply(membership_level, max_only=max_only)
            ok = bool(result.get("ok")) and not result.get("error")
            steps[0]["status"] = "done" if ok else "fail"
            steps[0]["detail"] = detail if ok else (result.get("error") or "失败")
            cb({"pct": 92, "message": result.get("message") or label, "steps": steps})
            return result

        return self._start_patch_job("max-apply", job, label)

    def model_unlock_restore_start(self) -> dict:
        def job(cb):
            steps = [{"id": "wb", "label": "workbench.desktop.main.js", "status": "run", "detail": ""}]
            cb({"pct": 28, "message": "正在还原 MAX…", "steps": steps, "phase": "run"})
            result = run_model_unlock_restore()
            ok = bool(result.get("ok"))
            steps[0]["status"] = "done" if ok else "fail"
            steps[0]["detail"] = "已还原" if ok else (result.get("error") or "失败")
            cb({"pct": 92, "message": result.get("message") or "MAX 已还原", "steps": steps})
            return result

        return self._start_patch_job("max-restore", job, "正在还原 MAX…")

    def _start_patch_job(self, job: str, fn, message: str) -> dict:
        with self._job_lock:
            if self._job_progress.get("busy"):
                return {"ok": False, "error": "已有写入/还原在进行，请稍候"}
            self._job_progress = {
                "busy": True,
                "pct": 2,
                "phase": "start",
                "message": message,
                "job": job,
                "result": None,
                "steps": [],
            }
        threading.Thread(target=self._run_patch_job, args=(job, fn, message), daemon=True).start()
        self._emit_patch_job(self._job_progress)
        return {"ok": True, "started": True, "job": job}

    def _run_patch_job(self, job: str, fn, message: str) -> None:
        def on_progress(payload: dict) -> None:
            with self._job_lock:
                current = dict(self._job_progress)
                current.update(payload)
                current["busy"] = True
                current["job"] = job
                self._job_progress = current
            self._emit_patch_job(self._job_progress)

        try:
            result = fn(on_progress)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        with self._job_lock:
            last_steps = list(self._job_progress.get("steps") or [])
        ok = bool(result.get("ok")) and not result.get("error")
        steps = []
        for item in last_steps:
            row = dict(item)
            if row.get("status") == "run":
                row["status"] = "done" if ok else "fail"
            steps.append(row)
        done = {
            "busy": False,
            "pct": 100 if ok else int(self._job_progress.get("pct") or 0),
            "phase": "done" if ok else "error",
            "message": result.get("message") or result.get("error") or ("完成" if ok else "失败"),
            "job": job,
            "result": result,
            "steps": steps,
        }
        with self._job_lock:
            self._job_progress = done
        self._emit_patch_job(done)

    def _emit_patch_job(self, payload: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('patch-job-progress', {detail: "
                + json.dumps(payload, ensure_ascii=False)
                + "}))"
            )
        except Exception:
            pass

    def crash_diagnose(self) -> dict:
        from launcher.crash_diag import diagnose

        try:
            return diagnose()
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
            saved_proxy = _read_json("proxy.json", {})
            proxy_cfg = ProxyConfig.from_dict(saved_proxy if isinstance(saved_proxy, dict) else {})
            if _load_config().get("disableAutoUpdate", True):
                try:
                    apply_disable_updates(layout.install_root)
                except Exception:
                    pass
            proxy_args: tuple[str, ...] = ()
            proxy_env_extra: dict = {}
            # 启动只带进程参数/环境，绝不在这里写 settings / argv / workbench。
            # 文件写入只走 save_proxy，否则每次「启动 IDE」都会重写 http.noProxy 等键，极易黑屏。
            proxy_ready = isinstance(saved_proxy, dict) and bool(saved_proxy) and proxy_cfg.enabled
            routed = {"ok": True, "skipped": True, "message": "启动不改路由；路由仅在「保存」时代入"}
            hooked = process_proxy_status(layout.install_root)
            if proxy_ready:
                proxy_args = tuple(proxy_chromium_args(proxy_cfg))
                proxy_env_extra = proxy_env(proxy_cfg)

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

                written = write_local_account(
                    item["token"],
                    email,
                    refresh_token=refresh,
                    membership=str(membership) if membership else None,
                    keep_refresh_if_missing=True,
                )
                update_config(lastAccountId=account_id)
                time.sleep(0.4)
            elif light and is_cursor_running():
                close_cursor(layout)
                wait_state_db_ready()

            start_cursor(
                layout,
                extra_args=proxy_args,
                light=bool(light),
                env_extra=proxy_env_extra or None,
            )
            return {
                "ok": True,
                "launched": True,
                "classic": True,
                "light": bool(light),
                "workspace": str(light_workspace_dir()) if light else "",
                "machineMode": mode if account_id else "none",
                "route": routed,
                "processProxy": hooked,
                "hasRefreshToken": bool(written.get("hasRefreshToken")) if account_id else None,
                "wroteRefresh": bool(written.get("wroteRefresh")) if account_id else None,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_cli_config(self) -> dict:
        """获取独立 CLI 的全局配置与安装状态。"""
        from launcher.agent_cli import resolve_agent_cli

        cfg = _load_config()
        agent = resolve_agent_cli()
        return {
            "ok": True,
            "apiKey": str(cfg.get("cliApiKey") or ""),
            "cwd": str(cfg.get("cliCwd") or ""),
            "installed": agent is not None,
            "agentPath": str(agent) if agent else "",
        }

    def save_cli_config(self, api_key: str = "", cwd: str = "") -> dict:
        """保存独立 CLI 的全局默认配置。"""
        from launcher.agent_cli import normalize_api_key, validate_api_key

        key = normalize_api_key(api_key)
        if key:
            try:
                key = validate_api_key(key)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        update_config(cliApiKey=key, cliCwd=(cwd or "").strip())
        return {"ok": True, "apiKey": key, "cwd": (cwd or "").strip()}

    def set_account_api_key(self, account_id: str, api_key: str = "") -> dict:
        """保存或清空账号绑定的 Cursor Agent API Key（crsr_…）。"""
        from launcher.agent_cli import normalize_api_key, validate_api_key

        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        text = normalize_api_key(api_key)
        if text:
            try:
                text = validate_api_key(text)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        updated = self._store.set_api_key(account_id, text)
        if not updated:
            return {"ok": False, "error": "保存失败"}
        return {"ok": True, "account": updated, "hasApiKey": bool(text)}

    def launch_agent_cli(
        self,
        account_id: str | None = None,
        api_key: str | None = None,
        prompt: str | None = None,
        cwd: str | None = None,
        save: bool = False,
    ) -> dict:
        """用 crsr_ API Key 打开新终端并启动 Cursor Agent CLI（支持账号绑定或独立运行）。"""
        from launcher.agent_cli import launch_agent_cli, normalize_api_key, validate_api_key

        key = normalize_api_key(api_key)
        if not key and account_id:
            key = self._store.get_api_key(account_id)
        if not key:
            key = str(_load_config().get("cliApiKey") or "")
        if not key:
            return {"ok": False, "error": "请先填写或保存 crsr_ API Key"}
        try:
            key = validate_api_key(key)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if save:
            if account_id:
                if not self._store.get(account_id):
                    return {"ok": False, "error": "账号不存在"}
                self._store.set_api_key(account_id, key)
            else:
                update_config(cliApiKey=key, cliCwd=(cwd or "").strip())
        target_cwd = (cwd or "").strip() or str(_load_config().get("cliCwd") or "") or None
        result = launch_agent_cli(api_key=key, cwd=target_cwd, prompt=prompt)
        if result.get("ok"):
            if account_id:
                result["accountId"] = account_id
            result["saved"] = bool(save)
        return result

    def get_mcp_servers(self, workspace: str = "") -> dict:
        """获取所有已发现的 MCP 服务列表（全局与工作区）。"""
        from launcher.mcp_manager import list_mcp_servers
        try:
            servers = list_mcp_servers(workspace=workspace.strip() or None)
            return {"ok": True, "servers": servers}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "servers": []}

    def toggle_mcp_server(self, file_path: str, server_name: str, disabled: bool) -> dict:
        """切换 MCP 服务的禁用/启用状态。"""
        from launcher.mcp_manager import toggle_mcp_server
        try:
            return toggle_mcp_server(file_path=file_path, server_name=server_name, disabled=disabled)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_mcp_server(self, file_path: str, server_name: str, cleanup_data: bool = False) -> dict:
        """彻底从配置中移除指定 MCP 服务，带安全备份与可选数据清理。"""
        from launcher.mcp_manager import delete_mcp_server
        try:
            return delete_mcp_server(file_path=file_path, server_name=server_name, cleanup_data=cleanup_data)
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

    def trim_memory(self) -> dict:
        """IDE 运行中也可调用：回收工作集，并尝试删除未被占用的状态库 backup。"""
        try:
            return trim_cursor_memory()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

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
        try:
            layout = resolve_install()
            hook_status = process_proxy_status(layout.install_root)
            patch_status = detect_patch(layout.install_root)
        except Exception:
            hook_status = {"ok": False, "installed": False, "hasDllSource": False}
            patch_status = {"ok": False, "patched": False, "hits": 0, "hasBackup": False}
        return {
            "saved": saved,
            "cursorSettings": current,
            "processProxyStatus": hook_status,
            "patchStatus": patch_status,
            "proxyBackup": proxy_backup_status(),
            "cursorRunning": is_cursor_running(),
        }

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
        """保存代理偏好。

        铁律：Cursor 正在跑时，只写启动器自己的 proxy.json，绝不碰
        settings / argv / workbench。以前一点「保存」就热改 settings，
        会直接把正在用的 IDE 打崩，看起来像「只能重装」。
        """
        cfg = ProxyConfig.from_dict(config)
        _write_json("proxy.json", cfg.to_dict())
        try:
            layout = resolve_install()
            running = is_cursor_running()
            if running:
                return {
                    "ok": True,
                    "config": cfg.to_dict(),
                    "deferred": True,
                    "filesWritten": False,
                    "message": (
                        "已记住代理设置，但 Cursor 还在跑——没有改任何 Cursor 文件。"
                        "请先「关闭 IDE」，再用启动器「启动 IDE」（会带上代理参数）。"
                    ),
                    "route": {"ok": True, "skipped": True, "deferred": True},
                    "processProxyStatus": process_proxy_status(layout.install_root),
                }

            # IDE 已关：清理/写入 settings+argv；网关原生模式绝不改 workbench
            applied = apply_proxy(cfg)
            if not applied.get("ok"):
                return {
                    "ok": False,
                    "error": applied.get("error") or "代理写入失败",
                    "config": cfg.to_dict(),
                }

            routed: dict = {"ok": True, "skipped": True}
            if cfg.enabled:
                routed = {
                    "ok": True,
                    "skipped": True,
                    "message": (
                        "代理只写 settings/argv。模型墙请用 YC 或 Sub2API 扩展面板打补丁，"
                        "启动器不剥 __bajie、不恢复 bajie 备份。"
                    ),
                }

            return {
                "ok": True,
                "config": cfg.to_dict(),
                "applied": applied,
                "filesWritten": True,
                "deferred": False,
                "route": routed,
                "processProxyStatus": process_proxy_status(layout.install_root),
                "message": "已写入 settings/argv；请用启动器启动 IDE",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "config": cfg.to_dict()}

    def apply_proxy_now(self) -> dict:
        if is_cursor_running():
            return {
                "ok": False,
                "error": "Cursor 正在运行，拒绝写入 settings。请先关闭 IDE 再操作。",
            }
        cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))
        try:
            return {"ok": True, **apply_proxy(cfg)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def undo_proxy_injection(self) -> dict:
        """误触急救：还原 settings/argv 快照，尽量恢复 workbench，卸掉 DLL，关掉代理开关。"""
        try:
            layout = resolve_install()
            if is_cursor_running():
                close_cursor(layout)
                wait_state_db_ready()

            steps: list[str] = []
            files = restore_proxy_files()
            if files.get("ok"):
                steps.extend(files.get("restored") or [])
            elif files.get("error") and "没有代理写入备份" not in str(files.get("error")):
                return {"ok": False, "error": files.get("error"), "steps": steps}

            wb = {"ok": True, "skipped": True, "refused": True, "message": "模型墙不由启动器还原"}

            dll = remove_process_proxy(layout.install_root, force=True)
            if dll.get("removed"):
                steps.append("version.dll")

            saved = ProxyConfig.from_dict(_read_json("proxy.json", {}))
            saved.enabled = False
            saved.process_hook = False
            _write_json("proxy.json", saved.to_dict())
            steps.append("proxy.json已关闭")

            return {
                "ok": True,
                "steps": steps,
                "files": files,
                "workbench": wb,
                "dll": dll,
                "config": saved.to_dict(),
                "proxyBackup": proxy_backup_status(),
                "message": (
                    "已尽量还原误触改动：" + "、".join(steps)
                    if steps
                    else "没有可还原的备份（可能从未成功写入过）"
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _with_cursor_closed(self, fn):
        layout = resolve_install()
        closed = False
        if is_cursor_running():
            close_cursor(layout)
            wait_state_db_ready()
            closed = True
        result = fn(layout)
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        result["closed"] = closed
        return result

    def install_process_proxy(self) -> dict:
        cfg = ProxyConfig.from_dict(_read_json("proxy.json", {}))

        def _go(layout):
            return deploy_process_proxy(
                layout.install_root,
                host=cfg.host,
                port=cfg.port,
                proxy_type=cfg.proxy_type,
                dll_source=cfg.dll_source or None,
            )

        try:
            return self._with_cursor_closed(_go)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def uninstall_process_proxy(self) -> dict:
        try:
            return self._with_cursor_closed(lambda layout: emergency_cleanup(layout.install_root))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def restore_process_proxy_files(self) -> dict:
        try:
            return self._with_cursor_closed(lambda layout: restore_process_proxy(layout.install_root))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def restore_workbench(self) -> dict:
        """用备份把网关补丁 workbench 还原回去。已拒绝：模型墙必须由扩展面板打。"""
        try:
            return self._with_cursor_closed(
                lambda layout: apply_bajie_route(layout.install_root, bypass=False)
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def recover_cursor(self) -> dict:
        """黑屏/误触急救：卸 DLL + 还原代理写入快照 + 尽量恢复 workbench。"""
        return self.undo_proxy_injection()

    # ---- 更新 ----

    def get_update_status(self) -> dict:
        try:
            layout = resolve_install()
            root = layout.install_root
        except Exception:
            root = None
        try:
            return read_update_status(root)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def apply_disable_updates(self) -> dict:
        try:
            layout = resolve_install()
            if is_cursor_running():
                return {
                    "ok": False,
                    "error": "请先关闭 Cursor，再禁用更新（需重命名 inno_updater.exe）",
                }
            return apply_disable_updates(layout.install_root)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def restore_updates(self) -> dict:
        try:
            layout = resolve_install()
            if is_cursor_running():
                return {"ok": False, "error": "请先关闭 Cursor"}
            return restore_updates(layout.install_root)
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

    def shortcut_status(self) -> dict:
        try:
            return get_shortcut_status()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "canCreate": False}

    def create_shortcuts(self, desktop: bool = False, start_menu: bool = False) -> dict:
        try:
            return make_shortcut_links(desktop=bool(desktop), start_menu=bool(start_menu))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def refresh_shortcut_icons(self, force: bool = True) -> dict:
        try:
            return refresh_shortcut_icon_links(force=bool(force))
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def skip_shortcut_prompt(self) -> dict:
        try:
            return mark_shortcut_prompted()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main() -> None:
    api = Api()
    geom = load_window_geom()
    window_kwargs = {
        "width": geom["width"],
        "height": geom["height"],
        "min_size": (900, 640),
        "maximized": bool(geom["maximized"]),
        "background_color": "#ECEAE6",
    }
    if geom["x"] is not None and geom["y"] is not None:
        window_kwargs["x"] = geom["x"]
        window_kwargs["y"] = geom["y"]
    window = webview.create_window(
        "Cursor Launcher",
        resource_path(os.path.join("web", "index.html")),
        js_api=api,
        **window_kwargs,
    )
    api._window = window
    attach_window_persistence(window)

    def _kickoff_icon_refresh() -> None:
        if not launcher_is_frozen():
            return
        thread = threading.Thread(
            target=refresh_shortcut_icon_links,
            kwargs={"force": False},
            daemon=True,
            name="shortcut-icon-refresh",
        )
        thread.start()

    try:
        window.events.loaded += lambda: _kickoff_icon_refresh()
    except Exception:
        pass
    webview.start()


if __name__ == "__main__":
    main()
