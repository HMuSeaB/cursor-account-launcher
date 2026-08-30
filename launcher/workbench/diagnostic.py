"""全栈诊断：workbench 各层 + ctxwin + 代理 + 修复建议。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from launcher.ctxwin import ctxwin_status
from launcher.cursor_install import resolve_layout
from launcher.cursor_process import is_cursor_running
from launcher.cursor_proxy import ProxyConfig, proxy_backup_status, read_current_proxy
from launcher.workbench import backup as wb_backup
from launcher.workbench.layers import scan_files


def _read_proxy_pref() -> dict:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "proxy.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _profile_label(scan, proxy_pref: dict) -> str:
    parts: list[str] = []
    if scan.gateway_hits > 0:
        parts.append("网关插件")
    if scan.max_only:
        parts.append("仅 MAX")
    elif scan.launcher_installed:
        parts.append("完整模型解锁")
    if proxy_pref.get("enabled"):
        mode = "网关原生" if not proxy_pref.get("bypass_gateway") else "改回官方"
        parts.append(f"代理({mode})")
    return " + ".join(parts) if parts else "接近官方"


def _recommendations(
    *,
    running: bool,
    scan,
    ctxwin: dict,
    proxy_pref: dict,
    proxy_live: dict,
    backup: dict,
) -> list[dict]:
    recs: list[dict] = []

    if scan.corrupted:
        recs.append(
            {
                "severity": "critical",
                "title": "workbench 异常补丁",
                "action": "关 IDE → 设置里点「修复黑屏」",
                "detail": f"memPro={scan.mem_pro} brokenShowMax={scan.broken_show_max}",
            }
        )

    if scan.gateway_hits > 0 and proxy_pref.get("enabled") and proxy_pref.get("bypass_gateway"):
        recs.append(
            {
                "severity": "critical",
                "title": "网关插件 + 改回官方 API 冲突",
                "action": "代理改选「网关原生」，或还原 workbench 网关补丁",
                "detail": "两种模式会互相覆盖 workbench",
            }
        )

    if not ctxwin.get("patched"):
        recs.append(
            {
                "severity": "warn",
                "title": "500k 回包改写未启用",
                "action": "关 IDE → 设置 → 启用回包改写",
                "detail": ctxwin.get("hostPath") or "",
            }
        )

    if proxy_pref.get("enabled") and not proxy_live.get("argvProxyServer") and not proxy_live.get("httpProxy"):
        recs.append(
            {
                "severity": "warn",
                "title": "代理偏好已开但未写入 Cursor",
                "action": "关 IDE → 保存代理设置，或用启动器启动 IDE",
                "detail": "",
            }
        )

    if not proxy_pref.get("enabled") and proxy_live.get("argvProxyServer"):
        recs.append(
            {
                "severity": "info",
                "title": "argv 里仍有代理，但启动器偏好已关",
                "action": "关 IDE → 保存一次代理（或一键还原误触）以同步",
                "detail": str(proxy_live.get("argvProxyServer")),
            }
        )

    if scan.gateway_hits > 0 and scan.show_max > 0 and not scan.fetch_spoof:
        recs.append(
            {
                "severity": "ok",
                "title": "当前 workbench 组合较安全",
                "action": "保持：网关原生 + 仅 MAX，不要点完整解锁或改回官方",
                "detail": f"gateway×{scan.gateway_hits} showMax×{scan.show_max}",
            }
        )

    if running:
        recs.append(
            {
                "severity": "info",
                "title": "Cursor 正在运行",
                "action": "改 workbench / 500k / 代理文件前须先关 IDE",
                "detail": "",
            }
        )

    if not backup.get("hasOfficial") and not backup.get("hasLegacyModelUnlockClean"):
        recs.append(
            {
                "severity": "warn",
                "title": "尚无 official 干净基线备份",
                "action": "下次关 IDE 后任意安全写入会自动建立；或从官方安装包覆盖 workbench",
                "detail": backup.get("storeRoot") or "",
            }
        )

    return recs


def run_full_diagnostic() -> dict:
    running = is_cursor_running()
    try:
        layout, app_root, files = resolve_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "cursorRunning": running}

    scan = scan_files(files) if files else scan_files([])
    ctxwin = ctxwin_status()
    proxy_pref = _read_proxy_pref()
    proxy_cfg = ProxyConfig.from_dict(proxy_pref)
    proxy_live = read_current_proxy()
    backup = wb_backup.backup_status(files)

    profile = _profile_label(scan, proxy_pref)
    recs = _recommendations(
        running=running,
        scan=scan,
        ctxwin=ctxwin,
        proxy_pref=proxy_pref,
        proxy_live=proxy_live,
        backup=backup,
    )

    return {
        "ok": True,
        "cursorRunning": running,
        "installRoot": str(layout.install_root),
        "version": layout.version,
        "appRoot": str(app_root),
        "workbenchFiles": [str(p) for p in files],
        "profile": profile,
        "layers": scan.as_hits(),
        "gatewayNative": bool(scan.gateway_hits > 0 and not proxy_cfg.bypass_gateway),
        "modelUnlock": {
            "installed": scan.launcher_installed,
            "maxOnly": scan.max_only,
            "corrupted": scan.corrupted,
        },
        "ctxwin": {
            "patched": ctxwin.get("patched"),
            "canApply": ctxwin.get("canApply"),
            "canRestore": ctxwin.get("canRestore"),
            "hostPath": ctxwin.get("hostPath"),
        },
        "proxy": {
            "preference": proxy_pref,
            "live": proxy_live,
            "backup": proxy_backup_status(),
        },
        "backup": backup,
        "recommendations": recs,
        "healthy": not scan.corrupted and not any(r["severity"] == "critical" for r in recs),
    }


def restore_workbench_layer(*, target: str = "auto") -> dict:
    """统一还原 workbench。target: official | latest | legacy-bajie | legacy-model | auto"""
    from launcher.cursor_process import is_cursor_running

    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE", "running": True}

    try:
        layout, app_root, files = resolve_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    if not files:
        return {"ok": False, "error": "找不到 workbench 文件"}

    candidates: list[tuple[str, Path]] = []
    off = wb_backup.official_dir()
    if any((off / p.name).is_file() for p in files):
        candidates.append(("official", off))

    snaps = wb_backup.list_snapshots(limit=1)
    if snaps:
        candidates.append(("latest-snapshot", Path(snaps[0]["path"])))

    legacy_bajie = wb_backup.legacy_dirs()["bajie"]
    if any((legacy_bajie / p.name).is_file() for p in files):
        candidates.append(("legacy-bajie", legacy_bajie))

    legacy_clean = wb_backup.find_best_legacy_clean()
    if legacy_clean:
        candidates.append(("legacy-model-unlock", legacy_clean))

    if not candidates:
        return {"ok": False, "error": "没有可用的 workbench 备份"}

    pick = candidates[0]
    if target != "auto":
        named = {name: path for name, path in candidates}
        key_map = {
            "official": "official",
            "latest": "latest-snapshot",
            "legacy-bajie": "legacy-bajie",
            "legacy-model": "legacy-model-unlock",
        }
        mapped = key_map.get(target, target)
        if mapped not in named:
            return {"ok": False, "error": f"备份 {target} 不存在", "available": list(named.keys())}
        pick = (mapped, named[mapped])

    restored = wb_backup.restore_from_dir(files, pick[1])
    product_src = pick[1] / "product.json"
    product_dst = app_root / "product.json"
    if product_src.is_file() and product_dst.is_file():
        import shutil

        shutil.copy2(product_src, product_dst)
        restored.append("product.json")

    return {
        "ok": True,
        "source": pick[0],
        "sourcePath": str(pick[1]),
        "restored": restored,
        "message": f"已从 {pick[0]} 还原 {', '.join(restored) or '（无变化）'}",
    }
