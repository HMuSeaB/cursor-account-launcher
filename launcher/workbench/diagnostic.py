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
    yc = scan.gateway_hits > 0
    sub2 = getattr(scan, "sub2api_hits", 0) > 0
    if yc and sub2:
        parts.append("YC+Sub2API 叠打")
    elif yc:
        parts.append("YC 原生")
    elif sub2:
        parts.append("Sub2API")
    if scan.max_only:
        parts.append("仅 MAX")
    elif scan.launcher_installed:
        parts.append("完整模型解锁")
    if proxy_pref.get("enabled"):
        mode = "网关原生" if not proxy_pref.get("bypass_gateway") else "改回官方"
        parts.append(f"代理({mode})")
    return " + ".join(parts) if parts else "接近官方"


def classify_extension_name(name: str) -> str:
    """yc / sub2api / other（池鸢 MCP 等）/ 空串（无关）。"""
    key = (name or "").casefold()
    if "sub2api" in key:
        return "sub2api"
    if "cursor-yc" in key or "cursor-gateway" in key:
        return "yc"
    if "bajie-chat" in key or key.startswith("bajie."):
        return "other"
    return ""


def find_gateway_extensions() -> dict[str, list[str]]:
    """本机用户目录里的网关扩展，按 YC / Sub2API / 其它分类。"""
    roots: list[Path] = []
    user = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    roots.append(Path(user) / ".cursor" / "extensions")
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Cursor" / "User" / "extensions")
    grouped: dict[str, list[str]] = {"yc": [], "sub2api": [], "other": []}
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for child in root.iterdir():
                name = child.name
                key = name.casefold()
                if key in seen:
                    continue
                kind = classify_extension_name(name)
                if not kind:
                    continue
                seen.add(key)
                grouped[kind].append(name)
        except OSError:
            continue
    return grouped


def _ext_note(grouped: dict[str, list[str]]) -> str:
    yc = grouped.get("yc") or []
    sub2 = grouped.get("sub2api") or []
    other = grouped.get("other") or []
    bits: list[str] = []
    if yc:
        bits.append("YC 扩展还在（" + "、".join(yc[:2]) + "）")
    else:
        bits.append("没扫到 YC 扩展")
    if sub2:
        bits.append("Sub2API 扩展还在（" + "、".join(sub2[:2]) + "）")
    else:
        bits.append("没扫到 Sub2API 扩展")
    if other:
        bits.append("另有 " + "、".join(other[:2]) + "（不是模型墙）")
    return " ".join(bits) + "。"


