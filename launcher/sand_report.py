"""本机 Cursor 与 Sand 规则的兼容性报告。

对齐 Claimer 1.2.1 的 patch_report：每条规则给出 已生效 / 可打未打 / 锚点缺失 / 部分，
并列出哪些 JS 包里还有锚点、因而「能改」。不新写 fetch 钩子。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from launcher.sand_stream import (
    AGENT_HOST_ENABLEMENT_RE,
    AGENT_HOST_IDENTITY_ORIGINAL,
    AGENT_HOST_MOVE_EXEC_ORIGINAL,
    ANCHOR_VERSION,
    DIRECT_STREAM_ANCHOR_RE,
    ELIGIBILITY_PREFIXES,
    HEADER_SET_SIMPLE_RE,
    LOCAL_RUNTIME_LOAD_ORIGINAL,
    LOCAL_RUNTIME_LOAD_RE,
    MANAGED_ACTION_ROUTE_ORIGINAL,
    MANAGED_LOCAL_ROUTE_RE,
    MANAGED_SUBAGENT_ROUTE_ORIGINAL,
    MANAGED_SUBAGENT_SESSION_RE,
    MANAGED_TASK_TOOL_ORIGINAL,
    MAX_TOKENS_ORIGINAL,
    MCP_FILESYSTEM_ORIGINAL,
    MOVE_EXEC_GATE_RE,
    PUSH_CONTEXT_TIMEOUT_ORIGINAL_RE,
    RPC_FILE_NAMES,
    RULES_PRESEED_ORIGINAL,
    RULES_SKILLS_EXEC_ORIGINAL,
    SAND_AGENT_HOST_ENABLEMENT_MARKER,
    SAND_AGENT_HOST_IDENTITY_MARKER,
    SAND_AGENT_HOST_MOVE_EXEC_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_ELIGIBILITY_MARKER,
    SAND_HDRFIX_V2_FN,
    SAND_HDRFIX_V2_MARKER,
    SAND_LOCAL_RUNTIME_LOAD_MARKER,
    SAND_MANAGED_ACTION_ROUTE_MARKER,
    SAND_MANAGED_LOCAL_ROUTE_MARKER,
    SAND_MANAGED_SUBAGENT_ROUTE_MARKER,
    SAND_MANAGED_SUBAGENT_SESSION_MARKER,
    SAND_MANAGED_TASK_TOOL_MARKER,
    SAND_MAX_TOKENS_MARKER,
    SAND_MCP_FILESYSTEM_MARKER,
    SAND_MOVE_EXEC_MARKER,
    SAND_PUSH_CONTEXT_TIMEOUT_MARKER,
    SAND_RPC_REWRITE_MARKER,
    SAND_RULES_PRESEED_MARKER,
    SAND_RULES_SKILLS_MARKER,
    SAND_STREAM_WRAP_MARKER,
    SAND_SUBAGENT_COMPLETION_WAKE_MARKER,
    SAND_SUBAGENT_RESUME_MODE_MARKER,
    SAND_TRANSPORT_HOST_MARKER,
    SAND_USER_RULES_MARKER,
    SUBAGENT_COMPLETION_WAKE_RE,
    SUBAGENT_RESUME_MODE_RE,
    USER_RULES_ORIGINAL_RE,
    _TRANSPORT_HOST_SWAPS,
)

STATUS_LABEL = {
    "applied": "已生效",
    "pending": "可打未打",
    "missing": "锚点缺失",
    "partial": "部分生效",
}

MISS_LABEL = {
    "package_absent": "包不存在",
    "shape_changed": "代码变了",
    "feature_absent": "版本没有",
}

MISSING_FIX = f"当前 Cursor 不是 {ANCHOR_VERSION}，或这个构建里压缩名变了，这条打不上。"
PENDING_FIX = "关 IDE 后重新启用即可补上。"
MISS_FIX = {
    "package_absent": f"这个安装里没有对应的包（例如 3.12 没有 cursor-agent-host）。装 Cursor {ANCHOR_VERSION} 后再打。",
    "shape_changed": f"相关代码还在，但和 {ANCHOR_VERSION} 压缩名对不上。不要硬打；升到锚点版本，或等启动器更新锚点。",
    "feature_absent": "这个构建里没有这项功能，不是漏扫。",
}

# 缺失时用来区分「包没了 / 压缩名变了 / 这版根本没有」
RELATED_NEEDLES: dict[str, tuple[str, ...]] = {
    "hdrfixV2": ("x-cursor-client-type",),
    "eligibility": ("adminSettingsService:",),
    "managedLocalRoute": ('reason:"gate-off"', 'runtime:"managed-local"'),
    "localRuntimeLoad": ("agent_host_local_loop",),
    "agentHostIdentity": ('clientIdentity:{clientType:"ide"}', 'clientType:"ide"'),
    "agentHostEnablement": ("_agentHostEnabled=",),
    "directStream": ("return t=>{return n=this,o=void 0,s=function*(){",),
    "transportHost": ("agentBidiTransport",),
    "streamWrap": ("INVARIANT VIOLATION: Transport is undefined for service:",),
    "moveExec": ("createAgentHost),",),
    "taskTool": ("taskToolProps:",),
    "subagentRoute": ("hasUnsupportedRunOptions",),
    "actionRoute": ("action-not-supported", "mode-not-supported"),
    "resumeMode": ("resumeAgentId&&", ".FL.UNSPECIFIED&&!e.readonly"),
    "completionWake": ('source==="interactive-child"',),
    "subagentSession": ("enableEmptyResponseRetry:!0", "nalLoopDetection:!0"),
    "maxTokens": ("resolveExtendedUsage",),
    "rulesSkills": ("registerAgentHostRuntime", "cursorAgentHostEnabled"),
    "mcpFilesystem": ("mcpFileSystemOptions", "enableMCPFileSystem"),
    "userRules": ("injectLocalModeNonFileRules",),
    "rulesPreseed": ("_lastPushedRulesProto",),
    "pushContextTimeout": ("[push_req_context]",),
}

PACKAGE_HINTS: dict[str, tuple[str, ...]] = {
    "managedLocalRoute": ("extensions/cursor-agent-host/",),
    "localRuntimeLoad": ("extensions/cursor-agent-host/",),
    "agentHostIdentity": ("extensions/cursor-agent-host/",),
    "agentHostEnablement": ("extensions/cursor-agent-host/",),
    "moveExec": ("extensions/cursor-agent-host/",),
    "rulesSkills": ("extensions/cursor-agent-host/",),
}


@dataclass(frozen=True)
class RuleSpec:
    key: str
    title: str
    why: str
    layer: str
    markers: tuple[str, ...]
    leftover: Callable[[str], bool]
    required: str = "stream"
    file_names: frozenset[str] | None = None


def _has(needle: str, check: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda c: needle in c and check(c)


def _unmarked(marker: str, check: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda c: marker not in c and check(c)


def _eligibility_leftover(content: str) -> bool:
    if SAND_ELIGIBILITY_MARKER in content:
        return False
    if "adminSettingsService:" not in content:
        return False
    for prefix in ELIGIBILITY_PREFIXES:
        if prefix in content:
            return True
    return bool(
        re.search(
            r"function\s+[A-Za-z0-9_$]+\([A-Za-z0-9_$]+\)\{const\{adminSettingsService:",
            content,
        )
    )


def _hdrfix_leftover(content: str) -> bool:
    if SAND_HDRFIX_V2_FN in content:
        return False
    if SAND_HDRFIX_V2_MARKER in content:
        return True
    if "x-cursor-client-type" not in content:
        return False
    needle = "x-cursor-client-type"
    pos = content.find(needle)
    while pos >= 0:
        window = content[max(0, pos - 220) : pos + 220]
        if SAND_HDRFIX_V2_MARKER not in window and HEADER_SET_SIMPLE_RE.search(window):
            return True
        pos = content.find(needle, pos + len(needle))
    return False


def _transport_leftover(content: str) -> bool:
    if SAND_TRANSPORT_HOST_MARKER in content:
        return False
    return any(old in content for old, _new in _TRANSPORT_HOST_SWAPS)


def _rpc_leftover(content: str) -> bool:
    return SAND_RPC_REWRITE_MARKER not in content


def _stream_wrap_leftover(content: str) -> bool:
    if SAND_STREAM_WRAP_MARKER in content:
        return False
    return "INVARIANT VIOLATION: Transport is undefined for service:" in content


RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        "hdrfixV2",
        "身份分流 HDRFIX_V2",
        "Agent 请求出 ide，其余出 sand，避免和 Agent 路由打架",
        "L0",
        (SAND_HDRFIX_V2_MARKER,),
        _hdrfix_leftover,
    ),
    RuleSpec(
        "eligibility",
        "资格判定短路",
        "跳过客户端里「是否允许 Sand」的管理员设置",
        "L0",
        (SAND_ELIGIBILITY_MARKER,),
        _eligibility_leftover,
    ),
    RuleSpec(
        "managedLocalRoute",
        "本地回路路由",
        "agent-host 走 managed-local，对话计到 Bot 额度",
        "L1",
        (SAND_MANAGED_LOCAL_ROUTE_MARKER,),
        _unmarked(
            SAND_MANAGED_LOCAL_ROUTE_MARKER,
            _has('reason:"gate-off"', lambda c: MANAGED_LOCAL_ROUTE_RE.search(c) is not None),
        ),
    ),
    RuleSpec(
        "localRuntimeLoad",
        "强制加载本地 runtime",
        "无视 agent_host_local_loop 灰度，始终加载本机回路",
        "L1",
        (SAND_LOCAL_RUNTIME_LOAD_MARKER,),
        _unmarked(
            SAND_LOCAL_RUNTIME_LOAD_MARKER,
            lambda c: LOCAL_RUNTIME_LOAD_ORIGINAL in c
            or LOCAL_RUNTIME_LOAD_RE.search(c) is not None,
        ),
    ),
    RuleSpec(
        "agentHostIdentity",
        "agent-host 身份 sand",
        "本地回路发出的推理请求以 sand 客户端身份出现",
        "L1",
        (SAND_AGENT_HOST_IDENTITY_MARKER,),
        lambda c: AGENT_HOST_IDENTITY_ORIGINAL in c,
    ),
    RuleSpec(
        "agentHostEnablement",
        "强制开启 agent-host",
        "workbench 侧无视 cursorAgentHostEnabled 开关",
        "L1",
        (SAND_AGENT_HOST_ENABLEMENT_MARKER,),
        _unmarked(
            SAND_AGENT_HOST_ENABLEMENT_MARKER,
            _has("_agentHostEnabled=", lambda c: AGENT_HOST_ENABLEMENT_RE.search(c) is not None),
        ),
    ),
    RuleSpec(
        "directStream",
        "Grok Bot Direct",
        "hre() 后注入 Joe 会话，绕过官方 RunInference",
        "L2",
        (SAND_DIRECT_STREAM_MARKER,),
        _unmarked(
            SAND_DIRECT_STREAM_MARKER,
            lambda c: DIRECT_STREAM_ANCHOR_RE.search(c) is not None,
        ),
    ),
    RuleSpec(
        "transportHost",
        "传输改到 api2",
        "Stream 走 _backendTransport，不跟 Agent Run 共用 agent 后端",
        "L3",
        (SAND_TRANSPORT_HOST_MARKER,),
        _transport_leftover,
    ),
    RuleSpec(
        "rpcRewrite",
        "请求头伪装 + RPC 改写",
        "fetch/http2/electron 上把 x-cursor-client-type=sand、client-version=0.18.0、x-sand-box-namespace=prod，并把 AgentService/Run 改到 InferenceService/Stream",
        "L4",
        (SAND_RPC_REWRITE_MARKER,),
        _rpc_leftover,
        file_names=RPC_FILE_NAMES,
    ),
    RuleSpec(
        "streamWrap",
        "stream wrap",
        "Connect transport.stream 接到 __sandRewriteStream",
        "L4",
        (SAND_STREAM_WRAP_MARKER,),
        _stream_wrap_leftover,
    ),
    RuleSpec(
        "moveExec",
        "工具执行器",
        "host 自带工具执行，不等 cursor-agent-exec 注册",
        "L5",
        (SAND_MOVE_EXEC_MARKER, SAND_AGENT_HOST_MOVE_EXEC_MARKER),
        _unmarked(
            SAND_MOVE_EXEC_MARKER,
            lambda c: SAND_AGENT_HOST_MOVE_EXEC_MARKER not in c
            and (
                MOVE_EXEC_GATE_RE.search(c) is not None
                or AGENT_HOST_MOVE_EXEC_ORIGINAL in c
            ),
        ),
        required="full",
    ),
    RuleSpec(
        "taskTool",
        "Task V3",
        "子代理继承父模型 / 1M；子代理内不再派 Task",
        "L6",
        (SAND_MANAGED_TASK_TOOL_MARKER,),
        lambda c: MANAGED_TASK_TOOL_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "subagentRoute",
        "子代理路由",
        "放行 subagentTypeName 等 run options",
        "L6",
        (SAND_MANAGED_SUBAGENT_ROUTE_MARKER,),
        lambda c: MANAGED_SUBAGENT_ROUTE_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "actionRoute",
        "Action 白名单",
        "放行 summarize / resume / executePlan 等，去掉 mode-not-supported",
        "L6",
        (SAND_MANAGED_ACTION_ROUTE_MARKER,),
        lambda c: MANAGED_ACTION_ROUTE_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "resumeMode",
        "Resume 改 AGENT",
        "UNSPECIFIED resume 改走 AGENT，避免 mode-not-supported",
        "L6",
        (SAND_SUBAGENT_RESUME_MODE_MARKER,),
        _unmarked(
            SAND_SUBAGENT_RESUME_MODE_MARKER,
            lambda c: SUBAGENT_RESUME_MODE_RE.search(c) is not None,
        ),
        required="l6",
    ),
    RuleSpec(
        "completionWake",
        "子代理完成唤醒",
        "source===subagent 时唤醒父会话",
        "L6",
        (SAND_SUBAGENT_COMPLETION_WAKE_MARKER,),
        _unmarked(
            SAND_SUBAGENT_COMPLETION_WAKE_MARKER,
            lambda c: SUBAGENT_COMPLETION_WAKE_RE.search(c) is not None,
        ),
        required="l6",
    ),
    RuleSpec(
        "subagentSession",
        "子代理会话",
        "useClientSideSubagent 打开客户端子代理",
        "L6",
        (SAND_MANAGED_SUBAGENT_SESSION_MARKER,),
        _unmarked(
            SAND_MANAGED_SUBAGENT_SESSION_MARKER,
            lambda c: MANAGED_SUBAGENT_SESSION_RE.search(c) is not None,
        ),
        required="l6",
    ),
    RuleSpec(
        "maxTokens",
        "maxTokens / 1M",
        "按 context 参数把 maxTokens 提到 1M / 300k / 200k",
        "L7",
        (SAND_MAX_TOKENS_MARKER,),
        lambda c: MAX_TOKENS_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "rulesSkills",
        "Rules / Skills exec",
        "agent-host 开启时仍注册 exec，Rules 才能落地",
        "L7",
        (SAND_RULES_SKILLS_MARKER,),
        lambda c: RULES_SKILLS_EXEC_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "mcpFilesystem",
        "MCP filesystem",
        "强制打开 MCP 文件系统选项",
        "L7",
        (SAND_MCP_FILESYSTEM_MARKER,),
        lambda c: MCP_FILESYSTEM_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "userRules",
        "User Rules",
        "localMode 下仍注入非文件规则",
        "L7",
        (SAND_USER_RULES_MARKER,),
        _unmarked(
            SAND_USER_RULES_MARKER,
            lambda c: USER_RULES_ORIGINAL_RE.search(c) is not None,
        ),
        required="l6",
    ),
    RuleSpec(
        "rulesPreseed",
        "Rules Preseed",
        "首问不等 10s 空规则，_lastPushedRulesProto 预置成 []",
        "L8",
        (SAND_RULES_PRESEED_MARKER,),
        lambda c: RULES_PRESEED_ORIGINAL in c,
        required="l6",
    ),
    RuleSpec(
        "pushContextTimeout",
        "push_req_context 50ms",
        "规则推送超时从 10s 改到 50ms",
        "L8",
        (SAND_PUSH_CONTEXT_TIMEOUT_MARKER,),
        _unmarked(
            SAND_PUSH_CONTEXT_TIMEOUT_MARKER,
            lambda c: PUSH_CONTEXT_TIMEOUT_ORIGINAL_RE.search(c) is not None,
        ),
        required="l6",
    ),
)


def _file_basename(file_name: str) -> str:
    return file_name.replace("\\", "/").rsplit("/", 1)[-1]


def _applies_to(spec: RuleSpec, file_name: str) -> bool:
    if spec.file_names is None:
        return True
    return _file_basename(file_name) in spec.file_names


def _ver_tuple(version: str) -> tuple[int, int, int]:
    nums = [int(part) for part in re.findall(r"\d+", version or "")[:3]]
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def _upgrade_advice(cursor_version: str) -> dict[str, Any]:
    local = (cursor_version or "").strip()
    lv, av = _ver_tuple(local), _ver_tuple(ANCHOR_VERSION)
    if not local:
        relation = "unknown"
        advice = f"没读到 Cursor 版本。Grok Bot 锚点按 {ANCHOR_VERSION}。"
    elif lv < av:
        relation = "older"
        advice = (
            f"本机 v{local} 比锚点 {ANCHOR_VERSION} 旧，3.12 也没有 cursor-agent-host，L1 工具链打不上。"
            f"不要用 IDE 自动更新。正确顺序：禁用自动更新 → 装 Cursor {ANCHOR_VERSION} → 关 IDE → "
            "网关插件重新接管 workbench（模型列表靠它）→ 仅解锁 MAX → 500k → 最后再打 Grok Bot。"
            "不要在旧版上硬打 3.18 的 L1–L7，也不要点完整解锁改模型选择器。"
        )
    elif lv > av:
        relation = "newer"
        advice = (
            f"本机 v{local} 新于锚点 {ANCHOR_VERSION}。压缩名可能已变；看规则是「代码变了」还是「包不存在」。"
            "升级会覆盖 workbench：网关模型墙、MAX、Bot 都要重打。自动更新请关掉。"
        )
    else:
        relation = "match"
        advice = f"版本对上 {ANCHOR_VERSION}。仍显示缺失的才是这台构建里真没有的锚点。"
    return {
        "local": local,
        "anchor": ANCHOR_VERSION,
        "relation": relation,
        "advice": advice,
    }


def _any_needle(files: list[tuple[str, str]], needles: tuple[str, ...]) -> bool:
    if not needles:
        return False
    for _name, content in files:
        if any(needle in content for needle in needles):
            return True
    return False


def _has_package_hint(files: list[tuple[str, str]], hints: tuple[str, ...]) -> bool:
    for name, _content in files:
        path = name.replace("\\", "/")
        if any(hint in path for hint in hints):
            return True
    return False


def _classify_missing(spec: RuleSpec, files: list[tuple[str, str]]) -> str:
    if spec.file_names is not None:
        present = any(_applies_to(spec, name) for name, _content in files)
        if not present:
            return "package_absent"
    hints = PACKAGE_HINTS.get(spec.key) or ()
    needles = RELATED_NEEDLES.get(spec.key) or ()
    found = _any_needle(files, needles)
    if hints and not _has_package_hint(files, hints) and not found:
        return "package_absent"
    if found:
        return "shape_changed"
    return "feature_absent"


def evaluate_file(content: str, file_name: str) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for spec in RULES:
        if not _applies_to(spec, file_name):
            continue
        marked = any(marker in content for marker in spec.markers)
        leftover = False
        try:
            leftover = bool(spec.leftover(content))
        except Exception:
            leftover = False
        out[spec.key] = {"marked": marked, "leftover": leftover}
    return out


def evaluate_compat(
    files: list[tuple[str, str]],
    *,
    cursor_version: str = "",
    include_subagent: bool = True,
    profile: str = "full",
) -> dict[str, Any]:
    """files: (file_name, content)。"""
    per_file: list[dict[str, Any]] = []
    agg: dict[str, dict[str, int]] = {
        spec.key: {"marked": 0, "leftover": 0, "files_marked": [], "files_leftover": []}
        for spec in RULES
    }
    for file_name, content in files:
        hits = evaluate_file(content, file_name)
        can_patch = [key for key, flags in hits.items() if flags["leftover"]]
        patched = [key for key, flags in hits.items() if flags["marked"]]
        per_file.append(
            {
                "name": file_name,
                "present": True,
                "patchable": bool(can_patch or patched),
                "canPatch": can_patch,
                "patched": patched,
            }
        )
        for key, flags in hits.items():
            if flags["marked"]:
                agg[key]["marked"] += 1
                agg[key]["files_marked"].append(file_name)
            if flags["leftover"]:
                agg[key]["leftover"] += 1
                agg[key]["files_leftover"].append(file_name)

    want_full = (profile or "full").strip().lower() != "stream"
    want_l6 = want_full and bool(include_subagent)
    rules_out: list[dict[str, Any]] = []
    for spec in RULES:
        marked = agg[spec.key]["marked"]
        leftover = agg[spec.key]["leftover"]
        if marked and leftover:
            status = "partial"
        elif marked:
            status = "applied"
        elif leftover:
            status = "pending"
        else:
            status = "missing"
        miss_kind = ""
        if status == "missing":
            miss_kind = _classify_missing(spec, files)
        optional = spec.required == "full" and not want_full
        if spec.required == "l6" and not want_l6:
            optional = True
        fix = ""
        if status == "pending":
            fix = PENDING_FIX
        elif status == "partial":
            fix = "有的位置改了、有的还没改。" + PENDING_FIX
        elif status == "missing" and not optional:
            fix = MISS_FIX.get(miss_kind) or MISSING_FIX
        status_label = STATUS_LABEL[status]
        if status == "missing" and miss_kind:
            status_label = MISS_LABEL.get(miss_kind) or status_label
        rules_out.append(
            {
                "key": spec.key,
                "title": spec.title,
                "why": spec.why,
                "layer": spec.layer,
                "required": spec.required,
                "optional": optional,
                "status": status,
                "statusLabel": status_label,
                "missKind": miss_kind,
                "files": list(dict.fromkeys(agg[spec.key]["files_marked"] + agg[spec.key]["files_leftover"])),
                "fix": fix,
            }
        )

    counted = [row for row in rules_out if not row["optional"]]
    applied = [row for row in counted if row["status"] == "applied"]
    missing = [row for row in counted if row["status"] == "missing"]
    pending = [row for row in counted if row["status"] in ("pending", "partial")]
    version = (cursor_version or "").strip()
    version_ok = version.startswith(ANCHOR_VERSION)
    return {
        "cursorVersion": version,
        "anchorVersion": ANCHOR_VERSION,
        "versionOk": version_ok,
        "versionHint": (
            ""
            if version_ok
            else f"锚点按 Cursor {ANCHOR_VERSION}；当前 v{version or '未知'} 可能不全"
        ),
        "summary": {
            "applied": len(applied),
            "required": len(counted),
            "missing": [row["title"] for row in missing],
            "pending": [row["title"] for row in pending],
        },
        "packages": per_file,
        "rules": rules_out,
        "upgrade": _upgrade_advice(version),
        "notes": [
            {
                "title": "请求头伪装",
                "body": (
                    "L4 在 extensionHost 封装 fetch / http2 / electron.net："
                    "推理请求带 sand / 0.18.0 / x-sand-box-namespace=prod。"
                    "AvailableModels / GetServerConfig 保持 ide，避免模型列表被收成 Bot 目录。"
                ),
            },
            {
                "title": "模型列表和 Edit 按钮",
                "body": (
                    "选择器变少、Edit 不对，通常是网关模型墙掉了，或切到了 Agent/Edit/Ask 里的 Edit 模式。"
                    "这不归 Grok Bot 规则管。升级/还原 workbench 后要让网关插件重新接管。"
                    "不要用完整解锁改 picker。"
                ),
            },
        ],
    }


def adjust_compat_scope(
    compat: dict[str, Any],
    *,
    profile: str = "full",
    include_subagent: bool = True,
) -> dict[str, Any]:
    want_full = (profile or "full").strip().lower() != "stream"
    want_l6 = want_full and bool(include_subagent)
    rules = []
    for row in compat.get("rules") or []:
        item = dict(row)
        required = item.get("required") or "stream"
        optional = (required == "full" and not want_full) or (required == "l6" and not want_l6)
        item["optional"] = optional
        if item.get("status") == "missing":
            kind = item.get("missKind") or ""
            item["fix"] = "" if optional else (MISS_FIX.get(kind) or MISSING_FIX)
            if kind:
                item["statusLabel"] = MISS_LABEL.get(kind) or item.get("statusLabel") or "锚点缺失"
        rules.append(item)
    counted = [row for row in rules if not row["optional"]]
    applied = [row for row in counted if row["status"] == "applied"]
    missing = [row for row in counted if row["status"] == "missing"]
    pending = [row for row in counted if row["status"] in ("pending", "partial")]
    out = dict(compat)
    out["rules"] = rules
    out["summary"] = {
        "applied": len(applied),
        "required": len(counted),
        "missing": [row["title"] for row in missing],
        "pending": [row["title"] for row in pending],
    }
    return out


def evaluate_layout_compat(
    layout: Any,
    contents: dict[Path, str],
    *,
    include_subagent: bool = True,
    profile: str = "full",
) -> dict[str, Any]:
    files = [(path.name, text) for path, text in contents.items()]
    return evaluate_compat(
        files,
        cursor_version=getattr(layout, "version", "") or "",
        include_subagent=include_subagent,
        profile=profile,
    )
