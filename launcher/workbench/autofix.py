"""推荐组合一键补齐：仅 MAX + 500k + 网关原生代理写入。"""

from __future__ import annotations

from typing import Any

from launcher.cursor_process import is_cursor_running
from launcher.cursor_proxy import ProxyConfig, apply_proxy
from launcher.ctxwin import ctxwin_apply, ctxwin_status
from launcher.model_unlock import apply as model_unlock_apply
from launcher.model_unlock import repair_corrupted
from launcher.versioning import clear_repatch_flag
from launcher.workbench.diagnostic import run_full_diagnostic


def _write_proxy_pref(data: dict) -> None:
    import json
    import os
    from pathlib import Path

    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "proxy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def plan_autofix(diag: dict | None = None) -> dict:
    report = diag or run_full_diagnostic()
    if not report.get("ok"):
        return {"ok": False, "error": report.get("error") or "诊断失败", "steps": []}

    layers = report.get("layers") or {}
    mu = report.get("modelUnlock") or {}
    ctx = report.get("ctxwin") or {}
    pref = ((report.get("proxy") or {}).get("preference")) or {}
    live = ((report.get("proxy") or {}).get("live")) or {}
    running = bool(report.get("cursorRunning"))

    steps: list[dict] = []
    if mu.get("corrupted"):
        steps.append({"id": "repair", "label": "修复黑屏 workbench", "needsClosed": True})
    if not (mu.get("maxOnly") or mu.get("installed")):
        steps.append({"id": "max", "label": "仅解锁 MAX", "needsClosed": True})
    if not ctx.get("patched"):
        steps.append({"id": "ctxwin", "label": "启用 500k 回包", "needsClosed": True})

    proxy_ok = bool(pref.get("enabled") and not pref.get("bypass_gateway"))
    proxy_written = bool(live.get("argvProxyServer") or live.get("httpProxy"))
    if not proxy_ok or (proxy_ok and not proxy_written):
        steps.append(
            {
                "id": "proxy",
                "label": "开启并写入网关原生代理",
                "needsClosed": True,
            }
        )

    if not (layers.get("gateway") or 0) > 0:
        steps.append(
            {
                "id": "gateway",
                "label": "确认外部网关插件",
                "needsClosed": False,
                "manual": True,
            }
        )

    return {
        "ok": True,
        "running": running,
        "ready": len([s for s in steps if not s.get("manual")]) == 0,
        "steps": steps,
        "needsClosed": any(s.get("needsClosed") for s in steps if not s.get("manual")),
        "diagnostic": report,
    }


def run_autofix(*, close_ide: bool = False) -> dict:
    """执行一键补齐。IDE 开着且 close_ide=False 时拒绝。"""
    from launcher.cursor_process import close_cursor, resolve_install
    from launcher.local_cursor import wait_state_db_ready

    if is_cursor_running():
        if not close_ide:
            return {
                "ok": False,
                "error": "请先关闭 IDE，或在确认后让启动器关闭再补齐",
                "running": True,
            }
        try:
            layout = resolve_install()
            close_cursor(layout)
            wait_state_db_ready()
        except Exception as exc:
            return {"ok": False, "error": f"关闭 IDE 失败：{exc}", "running": True}
        if is_cursor_running():
            return {"ok": False, "error": "IDE 仍在运行，请手动退出后再试", "running": True}

    plan = plan_autofix()
    if not plan.get("ok"):
        return plan

    done: list[str] = []
    errors: list[str] = []
    results: dict[str, Any] = {}

    for step in plan.get("steps") or []:
        sid = step["id"]
        if step.get("manual"):
            results[sid] = {"ok": False, "skipped": True, "manual": True}
            continue
        try:
            if sid == "repair":
                res = repair_corrupted()
            elif sid == "max":
                res = model_unlock_apply(None, max_only=True)
            elif sid == "ctxwin":
                res = ctxwin_apply()
            elif sid == "proxy":
                pref = ((plan.get("diagnostic") or {}).get("proxy") or {}).get("preference") or {}
                cfg = ProxyConfig.from_dict(
                    {
                        **pref,
                        "enabled": True,
                        "bypass_gateway": False,
                        "process_hook": False,
                        "proxy_type": pref.get("proxy_type") or "socks5",
                        "host": pref.get("host") or "127.0.0.1",
                        "port": int(pref.get("port") or 7891),
                    }
                )
                _write_proxy_pref(cfg.to_dict())
                res = apply_proxy(cfg)
            else:
                continue
            results[sid] = res
            if res.get("ok"):
                done.append(step["label"])
            else:
                errors.append(f"{step['label']}：{res.get('error') or '失败'}")
        except Exception as exc:
            errors.append(f"{step['label']}：{exc}")
            results[sid] = {"ok": False, "error": str(exc)}

    clear_repatch_flag()
    after = run_full_diagnostic()
    plan_after = plan_autofix(after)
    ok = not errors and plan_after.get("ready")
    return {
        "ok": ok or (bool(done) and not errors),
        "done": done,
        "errors": errors,
        "results": results,
        "planAfter": plan_after,
        "message": (
            "已补齐推荐组合"
            if plan_after.get("ready")
            else (
                "部分完成：" + "、".join(done)
                if done
                else ("失败：" + "；".join(errors) if errors else "无需改动")
            )
        ),
    }