def explain_model_wall(
    *,
    gateway_hits: int,
    stripped: bool,
    upgraded: bool,
    previous_version: str = "",
    current_version: str = "",
    has_bajie_backup: bool = False,
    extension_ids: list[str] | None = None,
    extensions: dict[str, list[str]] | None = None,
    updates_blocked: bool = True,
    sub2api_hits: int = 0,
    sub2api_endpoint: str = "",
) -> dict:
    """解释当前走的是 YC 还是 Sub2API，以及为什么模型会变多/变少。"""
    grouped = dict(extensions or {"yc": [], "sub2api": [], "other": []})
    if extension_ids:
        for name in extension_ids:
            kind = classify_extension_name(name) or "other"
            grouped.setdefault(kind, [])
            if name not in grouped[kind]:
                grouped[kind].append(name)

    yc_hits = int(gateway_hits or 0)
    sub2_hits = int(sub2api_hits or 0)
    endpoint = (sub2api_endpoint or "").strip()
    yc_ext = bool(grouped.get("yc"))
    sub2_ext = bool(grouped.get("sub2api"))
    note = _ext_note(grouped)

    yc_block = {
        "present": yc_hits > 0,
        "hits": yc_hits,
        "extensionInstalled": yc_ext,
        "extensions": list(grouped.get("yc") or []),
        "label": "YC 网关原生",
        "means": "更多模型、请求自己的号、可开 Sand",
        "marker": "43111/__bajie",
    }
    sub2_block = {
        "present": sub2_hits > 0,
        "hits": sub2_hits,
        "endpoint": endpoint,
        "extensionInstalled": sub2_ext,
        "extensions": list(grouped.get("sub2api") or []),
        "label": "Sub2API 网关",
        "means": "窄模型墙",
        "marker": "SUB2API_CURSOR_BRIDGE_ENDPOINT",
    }

    def pack(*, active: str, present: bool, cause: str, title: str, why: str, action: str, can_restore: bool) -> dict:
        if not updates_blocked and active in ("none", "both"):
            action += " 自动更新还没拦住，Cursor 再升一次还会把 workbench 盖掉。"
        return {
            "ok": True,
            "present": present,
            "active": active,
            "cause": cause,
            "title": title,
            "why": why,
            "action": action,
            "canRestoreGateway": can_restore,
            "extensionInstalled": yc_ext or sub2_ext,
            "yc": yc_block,
            "sub2api": sub2_block,
        }

    switch_to_sub2 = (
        "要换成 Sub2API 窄墙：先在 YC 面板回滚 Cursor 文件（或不要恢复 bajie 备份），"
        "再在 Sub2API 面板切到网关并打补丁。不要两套一起打，不要重装客户端。"
    )
    switch_to_yc = (
        "要换成 YC 原生（更多模型、自己的号、Sand）：先在 Sub2API 面板恢复 Cursor 文件 / 切直连，"
        "再关 IDE，YC 面板打补丁写入 43111/__bajie。不要重装客户端。"
    )

    if yc_hits > 0 and sub2_hits > 0:
        why = (
            "workbench 里同时有 YC 的 43111/__bajie，和 Sub2API 的 localhost 凭据补丁。"
            "两套会抢 API 地址，模型列表、Sand、Edit 都会乱。"
        )
        if endpoint:
            why += f" Sub2API 当前指向 {endpoint}。"
        why += " " + note
        return pack(
            active="both",
            present=True,
            cause="conflict",
            title="两套网关补丁叠在一起",
            why=why,
            action="同一时间只留一套。" + switch_to_yc + " " + switch_to_sub2,
            can_restore=False,
        )

    if yc_hits > 0:
        why = (
            "workbench 里有 43111/__bajie，请求打到本机 YC bridge（默认 43111）。"
            "这是 YC 原生模式：模型应较多，走自己的号，Sand 也走这套。"
            "列表若突然变少，多半是切到了 Sub2API，或 Agent/Edit/Ask 里的 Edit。"
        )
        if stripped:
            why += " 代理还勾着「改回官方」，保存时会剥掉这套 URL。"
        why += " " + note
        return pack(
            active="yc",
            present=True,
            cause="stripped" if stripped else "",
            title="YC 网关原生（模型多 / 自己的号 / Sand）",
            why=why,
            action="保持 YC 扩展启用，用启动器开 Cursor。" + switch_to_sub2,
            can_restore=False,
        )

    if sub2_hits > 0:
        ep = endpoint or "https://localhost:端口"
        why = (
            f"workbench 里有 Sub2API 凭据补丁，backendUrl 指向 {ep}。"
            "这不是 43111/__bajie，所以旧诊断会误报「模型墙掉了」。"
            "Sub2API 是窄模型墙，列表少是这套的预期，不是 YC 丢了。"
        )
        if stripped:
            why += " 代理「改回官方」只剥 YC 的 __bajie，剥不掉这套凭据。"
        why += " " + note
        return pack(
            active="sub2api",
            present=True,
            cause="stripped" if stripped else "",
            title="Sub2API 网关（窄模型墙）",
            why=why,
            action="列表少是 Sub2API 的正常结果。" + switch_to_yc,
            can_restore=False,
        )

    if stripped:
        cause = "stripped"
        why = (
            "代理选了「没打网关补丁 / 改回官方」。启动器会从 workbench 剥掉 43111/__bajie，"
            "YC 原生立刻没了。Sub2API 凭据若本来就没打上，模型就走官方目录，往往只剩几个。"
        )
        action = (
            "关 IDE → 代理改回「打了补丁，走网关原生」并保存。"
            "然后选定一套：YC 打补丁，或 Sub2API 面板切网关。不要关扩展，更不要重装 Cursor。"
        )
    elif upgraded:
        prev = previous_version or "上一版"
        cur = current_version or "?"
        cause = "upgraded"
        why = (
            f"Cursor 从 v{prev} 升到 v{cur} 时会整文件替换 workbench，"
            "YC 的 43111/__bajie 和 Sub2API 的凭据补丁都会没。关扩展再重装客户端，只会再覆盖一次。"
        )
        action = (
            "保持两个网关扩展都启用（你要哪套就开哪套面板）。关 IDE → "
            + ("有 bajie 备份可先「恢复 YC workbench」，" if has_bajie_backup else "")
            + "再按你要的那套重新打补丁。同时禁用自动更新。"
        )
    elif has_bajie_backup:
        cause = "overwritten"
        why = (
            "以前打过 YC（还有 bajie 备份），但当前 workbench 里既没有 43111/__bajie，也没有 Sub2API 凭据。"
            "常见原因：急救还原、官方安装覆盖、或 IDE 开着时插件没写进去。"
        )
        action = (
            "若要 YC 原生：关 IDE → 「恢复 YC workbench」，再用启动器开。"
            "若要 Sub2API 窄墙：不要恢复这份 bajie 备份，用 Sub2API 面板打补丁。"
            "不要关扩展、不要重装。"
        )
    else:
        cause = "missing"
        why = (
            "当前 workbench 两套网关补丁都没有。模型列表走官方目录，所以会突然变少。"
        )
        action = (
            "不要重装客户端。关 IDE，选定一套再打补丁："
            "YC 原生（多模型 / 自己的号 / Sand）用 YC 面板；"
            "窄墙用 Sub2API 面板。同一时间只打一套。"
        )

    why += " " + note
    return pack(
        active="none",
        present=False,
        cause=cause,
        title="两套网关都没接管 workbench",
        why=why,
        action=action,
        can_restore=bool(has_bajie_backup),
    )


def explain_classic_style(status: dict) -> dict:
    """旧版 IDE 风格（--classic）为什么会忽然没了。"""
    running = bool(status.get("running"))
    lost = bool(status.get("lost"))
    using = status.get("usingClassic")
    why = (
        "启动器开 Cursor 会带 --classic（旧版 IDE 风格）。"
        "从官方图标、开始菜单、或更新器自己重启，都不会带这个参数，界面会忽然变成新版。"
    )
    action = (
        "关掉当前 Cursor，点启动器顶栏「启动 IDE」。"
        "桌面快捷方式请用启动器生成的，不要点官方 Cursor 图标。"
    )
    if not running:
        title = "旧版风格：下次请用启动器开"
        lost = False
    elif lost:
        title = "旧版风格被覆盖了"
    elif using:
        title = "旧版风格还在（--classic）"
        why = "当前进程带了 --classic。"
        action = "以后也用启动器开，避免更新器或官方图标把风格冲掉。"
    else:
        title = "旧版风格无法判定"
        why = "读不到主进程命令行，不能确认有没有 --classic。"
        action = "若界面已经变成新版：关 IDE，用启动器再开。"
    return {
        "ok": True,
        "running": running,
        "usingClassic": using,
        "lost": lost,
        "title": title,
        "why": why,
        "action": action,
        "sampled": int(status.get("sampled") or 0),
    }


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

    if (scan.gateway_hits > 0 or getattr(scan, "sub2api_hits", 0) > 0) and proxy_pref.get("enabled") and proxy_pref.get("bypass_gateway"):
        recs.append(
            {
                "severity": "critical",
                "title": "网关补丁 + 改回官方 API 冲突",
                "action": "代理改选「网关原生」。改回官方会剥 YC 的 __bajie；Sub2API 凭据还在，两套意图拧着",
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

    if scan.gateway_hits > 0 and getattr(scan, "sub2api_hits", 0) == 0 and scan.show_max > 0 and not scan.fetch_spoof:
        recs.append(
            {
                "severity": "ok",
                "title": "当前是 YC 原生 + 仅 MAX",
                "action": "这是多模型 / 自己的号 / Sand 那套。不要再打 Sub2API，也不要点完整解锁或改回官方",
                "detail": f"YC×{scan.gateway_hits} showMax×{scan.show_max}",
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

    # 首次诊断顺带迁移旧备份（幂等）
    try:
        if not (wb_backup.store_root() / ".migrated-legacy").is_file():
            wb_backup.migrate_legacy_into_unified()
    except Exception:
        pass

    from launcher.versioning import (
        LAUNCHER_VERSION,
        cursor_upgrade_status,
        note_cursor_version,
    )

    upgrade = note_cursor_version(layout.version)
    scan = scan_files(files) if files else scan_files([])
    ctxwin = ctxwin_status()
    proxy_pref = _read_proxy_pref()
    proxy_cfg = ProxyConfig.from_dict(proxy_pref)
    proxy_live = read_current_proxy()
    backup = wb_backup.backup_status(files)

    from launcher.bajie_route import detect_patch
    from launcher.cursor_process import classic_launch_status
    from launcher.cursor_update import read_update_status

    update_st = read_update_status(layout.install_root)
    gw_detect = detect_patch(layout.install_root)
    ext_map = find_gateway_extensions()
    wall = explain_model_wall(
        gateway_hits=int(scan.gateway_hits or 0),
        sub2api_hits=int(getattr(scan, "sub2api_hits", 0) or 0),
        sub2api_endpoint=str(getattr(scan, "sub2api_endpoint", "") or ""),
        stripped=bool(proxy_pref.get("enabled") and proxy_pref.get("bypass_gateway")),
        upgraded=bool(upgrade.get("needsRepatch") or upgrade.get("upgraded")),
        previous_version=str(upgrade.get("previousVersion") or ""),
        current_version=str(layout.version or ""),
        has_bajie_backup=bool(backup.get("hasLegacyBajie") or gw_detect.get("hasBackup")),
        extensions=ext_map,
        updates_blocked=bool(update_st.get("settingsBlocked") or update_st.get("innoUpdaterDisabled")),
    )
    classic = explain_classic_style(classic_launch_status())

    profile = _profile_label(scan, proxy_pref)
    recs = _recommendations(
        running=running,
        scan=scan,
        ctxwin=ctxwin,
        proxy_pref=proxy_pref,
        proxy_live=proxy_live,
        backup=backup,
    )
    if wall.get("active") == "both":
        recs.insert(
            0,
            {
                "severity": "warn",
                "title": wall["title"],
                "action": wall["action"],
                "detail": wall["why"],
            },
        )
    elif not wall.get("present"):
        recs.insert(
            0,
            {
                "severity": "warn",
                "title": wall["title"],
                "action": wall["action"],
                "detail": wall["why"],
            },
        )
    if classic.get("lost"):
        recs.insert(
            0,
            {
                "severity": "warn",
                "title": classic["title"],
                "action": classic["action"],
                "detail": classic["why"],
            },
        )
    if upgrade.get("needsRepatch") or upgrade.get("upgraded"):
        recs.insert(
            0,
            {
                "severity": "warn",
                "title": f"Cursor 已升级到 v{layout.version}",
                "action": "关 IDE → 一键补齐（重打 MAX / 500k）",
                "detail": f"上次记录：{upgrade.get('previousVersion') or '—'}",
            },
        )

    from launcher.workbench.autofix import plan_autofix

    report = {
        "ok": True,
        "cursorRunning": running,
        "installRoot": str(layout.install_root),
        "version": layout.version,
        "appRoot": str(app_root),
        "workbenchFiles": [str(p) for p in files],
        "profile": profile,
        "layers": scan.as_hits(),
        "gatewayNative": bool(scan.gateway_hits > 0 and not proxy_cfg.bypass_gateway),
        "gatewayKind": wall.get("active") or "none",
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
        "healthy": not scan.corrupted
        and not any(r["severity"] == "critical" for r in recs)
        and wall.get("active") not in ("none", "both"),
        "launcherVersion": LAUNCHER_VERSION,
        "cursorUpgrade": cursor_upgrade_status(),
        "wall": wall,
        "classic": classic,
        "updateGuard": {
            "blocked": bool(update_st.get("settingsBlocked") or update_st.get("innoUpdaterDisabled")),
            "disableAutoUpdate": bool(update_st.get("disableAutoUpdate")),
        },
    }
    report["autofix"] = plan_autofix(report)
    return report



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
