"""Sand Stream 模式：client-type 分流 + InferenceService/Stream。

与 model_unlock 分离。补丁核对齐 SandClaimer 1.1.9（条件 Stream、HDRFIX_V2、
transport→api2、move_exec、RPC 改写），L6 对齐 v1.2.6 子代理层。
写入仍走统一备份 + workbench 预检。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from launcher.cursor_install import app_root as install_app_root
from launcher.cursor_process import is_cursor_running, resolve_install
from launcher.workbench.manager import WorkbenchWriteError, sync_product_checksums, write_atomic
from launcher.workbench.preflight import PreflightError, assert_safe

MODULE_VERSION = "1.1.0"
ANCHOR_VERSION = "3.18.9"

SAND_CLIENT_MARKER = "/*SAND_CLIENT_MODE_V1*/"
SAND_CLIENT_EXISTING_MARKER = "/*SAND_CLIENT_EXISTING_V1*/"
SAND_ELIGIBILITY_MARKER = "/*SAND_ELIGIBILITY_MODE_V1*/"
SAND_GLASSFIX_MARKER = "/*SAND_GLASSFIX_V1*/"
SAND_HDRFIX_V2_MARKER = "/*SAND_HDRFIX_V2*/"
SAND_HDRFIX_V2_FN = (
    '(function(r){try{var u=String((r&&r.url)||""),s=String((r&&r.service&&r.service.typeName)||"");'
    'if(/AgentService|\\/agent\\.v1\\./.test(u+s))return"ide"}catch(x){}return"sand"})'
)
HEADER_SET_SIMPLE_RE = re.compile(
    r"([A-Za-z_$][\w$]*)\.header\.set\(\s*([\"'])x-cursor-client-type\2\s*,\s*"
    r"(?:[A-Za-z_$][\w$]*\s*\?\?\s*)?"
    r"([\"'])(?:ide|sand|glass)\3"
    r"(?:/\*SAND[A-Z0-9_]*_V1\*/)*"
    r"\)"
)
HDRFIX_V2_REMOVE_RE = re.compile(
    re.escape(SAND_HDRFIX_V2_FN)
    + r"\([A-Za-z_$][\w$]*\)"
    + re.escape(SAND_HDRFIX_V2_MARKER)
)
SAND_MANAGED_LOCAL_ROUTE_MARKER = "/*SAND_MANAGED_LOCAL_ROUTE_V1*/"
SAND_DIRECT_STREAM_MARKER = "/*SAND_DIRECT_INFERENCE_STREAM_V1*/"
SAND_AGENT_HOST_ENABLEMENT_MARKER = "/*SAND_AGENT_HOST_ENABLEMENT_V1*/"
SAND_LOCAL_RUNTIME_LOAD_MARKER = "/*SAND_LOCAL_RUNTIME_LOAD_V1*/"
SAND_AGENT_HOST_IDENTITY_MARKER = "/*SAND_AGENT_HOST_IDENTITY_V1*/"
SAND_AGENTEXEC_KEEP_MARKER = "/*SAND_AGENTEXEC_KEEP_V1*/"
SAND_AGENT_IDE_MARKER = "/*SAND_AGENT_IDE_V1*/"
SAND_MOVE_EXEC_MARKER = "/*SAND_MOVE_EXEC_V1*/"
SAND_AGENT_HOST_MOVE_EXEC_MARKER = "/*SAND_AGENT_HOST_MOVE_EXEC_V1*/"
SAND_RPC_REWRITE_MARKER = "/*SAND_RPC_REWRITE_V1*/"
SAND_RPC_REWRITE_END = "/*SAND_RPC_REWRITE_END*/"
SAND_STREAM_WRAP_MARKER = "/*SAND_STREAM_WRAP_V1*/"
SAND_TRANSPORT_HOST_MARKER = "/*SAND_TRANSPORT_HOST_V1*/"
SAND_MANAGED_SUBAGENT_ROUTE_MARKER = "/*SAND_MANAGED_SUBAGENT_ROUTE_V1*/"
SAND_MANAGED_SUBAGENT_SESSION_MARKER = "/*SAND_MANAGED_SUBAGENT_SESSION_V1*/"
SAND_MANAGED_TASK_TOOL_MARKER = "/*SAND_MANAGED_TASK_TOOL_V2*/"
LEGACY_SAND_MANAGED_TASK_TOOL_MARKER = "/*SAND_MANAGED_TASK_TOOL_V1*/"
SAND_MANAGED_ACTION_ROUTE_MARKER = "/*SAND_MANAGED_ACTION_ROUTE_V1*/"
SAND_SUBAGENT_RESUME_MODE_MARKER = "/*SAND_SUBAGENT_RESUME_AGENT_MODE_V1*/"
SAND_SUBAGENT_COMPLETION_WAKE_MARKER = "/*SAND_SUBAGENT_COMPLETION_WAKE_V1*/"
LAUNCHER_SAND_MARKER = "/*CURSOR_LAUNCHER_SAND_STREAM_V1*/"
OLD_RPC_PATH = "agent.v1.AgentService/Run"
NEW_RPC_PATH = "aiserver.v1.InferenceService/Stream"

RPC_SNIPPET_RE = re.compile(
    re.escape(SAND_RPC_REWRITE_MARKER) + r"[\s\S]*?" + re.escape(SAND_RPC_REWRITE_END)
)
RPC_SNIPPET_RE_LEGACY = re.compile(
    re.escape(SAND_RPC_REWRITE_MARKER) + r"[\s\S]*?\}\)\(\);"
)
STREAM_WRAP_RESTORE_RE = re.compile(
    r'(throw new Error\("INVARIANT VIOLATION: Transport is undefined for service: "\+\w+\.typeName\);return )'
    r'\(typeof globalThis\.__sandRewriteStream==="function"\?globalThis\.__sandRewriteStream\((\w+)\.transport,'
    r'([^)]+)\):\2\.transport\.stream\(\3\)\)'
    + re.escape(SAND_STREAM_WRAP_MARKER)
)
STREAM_WRAP_INJECT_RE = re.compile(
    r'(throw new Error\("INVARIANT VIOLATION: Transport is undefined for service: "\+(\w+)\.typeName\);return )'
    r'(\2\.transport\.stream\(([^)]+)\))'
)
_TRANSPORT_HOST_SWAPS: tuple[tuple[str, str], ...] = (
    (
        "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[kt.typeName]=s.agentBidiTransport",
        "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[kt.typeName]=this._backendTransport"
        + SAND_TRANSPORT_HOST_MARKER,
    ),
    (
        "this._overrideMethodNameToTransportMap[kt.methods.run.name]=s.agentBidiTransport",
        "this._overrideMethodNameToTransportMap[kt.methods.run.name]=this._backendTransport"
        + SAND_TRANSPORT_HOST_MARKER,
    ),
    (
        "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[l.AgentService.typeName]=e.agentBidiTransport",
        "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[l.AgentService.typeName]=this._backendTransport"
        + SAND_TRANSPORT_HOST_MARKER,
    ),
    (
        "this._overrideMethodNameToTransportMap[l.AgentService.methods.run.name]=e.agentBidiTransport",
        "this._overrideMethodNameToTransportMap[l.AgentService.methods.run.name]=this._backendTransport"
        + SAND_TRANSPORT_HOST_MARKER,
    ),
)

LEGACY_SAND_CLIENT_MARKER = "/*K" + "C_SAND_CLIENT_V1*/"
LEGACY_SAND_ELIGIBILITY_MARKER = "/*K" + "C_SAND_ELIGIBILITY_V1*/"
CLIENT_MARKER_PATTERN = re.escape(SAND_CLIENT_MARKER)
CLIENT_EXISTING_MARKER_PATTERN = re.escape(SAND_CLIENT_EXISTING_MARKER)
ELIGIBILITY_MARKER_PATTERN = re.escape(SAND_ELIGIBILITY_MARKER)
LEGACY_CLIENT_MARKER_PATTERN = re.escape(LEGACY_SAND_CLIENT_MARKER)
LEGACY_ELIGIBILITY_MARKER_PATTERN = re.escape(LEGACY_SAND_ELIGIBILITY_MARKER)
CLIENT_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_CLIENT(?:_(?:MODE|EXISTING))?_V1\*/"
ELIGIBILITY_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_ELIGIBILITY(?:_MODE)?_V1\*/"

TARGET_SPECS: tuple[tuple[str, str | None], ...] = (
    ("out/main.js", None),
    ("out/vs/workbench/api/worker/extensionHostWorkerMain.js", None),
    ("out/vs/workbench/api/node/extensionHostProcess.js", None),
    ("out/vs/workbench/workbench.glass.main.js", None),
    ("out/vs/workbench/workbench.desktop.main.js", None),
    (
        "out/vs/code/electron-utility/alwaysLocalSingleton/alwaysLocalSingletonMain.js",
        None,
    ),
    ("extensions/cursor-always-local/dist/main.js", "cursor-always-local"),
    ("extensions/cursor-local-agent-runtime/dist/main.js", "cursor-local-agent-runtime"),
    ("extensions/cursor-agent-host/dist/main.js", "cursor-agent-host"),
    ("extensions/cursor-agent-exec/dist/main.js", "cursor-agent-exec"),
)
AGENT_HOST_DIST_REL = "extensions/cursor-agent-host/dist"
EXT_HOST_REL = "out/vs/workbench/api/node/extensionHostProcess.js"
WORKBENCH_NAMES = frozenset({"workbench.desktop.main.js", "workbench.glass.main.js"})
RPC_FILE_NAMES = frozenset(
    {"extensionHostProcess.js", "extensionHostWorkerMain.js"}
)

ELIGIBILITY_PREFIXES: tuple[str, ...] = (
    "function r4g(e){const{adminSettingsService:t",
    "function Vj_(t){const{adminSettingsService:e",
    "function inf(e){const{adminSettingsService:t",
    "function HSy(t){const{adminSettingsService:e",
    "function Q_f(e){const{adminSettingsService:t",
    "function BpS(t){const{adminSettingsService:e",
)

MANAGED_LOCAL_ROUTE_RE = re.compile(
    r'try\{return(\(yield \w+\.checkFeatureGate\(\w+\)\)\?'
    r'\{runtime:"managed-local",reason:"eligible"\}:'
    r'\{runtime:"connect",reason:"gate-off"\})\}catch\((\w+)\)'
)
MANAGED_LOCAL_ROUTE_RESTORE_RE = re.compile(
    r'try\{return\{runtime:"managed-local",reason:"sand-client"\}'
    + re.escape(SAND_MANAGED_LOCAL_ROUTE_MARKER)
    + r";"
)
LOCAL_RUNTIME_LOAD_RE = re.compile(
    r"(let (\w+)=!1;try\{\2=await \w+\.cursor\.checkFeatureGate\(\w+\)\}"
    r"catch\(\w+\)\{[^{}]*agent_host_local_loop[^{}]*\})"
    r"(if\(!\2\))"
)
LOCAL_RUNTIME_LOAD_RESTORE_RE = re.compile(
    re.escape(SAND_LOCAL_RUNTIME_LOAD_MARKER) + r"\w+=!0;"
)
LOCAL_RUNTIME_LOAD_ORIGINAL = "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}"
LOCAL_RUNTIME_LOAD_PATCHED = "let t=!0;" + SAND_LOCAL_RUNTIME_LOAD_MARKER + "try{t=!0}"
AGENT_HOST_IDENTITY_ORIGINAL = 'clientIdentity:{clientType:"ide"}'
AGENT_HOST_IDENTITY_PATCHED = (
    'clientIdentity:{clientType:"sand"' + SAND_AGENT_HOST_IDENTITY_MARKER + "}"
)
DIRECT_STREAM_ANCHOR = (
    "function hre(e){return t=>{return n=this,o=void 0,s=function*(){"
)
AGENT_HOST_ENABLEMENT_RE = re.compile(
    r"(this\._agentHostEnabled=)([A-Za-z_$][A-Za-z0-9_$]*)(,)"
)
AGENT_HOST_ENABLEMENT_PATCH_RE = re.compile(
    rf"([A-Za-z_$][A-Za-z0-9_$]*)=!0;"
    rf"{re.escape(SAND_AGENT_HOST_ENABLEMENT_MARKER)}"
    rf"(this\._agentHostEnabled=)\1(,)"
)
AGENTEXEC_SKIP_ORIGINAL = (
    "waitForProviderRegistration(r.ctx.signal);return}await this._agentExecProviderService.waitForProviderRegistration"
)
AGENTEXEC_SKIP_PATCHED = (
    "waitForProviderRegistration(r.ctx.signal);"
    + SAND_AGENTEXEC_KEEP_MARKER
    + "}await this._agentExecProviderService.waitForProviderRegistration"
)
AGENT_IDE_INJECT_RE = re.compile(
    r"(?<!" + re.escape(SAND_AGENT_IDE_MARKER) + r"\);)"
    r"return\{headers:([A-Za-z_$][\w$]*),credentialFingerprint:"
)
AGENT_IDE_REMOVE_RE = re.compile(
    r'[A-Za-z_$][\w$]*\.set\("x-cursor-client-type","ide"'
    + re.escape(SAND_AGENT_IDE_MARKER)
    + r"\);"
)
MOVE_EXEC_GATE_RE = re.compile(
    r"(createAgentHost\),)(\w+)=await Promise\.resolve\("
    r"(\w+\.cursor\.checkFeatureGate\(\w+\))\)\.catch\(\(\)=>!1\)"
)
MOVE_EXEC_GATE_RESTORE_RE = re.compile(
    r"(createAgentHost\),)(\w+)=!0"
    + re.escape(SAND_MOVE_EXEC_MARKER)
    + r"\|\|await Promise\.resolve\("
    r"(\w+\.cursor\.checkFeatureGate\(\w+\))\)\.catch\(\(\)=>!1\)"
)
AGENT_HOST_MOVE_EXEC_ORIGINAL = (
    "p=await Promise.resolve(r.cursor.checkFeatureGate(Us)).catch(()=>!1)"
)
AGENT_HOST_MOVE_EXEC_PATCHED = "p=!0" + SAND_AGENT_HOST_MOVE_EXEC_MARKER

MANAGED_SUBAGENT_ROUTE_ORIGINAL = (
    "hasUnsupportedRunOptions:void 0!==e.runOptions.customSystemPrompt||"
    "void 0!==e.runOptions.harness||"
    "!0===e.runOptions.excludeWorkspaceContext||"
    "void 0!==e.runOptions.subagentTypeName||"
    "void 0!==e.runOptions.parentAgentToolCallId||"
    "!0===e.runOptions.directMetaParentChildSubagent"
)
MANAGED_SUBAGENT_ROUTE_PATCHED = (
    "hasUnsupportedRunOptions:void 0!==e.runOptions.customSystemPrompt||"
    "void 0!==e.runOptions.harness||"
    "!0===e.runOptions.excludeWorkspaceContext"
    + SAND_MANAGED_SUBAGENT_ROUTE_MARKER
    + "||!0===e.runOptions.directMetaParentChildSubagent"
)
MANAGED_ACTION_ROUTE_ORIGINAL = (
    'return"userMessageAction"!==e.actionCase?"action-not-supported":'
    'e.requestedMode!==oe.xyI.AGENT?"mode-not-supported":'
    'e.simulatedUserMessage?"simulated-message-not-supported":'
    'void 0===e.modelId?"model-not-supported":'
    'e.hasModelCredentials?"private-model-not-supported":'
    'e.hasUnsupportedRunOptions?"run-options-not-supported":void 0'
)
MANAGED_ACTION_ROUTE_PATCHED = (
    "return"
    + SAND_MANAGED_ACTION_ROUTE_MARKER
    + '!["userMessageAction","summarizeAction","resumeAction",'
    '"backgroundTaskCompletionAction"].includes(e.actionCase)?'
    '"action-not-supported":'
    '"userMessageAction"===e.actionCase&&'
    'e.requestedMode!==oe.xyI.AGENT?"mode-not-supported":'
    '"userMessageAction"===e.actionCase&&'
    'e.simulatedUserMessage?"simulated-message-not-supported":'
    'void 0===e.modelId?"model-not-supported":'
    'e.hasModelCredentials?"private-model-not-supported":'
    'e.hasUnsupportedRunOptions?"run-options-not-supported":void 0'
)
SUBAGENT_RESUME_MODE_ORIGINAL = (
    "e.resumeAgentId&&e.mode===Mn.FL.UNSPECIFIED&&!e.readonly?"
    "oe.xyI.UNSPECIFIED:"
)
SUBAGENT_RESUME_MODE_PATCHED = (
    "e.resumeAgentId&&e.mode===Mn.FL.UNSPECIFIED&&!e.readonly?"
    + SAND_SUBAGENT_RESUME_MODE_MARKER
    + "oe.xyI.AGENT:"
)
SUBAGENT_COMPLETION_WAKE_RE = re.compile(
    r'([A-Za-z_$][A-Za-z0-9_$]*)\.source==="interactive-child"\|\|'
    r'\1\.payload\.notificationContext==="user_driven_interactive_child"'
)
SUBAGENT_COMPLETION_WAKE_PATCH_RE = re.compile(
    r'([A-Za-z_$][A-Za-z0-9_$]*)\.source==="subagent"'
    + re.escape(SAND_SUBAGENT_COMPLETION_WAKE_MARKER)
    + r'\|\|\1\.source==="interactive-child"\|\|'
    r'\1\.payload\.notificationContext==="user_driven_interactive_child"'
)
MANAGED_SUBAGENT_SESSION_ORIGINAL = (
    "const Cre={enableEmptyResponseRetry:!0,enableGrepBroadGlobGuard:!0,"
    "enableReadToolNegativeOffset:!0,enableSandboxSharedBuildCache:!0,"
    "nalLoopDetection:!0};"
)
MANAGED_SUBAGENT_SESSION_PATCHED = (
    "const Cre={enableEmptyResponseRetry:!0,enableGrepBroadGlobGuard:!0,"
    "enableReadToolNegativeOffset:!0,enableSandboxSharedBuildCache:!0,"
    "nalLoopDetection:!0,useClientSideSubagent:!0"
    + SAND_MANAGED_SUBAGENT_SESSION_MARKER
    + "};"
)
MANAGED_TASK_TOOL_ORIGINAL = (
    "isGenerateImageModelRestricted:!1,taskToolProps:void 0},resolvers:"
)

CORE_HIT_KEYS = (
    "managedLocalRoute",
    "localRuntimeLoad",
    "agentHostEnablement",
    "agentHostIdentity",
)
L4_HIT_KEYS = ("rpcRewrite", "streamWrap", "transportHost")
L5_HIT_KEYS = ("moveExec",)
L6_HIT_KEYS = (
    "taskTool",
    "subagentRoute",
    "subagentSession",
    "actionRoute",
    "resumeMode",
    "completionWake",
)
HIT_LABELS = {
    "hdrfixV2": "L0 HDRFIX_V2（Agent→ide）",
    "managedLocalRoute": "L1 managed-local 路由",
    "localRuntimeLoad": "L1 本地 runtime",
    "agentHostEnablement": "L1 强制 agent-host",
    "agentHostIdentity": "L1 agent-host 身份",
    "directStream": "L2 条件化 Stream",
    "transportHost": "L3 transport→api2",
    "rpcRewrite": "L4 RPC 改写钩子",
    "streamWrap": "L4 stream wrap",
    "moveExec": "L5 工具执行器",
    "taskTool": "L6 Task 工具",
    "subagentRoute": "L6 子代理路由",
    "subagentSession": "L6 子代理会话",
    "actionRoute": "L6 action 白名单",
    "resumeMode": "L6 resume mode",
    "completionWake": "L6 完成唤醒",
}


class SandStreamError(RuntimeError):
    pass


def _compile_client_rules() -> tuple[tuple[str, re.Pattern[str]], ...]:
    marker_guard = rf"(?!{CLIENT_MARKER_GUARD_PATTERN})"
    return (
        (
            "is_glass",
            re.compile(
                rf"(isGlass\s*\?\s*[\"']glass[\"']\s*:\s*)([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
        (
            "object_header",
            re.compile(
                rf"([\"']x-cursor-client-type[\"']\s*:\s*)([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
        (
            "set_header",
            re.compile(
                rf"(header\.set\(\s*[\"']x-cursor-client-type[\"']\s*,\s*"
                rf"[A-Za-z_$][A-Za-z0-9_$.]*\s*(?:\?\?|\|\|)\s*)"
                rf"([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
    )


CLIENT_RULES = _compile_client_rules()


@dataclass
class PatchStats:
    is_glass: int = 0
    object_header: int = 0
    set_header: int = 0
    eligibility: int = 0
    adopted_sand: int = 0
    migrated_client: int = 0
    migrated_eligibility: int = 0
    rpc_rewrite: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0
    move_exec: int = 0
    managed_subagent_route: int = 0
    managed_action_route: int = 0
    subagent_resume_mode: int = 0
    subagent_completion_wake: int = 0
    managed_subagent_session: int = 0
    managed_task_tool: int = 0
    migrated_task_tool: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, item.name) for item in fields(self))


@dataclass
class RemoveStats:
    client_type: int = 0
    eligibility: int = 0
    rpc_rewrite: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0
    move_exec: int = 0
    managed_subagent_route: int = 0
    managed_action_route: int = 0
    subagent_resume_mode: int = 0
    subagent_completion_wake: int = 0
    managed_subagent_session: int = 0
    managed_task_tool: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, item.name) for item in fields(self))


@dataclass(frozen=True)
class SandLayout:
    install_root: Path
    app_root: Path
    product_json: Path
    executable: Path
    target_paths: tuple[Path, ...]
    ext_host_path: Path | None
    version: str


@dataclass
class PatchStatus:
    hits: dict[str, int] = field(default_factory=dict)
    patched_files: tuple[str, ...] = ()
    external_marker_count: int = 0
    launcher_markers: int = 0

    @property
    def installed(self) -> bool:
        return sum(self.hits.values()) + self.launcher_markers > 0

    @property
    def client_markers(self) -> int:
        return int(self.hits.get("client") or 0)

    @property
    def eligibility_markers(self) -> int:
        return int(self.hits.get("eligibility") or 0)

    @property
    def managed_local_route_markers(self) -> int:
        return int(self.hits.get("managedLocalRoute") or 0)

    @property
    def local_runtime_load_markers(self) -> int:
        return int(self.hits.get("localRuntimeLoad") or 0)

    @property
    def direct_stream_markers(self) -> int:
        return int(self.hits.get("directStream") or 0)

    @property
    def agent_host_enablement_markers(self) -> int:
        return int(self.hits.get("agentHostEnablement") or 0)

    @property
    def agent_host_identity_markers(self) -> int:
        return int(self.hits.get("agentHostIdentity") or 0)

    @property
    def stream_mode_installed(self) -> bool:
        return classify_readiness(self.hits, profile="stream")["streamReady"]


def _managed_local_route_sub(match: re.Match[str]) -> str:
    original_ternary = match.group(1)
    catch_var = match.group(2)
    return (
        'try{return{runtime:"managed-local",reason:"sand-client"}'
        + SAND_MANAGED_LOCAL_ROUTE_MARKER
        + ";"
        + original_ternary
        + "}catch("
        + catch_var
        + ")"
    )


def _local_runtime_load_sub(match: re.Match[str]) -> str:
    head = match.group(1)
    var = match.group(2)
    tail_if = match.group(3)
    return head + SAND_LOCAL_RUNTIME_LOAD_MARKER + var + "=!0;" + tail_if


def _move_exec_gate_sub(match: re.Match[str]) -> str:
    return (
        match.group(1)
        + match.group(2)
        + "=!0"
        + SAND_MOVE_EXEC_MARKER
        + "||await Promise.resolve("
        + match.group(3)
        + ").catch(()=>!1)"
    )


def _move_exec_gate_restore(match: re.Match[str]) -> str:
    return (
        match.group(1)
        + match.group(2)
        + "=await Promise.resolve("
        + match.group(3)
        + ").catch(()=>!1)"
    )


def _joe_stream_session_js() -> str:
    return (
        'const n=t.requestedModel;'
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        'r=new Map((n.parameters||[]).map(e=>[e.id,e.value])),'
        's=new Joe(e,n,void 0,void 0).getSession(),'
        'p={getExecutor:e=>new RK(s.getExecutor(e))},'
        'a={vendor:i.includes("grok")?"xai":i.includes("gemini")?"gemini":'
        'i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable")?'
        '"anthropic":i.includes("gpt")||i.includes("codex")?"openai":"unknown",'
        'promptVersion:"latest",reasoningEffort:r.get("effort"),'
        'isGrok45ProductPrompt:i.includes("grok"),'
        'isClaude4x:i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable"),'
        'isFable5:i.includes("fable-5"),'
        'isOpus5:i.includes("opus-5")||i.includes("opus5"),'
        'isOpus48:i.includes("opus-4.8")||i.includes("opus48"),'
        'isOpus46:i.includes("opus-4.6")||i.includes("opus46"),'
        'isOpus45:i.includes("opus-4.5")||i.includes("opus45"),'
        'isSonnet45:i.includes("sonnet-4.5")||i.includes("sonnet45"),'
        'isSonnet4:i.includes("sonnet-4")||i.includes("sonnet4"),'
        'isGemini3:i.includes("gemini-3")||i.includes("gemini3"),'
        'isGpt56:i.includes("gpt-5.6")||i.includes("gpt5.6"),'
        'isGpt55:i.includes("gpt-5.5")||i.includes("gpt5.5"),'
        'isGpt54:i.includes("gpt-5.4")||i.includes("gpt5.4"),'
        'isGpt53Codex:i.includes("gpt-5.3-codex"),'
        'isGpt52Codex:i.includes("gpt-5.2-codex"),'
        'isCodexFamily:i.includes("codex"),isGpt5Family:i.includes("gpt-5")};'
        'return{promptSession:s,promptToolSession:p,attempt:{resolvedModel:cre(n),'
        'supportsSelfSummary:!1,routedModelDisplayName:o,'
        'resolvedModelMetadata:nre(a,o),finish:()=>Promise.resolve()}}'
    )


def _legacy_direct_stream_injection() -> str:
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + 'const n=t.requestedModel;'
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        'r=new Map(n.parameters.map(e=>[e.id,e.value])),'
        's=new Joe(e,n,void 0,void 0).getSession(),'
        'p={getExecutor:e=>new RK(s.getExecutor(e))},'
        'a={vendor:i.includes("grok")?"xai":i.includes("gemini")?"gemini":'
        'i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable")?'
        '"anthropic":i.includes("gpt")||i.includes("codex")?"openai":"unknown",'
        'promptVersion:"latest",reasoningEffort:r.get("effort"),'
        'isGrok45ProductPrompt:i.includes("grok"),'
        'isClaude4x:i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable"),'
        'isFable5:i.includes("fable-5"),'
        'isOpus5:i.includes("opus-5")||i.includes("opus5"),'
        'isOpus48:i.includes("opus-4.8")||i.includes("opus48"),'
        'isOpus46:i.includes("opus-4.6")||i.includes("opus46"),'
        'isOpus45:i.includes("opus-4.5")||i.includes("opus45"),'
        'isSonnet45:i.includes("sonnet-4.5")||i.includes("sonnet45"),'
        'isSonnet4:i.includes("sonnet-4")||i.includes("sonnet4"),'
        'isGemini3:i.includes("gemini-3")||i.includes("gemini3"),'
        'isGpt56:i.includes("gpt-5.6")||i.includes("gpt5.6"),'
        'isGpt55:i.includes("gpt-5.5")||i.includes("gpt5.5"),'
        'isGpt54:i.includes("gpt-5.4")||i.includes("gpt5.4"),'
        'isGpt53Codex:i.includes("gpt-5.3-codex"),'
        'isGpt52Codex:i.includes("gpt-5.2-codex"),'
        'isCodexFamily:i.includes("codex"),isGpt5Family:i.includes("gpt-5")};'
        'return{promptSession:s,promptToolSession:p,attempt:{resolvedModel:cre(n),'
        'supportsSelfSummary:!1,routedModelDisplayName:o,'
        'resolvedModelMetadata:nre(a,o),finish:()=>Promise.resolve()}}}'
    )


def _direct_stream_injection() -> str:
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + 'if(!(e&&typeof e.runInference==="function")){'
        + _joe_stream_session_js()
        + "}}"
    )


DIRECT_STREAM_SNIPPET_RE = re.compile(
    re.escape("{")
    + re.escape(SAND_DIRECT_STREAM_MARKER)
    + r"[\s\S]*?finish:\(\)=>Promise\.resolve\(\)\}+"
)


def _strip_direct_stream_injection(content: str) -> tuple[str, int]:
    if SAND_DIRECT_STREAM_MARKER not in content:
        return content, 0
    total = 0
    for exact in (_direct_stream_injection(), _legacy_direct_stream_injection()):
        count = content.count(exact)
        if count:
            content = content.replace(exact, "")
            total += count
    if SAND_DIRECT_STREAM_MARKER in content:
        content, n = DIRECT_STREAM_SNIPPET_RE.subn("", content)
        total += n
    return content, total


def _strip_rpc_snippets(content: str) -> tuple[str, int]:
    next_content, n1 = RPC_SNIPPET_RE.subn("", content)
    n2 = 0
    if SAND_RPC_REWRITE_MARKER in next_content:
        next_content, n2 = RPC_SNIPPET_RE_LEGACY.subn("", next_content)
    return next_content, n1 + n2


def _load_rpc_js() -> str:
    path = Path(__file__).resolve().parent / "sand_rpc.js"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _rpc_snippet() -> str:
    js = _load_rpc_js()
    if not js:
        return ""
    return SAND_RPC_REWRITE_MARKER + js + SAND_RPC_REWRITE_END


def _managed_task_tool_props(
    custom_subagent_normalizer: str = "()=>[]",
    marker: str = SAND_MANAGED_TASK_TOOL_MARKER,
    model_catalog: str = "new Map([[i,{slug:i}]])",
) -> str:
    return (
        "{"
        + marker
        + "parentRequestedModelName:i,"
        "parentModelParameters:e.requestedModel.parameters,"
        "parentMaxMode:l,"
        "isModelBlocked:()=>!1,"
        "isModelValid:e=>e===i,"
        "requiresMaxMode:()=>!1,"
        "compareModelCosts:()=>0,"
        'subagentModelForcePolicy:"none",'
        "requireServerSideSubagent:!1,"
        f"subagentModels:{{modelsBySlug:{model_catalog}}},"
        f"normalizeCustomSubagents:{custom_subagent_normalizer},"
        "getTaskToolConfig:async()=>({})"
        "}"
    )


def _managed_task_tool_patched() -> str:
    return (
        "isGenerateImageModelRestricted:!1,taskToolProps:"
        "void 0!==e.runOptions.subagentTypeName?void 0:"
        + _managed_task_tool_props()
        + "},resolvers:"
    )


def _managed_task_tool_patched_v124() -> str:
    return (
        "isGenerateImageModelRestricted:!1,taskToolProps:"
        + _managed_task_tool_props(
            "e=>e",
            LEGACY_SAND_MANAGED_TASK_TOOL_MARKER,
            "new Map",
        )
        + "},resolvers:"
    )


def _managed_task_tool_patched_v125() -> str:
    return (
        "isGenerateImageModelRestricted:!1,taskToolProps:"
        "void 0!==e.runOptions.subagentTypeName?void 0:"
        + _managed_task_tool_props(
            marker=LEGACY_SAND_MANAGED_TASK_TOOL_MARKER,
            model_catalog="new Map",
        )
        + "},resolvers:"
    )


def _replace_count(content: str, old: str, new: str) -> tuple[str, int]:
    if not old or old not in content:
        return content, 0
    return content.replace(old, new), content.count(old)


def _strip_l6(content: str, stats: RemoveStats | None = None) -> str:
    next_content, n = _replace_count(
        content, MANAGED_SUBAGENT_ROUTE_PATCHED, MANAGED_SUBAGENT_ROUTE_ORIGINAL
    )
    if stats:
        stats.managed_subagent_route += n
    next_content, n = _replace_count(
        next_content, MANAGED_ACTION_ROUTE_PATCHED, MANAGED_ACTION_ROUTE_ORIGINAL
    )
    if stats:
        stats.managed_action_route += n
    next_content, n = _replace_count(
        next_content, SUBAGENT_RESUME_MODE_PATCHED, SUBAGENT_RESUME_MODE_ORIGINAL
    )
    if stats:
        stats.subagent_resume_mode += n

    def disable_wake(match: re.Match[str]) -> str:
        variable = match.group(1)
        return (
            variable
            + '.source==="interactive-child"||'
            + variable
            + '.payload.notificationContext==="user_driven_interactive_child"'
        )

    next_content, n = SUBAGENT_COMPLETION_WAKE_PATCH_RE.subn(disable_wake, next_content)
    if stats:
        stats.subagent_completion_wake += n
    next_content, n = _replace_count(
        next_content, MANAGED_SUBAGENT_SESSION_PATCHED, MANAGED_SUBAGENT_SESSION_ORIGINAL
    )
    if stats:
        stats.managed_subagent_session += n
    for patched in (
        _managed_task_tool_patched(),
        _managed_task_tool_patched_v125(),
        _managed_task_tool_patched_v124(),
    ):
        next_content, n = _replace_count(next_content, patched, MANAGED_TASK_TOOL_ORIGINAL)
        if stats:
            stats.managed_task_tool += n
    return next_content


def _strip_move_exec(content: str, stats: RemoveStats | None = None) -> str:
    next_content, n = MOVE_EXEC_GATE_RESTORE_RE.subn(_move_exec_gate_restore, content)
    if stats:
        stats.move_exec += n
    next_content, n = _replace_count(
        next_content, AGENT_HOST_MOVE_EXEC_PATCHED, AGENT_HOST_MOVE_EXEC_ORIGINAL
    )
    if stats:
        stats.move_exec += n
    return next_content


def _apply_l6(content: str, stats: PatchStats) -> str:
    next_content, n = _replace_count(
        content, MANAGED_SUBAGENT_ROUTE_ORIGINAL, MANAGED_SUBAGENT_ROUTE_PATCHED
    )
    stats.managed_subagent_route += n
    next_content, n = _replace_count(
        next_content, MANAGED_ACTION_ROUTE_ORIGINAL, MANAGED_ACTION_ROUTE_PATCHED
    )
    stats.managed_action_route += n
    next_content, n = _replace_count(
        next_content, SUBAGENT_RESUME_MODE_ORIGINAL, SUBAGENT_RESUME_MODE_PATCHED
    )
    stats.subagent_resume_mode += n
    if SAND_SUBAGENT_COMPLETION_WAKE_MARKER not in next_content:

        def enable_wake(match: re.Match[str]) -> str:
            variable = match.group(1)
            return (
                variable
                + '.source==="subagent"'
                + SAND_SUBAGENT_COMPLETION_WAKE_MARKER
                + "||"
                + match.group(0)
            )

        next_content, n = SUBAGENT_COMPLETION_WAKE_RE.subn(enable_wake, next_content)
        stats.subagent_completion_wake += n
    next_content, n = _replace_count(
        next_content, MANAGED_SUBAGENT_SESSION_ORIGINAL, MANAGED_SUBAGENT_SESSION_PATCHED
    )
    stats.managed_subagent_session += n
    for previous in (_managed_task_tool_patched_v125(), _managed_task_tool_patched_v124()):
        next_content, n = _replace_count(next_content, previous, _managed_task_tool_patched())
        stats.migrated_task_tool += n
    next_content, n = _replace_count(
        next_content, MANAGED_TASK_TOOL_ORIGINAL, _managed_task_tool_patched()
    )
    stats.managed_task_tool += n
    return next_content


def _normalize_profile(profile: str | None) -> str:
    value = (profile or "full").strip().lower()
    return "stream" if value == "stream" else "full"


def apply_patch_to_content(
    content: str,
    profile: str = "full",
    include_subagent: bool = True,
    inject_rpc: bool = False,
) -> tuple[str, PatchStats]:
    stats = PatchStats()
    next_content = content
    want_full = _normalize_profile(profile) == "full"
    want_l6 = want_full and bool(include_subagent)

    if not want_l6:
        next_content = _strip_l6(next_content)
    if not want_full:
        next_content = _strip_move_exec(next_content)

    next_content, rpc_stripped = _strip_rpc_snippets(next_content)
    stats.rpc_rewrite += rpc_stripped

    legacy_client_re = re.compile(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}")
    next_content, stats.migrated_client = legacy_client_re.subn(
        lambda m: m.group(1) + "sand" + m.group(1) + SAND_CLIENT_MARKER,
        next_content,
    )
    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    stats.migrated_eligibility = next_content.count(legacy_eligibility)
    next_content = next_content.replace(
        legacy_eligibility,
        "return!1;" + SAND_ELIGIBILITY_MARKER,
    )

    def _smart_header(match: re.Match[str]) -> str:
        stats.set_header += 1
        obj = match.group(1)
        q = match.group(2)
        return (
            f"{obj}.header.set({q}x-cursor-client-type{q},"
            f"{SAND_HDRFIX_V2_FN}({obj}){SAND_HDRFIX_V2_MARKER})"
        )

    next_content = HEADER_SET_SIMPLE_RE.sub(_smart_header, next_content)

    for key, rule in CLIENT_RULES:

        def replace_client(match: re.Match[str], stat_key: str = key) -> str:
            current = match.group(3)
            setattr(stats, stat_key, getattr(stats, stat_key) + 1)
            marker = (
                SAND_CLIENT_EXISTING_MARKER if current == "sand" else SAND_CLIENT_MARKER
            )
            if current == "sand":
                stats.adopted_sand += 1
            return match.group(1) + match.group(2) + "sand" + match.group(2) + marker

        next_content = rule.sub(replace_client, next_content)

    glass_true_pattern = re.compile(r'(isGlass\?)(["\'])glass\2(:)(["\'])(?:ide|sand)\4')

    def _fix_glass_true(match: re.Match[str]) -> str:
        stats.is_glass += 1
        q1 = match.group(2)
        q2 = match.group(4)
        return f"{match.group(1)}{q1}sand{q1}{SAND_GLASSFIX_MARKER}{match.group(3)}{q2}sand{q2}"

    next_content = glass_true_pattern.sub(_fix_glass_true, next_content)

    eligibility_pattern = re.compile(
        r"(function\s+[A-Za-z0-9_$]+\([A-Za-z0-9_$]+\)\{)(const\{adminSettingsService:)"
    )

    def inject_eligibility(match: re.Match[str]) -> str:
        stats.eligibility += 1
        return match.group(1) + "return!1;" + SAND_ELIGIBILITY_MARKER + match.group(2)

    next_content = eligibility_pattern.sub(inject_eligibility, next_content)
    for prefix in ELIGIBILITY_PREFIXES:
        if SAND_ELIGIBILITY_MARKER in prefix:
            continue
        if prefix not in next_content:
            continue
        if "return!1;" + SAND_ELIGIBILITY_MARKER in next_content and prefix.replace(
            "{const{adminSettingsService:",
            "{return!1;" + SAND_ELIGIBILITY_MARKER + "const{adminSettingsService:",
        ) in next_content:
            continue
        patched_prefix = prefix.replace(
            "{const{adminSettingsService:",
            "{return!1;" + SAND_ELIGIBILITY_MARKER + "const{adminSettingsService:",
        )
        count = next_content.count(prefix)
        if count and patched_prefix not in next_content:
            next_content = next_content.replace(prefix, patched_prefix)
            stats.eligibility += count

    def _inject_agent_ide(match: re.Match[str]) -> str:
        stats.rpc_rewrite += 1
        ident = match.group(1)
        return (
            f'{ident}.set("x-cursor-client-type","ide"{SAND_AGENT_IDE_MARKER});'
            f"return{{headers:{ident},credentialFingerprint:"
        )

    next_content = AGENT_IDE_INJECT_RE.sub(_inject_agent_ide, next_content)

    next_content, route_count = MANAGED_LOCAL_ROUTE_RE.subn(
        _managed_local_route_sub, next_content
    )
    stats.managed_local_route += route_count

    next_content, runtime_load_count = LOCAL_RUNTIME_LOAD_RE.subn(
        _local_runtime_load_sub, next_content
    )
    stats.local_runtime_load += runtime_load_count
    if (
        stats.local_runtime_load == 0
        and SAND_LOCAL_RUNTIME_LOAD_MARKER not in next_content
        and LOCAL_RUNTIME_LOAD_ORIGINAL in next_content
    ):
        next_content, n = _replace_count(
            next_content, LOCAL_RUNTIME_LOAD_ORIGINAL, LOCAL_RUNTIME_LOAD_PATCHED
        )
        stats.local_runtime_load += n

    identity_count = next_content.count(AGENT_HOST_IDENTITY_ORIGINAL)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_ORIGINAL,
            AGENT_HOST_IDENTITY_PATCHED,
        )
        stats.agent_host_identity += identity_count

    if want_full:
        next_content, move_exec_count = MOVE_EXEC_GATE_RE.subn(
            _move_exec_gate_sub, next_content
        )
        stats.move_exec += move_exec_count
        if (
            stats.move_exec == 0
            and SAND_MOVE_EXEC_MARKER not in next_content
            and SAND_AGENT_HOST_MOVE_EXEC_MARKER not in next_content
        ):
            next_content, n = _replace_count(
                next_content, AGENT_HOST_MOVE_EXEC_ORIGINAL, AGENT_HOST_MOVE_EXEC_PATCHED
            )
            stats.move_exec += n

    conditional_injection = _direct_stream_injection()
    if conditional_injection not in next_content:
        next_content, _stripped = _strip_direct_stream_injection(next_content)
        if (
            SAND_DIRECT_STREAM_MARKER not in next_content
            and DIRECT_STREAM_ANCHOR in next_content
        ):
            next_content = next_content.replace(
                DIRECT_STREAM_ANCHOR,
                DIRECT_STREAM_ANCHOR + conditional_injection,
                1,
            )
            stats.direct_stream += 1

    if SAND_AGENT_HOST_ENABLEMENT_MARKER not in next_content:

        def enable_agent_host(match: re.Match[str]) -> str:
            variable = match.group(2)
            return (
                variable
                + "=!0;"
                + SAND_AGENT_HOST_ENABLEMENT_MARKER
                + match.group(1)
                + variable
                + match.group(3)
            )

        next_content, agent_host_count = AGENT_HOST_ENABLEMENT_RE.subn(
            enable_agent_host,
            next_content,
            count=1,
        )
        stats.agent_host_enablement += agent_host_count
    if AGENTEXEC_SKIP_PATCHED in next_content:
        next_content = next_content.replace(AGENTEXEC_SKIP_PATCHED, AGENTEXEC_SKIP_ORIGINAL)

    if want_l6:
        next_content = _apply_l6(next_content, stats)

    for old, new in _TRANSPORT_HOST_SWAPS:
        if new in next_content:
            continue
        next_content, n = _replace_count(next_content, old, new)
        stats.rpc_rewrite += n

    if SAND_STREAM_WRAP_MARKER not in next_content:

        def wrap_stream(match: re.Match[str]) -> str:
            ident = match.group(2)
            args = match.group(4)
            stats.rpc_rewrite += 1
            return (
                match.group(1)
                + f'(typeof globalThis.__sandRewriteStream==="function"?'
                f"globalThis.__sandRewriteStream({ident}.transport,{args}):"
                f"{ident}.transport.stream({args}))"
                + SAND_STREAM_WRAP_MARKER
            )

        next_content = STREAM_WRAP_INJECT_RE.sub(wrap_stream, next_content)

    if inject_rpc:
        snippet = _rpc_snippet()
        if snippet and SAND_RPC_REWRITE_MARKER not in next_content:
            next_content = snippet + next_content
            stats.rpc_rewrite += 1

    return next_content, stats


def remove_patch_from_content(content: str) -> tuple[str, RemoveStats]:
    stats = RemoveStats()
    next_content, rpc_snip_count = _strip_rpc_snippets(content)
    stats.rpc_rewrite += rpc_snip_count
    if NEW_RPC_PATH in next_content:
        n = next_content.count(NEW_RPC_PATH)
        next_content = next_content.replace(NEW_RPC_PATH, OLD_RPC_PATH)
        stats.rpc_rewrite += n

    def _restore_proxy_stream(match: re.Match[str]) -> str:
        stats.rpc_rewrite += 1
        return f"{match.group(1)}{match.group(2)}.transport.stream({match.group(3)})"

    next_content = STREAM_WRAP_RESTORE_RE.sub(_restore_proxy_stream, next_content)
    for old, new in _TRANSPORT_HOST_SWAPS:
        if new in next_content:
            next_content = next_content.replace(new, old)
            stats.rpc_rewrite += 1
    next_content, agent_ide_count = AGENT_IDE_REMOVE_RE.subn("", next_content)
    stats.rpc_rewrite += agent_ide_count

    if LAUNCHER_SAND_MARKER in next_content:
        next_content = next_content.replace(LAUNCHER_SAND_MARKER, "", 1)

    legacy_client_re = re.compile(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}")
    next_content, legacy_client_count = legacy_client_re.subn(
        lambda m: m.group(1) + "ide" + m.group(1),
        next_content,
    )
    stats.client_type += legacy_client_count
    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    legacy_eligibility_count = next_content.count(legacy_eligibility)
    next_content = next_content.replace(legacy_eligibility, "")
    stats.eligibility += legacy_eligibility_count

    client_re = re.compile(rf"([\"'])sand\1{CLIENT_MARKER_PATTERN}")
    existing_re = re.compile(rf"([\"'])sand\1{CLIENT_EXISTING_MARKER_PATTERN}")

    def remove_client(match: re.Match[str]) -> str:
        stats.client_type += 1
        return match.group(1) + "ide" + match.group(1)

    next_content = client_re.sub(remove_client, next_content)
    next_content, existing_count = existing_re.subn(
        lambda m: m.group(1) + "sand" + m.group(1),
        next_content,
    )
    stats.client_type += existing_count
    glassfix_re = re.compile(r"([\"'])sand\1" + re.escape(SAND_GLASSFIX_MARKER))
    next_content, glassfix_count = glassfix_re.subn(
        lambda m: m.group(1) + "glass" + m.group(1),
        next_content,
    )
    stats.client_type += glassfix_count
    next_content, hdrfix_v2_count = HDRFIX_V2_REMOVE_RE.subn('"ide"', next_content)
    stats.client_type += hdrfix_v2_count

    eligibility_re = re.compile(rf"return!1;{ELIGIBILITY_MARKER_PATTERN}")
    next_content, eligibility_count = eligibility_re.subn("", next_content)
    stats.eligibility += eligibility_count

    next_content, route_count = MANAGED_LOCAL_ROUTE_RESTORE_RE.subn(
        "try{return", next_content
    )
    stats.managed_local_route += route_count
    next_content, runtime_load_count = LOCAL_RUNTIME_LOAD_RESTORE_RE.subn(
        "", next_content
    )
    stats.local_runtime_load += runtime_load_count
    next_content, n = _replace_count(
        next_content, LOCAL_RUNTIME_LOAD_PATCHED, LOCAL_RUNTIME_LOAD_ORIGINAL
    )
    stats.local_runtime_load += n

    identity_count = next_content.count(AGENT_HOST_IDENTITY_PATCHED)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_PATCHED,
            AGENT_HOST_IDENTITY_ORIGINAL,
        )
        stats.agent_host_identity += identity_count

    next_content = _strip_move_exec(next_content, stats)
    next_content, direct_count = _strip_direct_stream_injection(next_content)
    stats.direct_stream += direct_count
    next_content, agent_host_count = AGENT_HOST_ENABLEMENT_PATCH_RE.subn(
        lambda m: m.group(2) + m.group(1) + m.group(3),
        next_content,
    )
    stats.agent_host_enablement += agent_host_count
    if AGENTEXEC_SKIP_PATCHED in next_content:
        next_content = next_content.replace(AGENTEXEC_SKIP_PATCHED, AGENTEXEC_SKIP_ORIGINAL)
    next_content = _strip_l6(next_content, stats)

    residual_marker_re = re.compile(
        r'(["\'])(?:ide|sand|glass)\1((?:/\*SAND[A-Z0-9_]*_V1\*/)+)'
    )

    def _collapse_residual(match: re.Match[str]) -> str:
        quote = match.group(1)
        first_match = re.match(r"/\*(SAND[A-Z0-9_]*_V1)\*/", match.group(2))
        first = first_match.group(1) if first_match else ""
        if "EXISTING" in first:
            value = "sand"
        elif "GLASSFIX" in first:
            value = "glass"
        else:
            value = "ide"
        return f"{quote}{value}{quote}"

    next_content, residual_count = residual_marker_re.subn(_collapse_residual, next_content)
    stats.client_type += residual_count
    return next_content, stats


def inspect_content_hits(content: str) -> dict[str, int]:
    return {
        "client": content.count(SAND_CLIENT_MARKER) + content.count(SAND_CLIENT_EXISTING_MARKER),
        "eligibility": content.count(SAND_ELIGIBILITY_MARKER),
        "hdrfixV2": content.count(SAND_HDRFIX_V2_MARKER),
        "managedLocalRoute": content.count(SAND_MANAGED_LOCAL_ROUTE_MARKER),
        "localRuntimeLoad": content.count(SAND_LOCAL_RUNTIME_LOAD_MARKER),
        "directStream": content.count(SAND_DIRECT_STREAM_MARKER),
        "agentHostEnablement": content.count(SAND_AGENT_HOST_ENABLEMENT_MARKER),
        "agentHostIdentity": content.count(SAND_AGENT_HOST_IDENTITY_MARKER),
        "moveExec": content.count(SAND_MOVE_EXEC_MARKER)
        + content.count(SAND_AGENT_HOST_MOVE_EXEC_MARKER),
        "rpcRewrite": content.count(SAND_RPC_REWRITE_MARKER),
        "streamWrap": content.count(SAND_STREAM_WRAP_MARKER),
        "transportHost": content.count(SAND_TRANSPORT_HOST_MARKER),
        "taskTool": content.count(SAND_MANAGED_TASK_TOOL_MARKER),
        "subagentRoute": content.count(SAND_MANAGED_SUBAGENT_ROUTE_MARKER),
        "subagentSession": content.count(SAND_MANAGED_SUBAGENT_SESSION_MARKER),
        "actionRoute": content.count(SAND_MANAGED_ACTION_ROUTE_MARKER),
        "resumeMode": content.count(SAND_SUBAGENT_RESUME_MODE_MARKER),
        "completionWake": content.count(SAND_SUBAGENT_COMPLETION_WAKE_MARKER),
        "launcherMarker": content.count(LAUNCHER_SAND_MARKER),
    }


def classify_readiness(
    hits: dict[str, int],
    profile: str = "full",
    include_subagent: bool = True,
) -> dict[str, Any]:
    profile = _normalize_profile(profile)
    want_l6 = profile == "full" and bool(include_subagent)
    missing: list[str] = []
    for key in CORE_HIT_KEYS:
        if int(hits.get(key) or 0) <= 0:
            missing.append(key)
    if int(hits.get("hdrfixV2") or 0) <= 0:
        missing.append("hdrfixV2")
    for key in L4_HIT_KEYS:
        if int(hits.get(key) or 0) <= 0:
            missing.append(key)
    if profile == "full":
        for key in L5_HIT_KEYS:
            if int(hits.get(key) or 0) <= 0:
                missing.append(key)
    if want_l6:
        for key in L6_HIT_KEYS:
            if int(hits.get(key) or 0) <= 0:
                missing.append(key)
    stream_ready = all(int(hits.get(key) or 0) > 0 for key in CORE_HIT_KEYS)
    tools_ready = stream_ready and int(hits.get("moveExec") or 0) > 0
    full_ready = tools_ready and all(int(hits.get(key) or 0) > 0 for key in L6_HIT_KEYS)
    core_missing = [key for key in CORE_HIT_KEYS if int(hits.get(key) or 0) <= 0]
    return {
        "streamReady": stream_ready,
        "toolsReady": tools_ready,
        "fullReady": full_ready,
        "complete": not missing,
        "missing": missing,
        "missingLabels": [HIT_LABELS.get(key, key) for key in missing],
        "coreMissing": core_missing,
        "profile": profile,
        "includeSubagent": want_l6,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _store_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "sand-stream"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_root() -> Path:
    path = _store_root() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_rpc_target(path: Path, app_root: Path) -> bool:
    if path.name in RPC_FILE_NAMES:
        return True
    try:
        rel = path.resolve().relative_to(app_root.resolve()).as_posix()
    except ValueError:
        return False
    return rel.startswith(AGENT_HOST_DIST_REL + "/") and path.suffix == ".js" and not path.name.endswith("-worker.js")


def build_layout() -> SandLayout:
    layout = resolve_install()
    app_root = install_app_root(layout.install_root)
    product_json = app_root / "product.json"
    if not product_json.is_file():
        raise SandStreamError(f"找不到 product.json：{product_json}")
    try:
        product = json.loads(product_json.read_bytes().decode("utf-8-sig"))
    except Exception as exc:
        raise SandStreamError(f"无法解析 product.json：{exc}") from exc

    targets: list[Path] = []
    seen: set[str] = set()
    for rel, _ext in TARGET_SPECS:
        target = app_root.joinpath(*rel.split("/"))
        if not target.is_file():
            continue
        real = target.resolve()
        if not _is_within(real, app_root.resolve()):
            raise SandStreamError(f"目标文件逃逸 app 目录：{target}")
        key = str(real).casefold()
        if key in seen:
            continue
        seen.add(key)
        targets.append(real)
    dist_dir = app_root.joinpath(*AGENT_HOST_DIST_REL.split("/"))
    if dist_dir.is_dir():
        for chunk in sorted(dist_dir.glob("*.js")):
            if chunk.name == "main.js" or chunk.name.endswith("-worker.js"):
                continue
            if not chunk.is_file():
                continue
            real = chunk.resolve()
            if not _is_within(real, app_root.resolve()):
                continue
            key = str(real).casefold()
            if key in seen:
                continue
            seen.add(key)
            targets.append(real)
    if not targets:
        raise SandStreamError("当前 Cursor 没有可识别的 Sand Stream 目标文件（可能用了 app.asar）")

    ext_host = app_root.joinpath(*EXT_HOST_REL.split("/"))
    ext_host_real = ext_host.resolve() if ext_host.is_file() else None
    version = str(product.get("version") or product.get("commit") or layout.version or "未知")
    return SandLayout(
        install_root=Path(layout.install_root),
        app_root=app_root.resolve(),
        product_json=product_json.resolve(),
        executable=Path(layout.executable),
        target_paths=tuple(targets),
        ext_host_path=ext_host_real,
        version=version,
    )


def inspect_status(layout: SandLayout) -> PatchStatus:
    totals: dict[str, int] = {}
    external_marker_count = 0
    patched_files: list[str] = []
    launcher_markers = 0
    for target in layout.target_paths:
        content = target.read_text(encoding="utf-8", errors="ignore")
        hits = inspect_content_hits(content)
        launcher_markers += hits.get("launcherMarker") or 0
        if sum(hits.values()):
            patched_files.append(target.name)
        for key, value in hits.items():
            totals[key] = totals.get(key, 0) + value
        client_count = hits.get("client") or 0
        eligibility_count = hits.get("eligibility") or 0
        legacy_client_count = len(
            re.findall(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}", content)
        )
        legacy_eligibility_count = content.count("return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER)
        external_marker_count += max(
            0,
            len(re.findall(CLIENT_MARKER_GUARD_PATTERN, content))
            - client_count
            - legacy_client_count,
        )
        external_marker_count += max(
            0,
            len(re.findall(ELIGIBILITY_MARKER_GUARD_PATTERN, content))
            - eligibility_count
            - legacy_eligibility_count,
        )
    return PatchStatus(
        hits=totals,
        patched_files=tuple(patched_files),
        external_marker_count=external_marker_count,
        launcher_markers=launcher_markers,
    )


def _target_extension_name(layout: SandLayout, file_path: Path) -> str | None:
    for rel, extension_name in TARGET_SPECS:
        if not extension_name:
            continue
        candidate = layout.app_root.joinpath(*rel.split("/")).resolve()
        if candidate == file_path.resolve():
            return extension_name
    return None


def _update_extension_hashes(
    layout: SandLayout,
    pending: dict[Path, bytes],
) -> None:
    if layout.ext_host_path is None:
        return
    ext_path = layout.ext_host_path
    ext_bytes = pending.get(ext_path, ext_path.read_bytes())
    ext_content = ext_bytes.decode("utf-8")
    original = ext_content
    for file_path, data in pending.items():
        extension_name = _target_extension_name(layout, file_path)
        if not extension_name:
            continue
        extension_id = "anysphere." + extension_name
        if f'"{extension_id}"' not in ext_content:
            continue
        digest = hashlib.sha256(data).hexdigest()
        pattern = re.compile(
            rf'(\"{re.escape(extension_id)}\"\s*:\s*\{{[\s\S]{{0,2400}}?'
            rf'\"main\.js\"\s*:\s*\")[0-9a-f]{{64}}(\")'
        )
        ext_content, count = pattern.subn(
            lambda m: m.group(1) + digest + m.group(2),
            ext_content,
            count=1,
        )
        if count > 1:
            raise SandStreamError(f"{extension_id} 的内嵌 main.js 哈希不唯一")
    if ext_content != original:
        pending[ext_path] = ext_content.encode("utf-8")


def _snapshot_backup(
    layout: SandLayout,
    originals: dict[Path, bytes],
    *,
    operation: str,
) -> Path:
    app_hash = hashlib.sha256(str(layout.app_root).encode("utf-8")).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = _backup_root() / app_hash / f"{stamp}-{operation}"
    files_dir = backup_dir / "files"
    entries: list[dict[str, Any]] = []
    for path, data in originals.items():
        rel = path.resolve().relative_to(layout.app_root.resolve())
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entries.append(
            {
                "path": rel.as_posix(),
                "originalSha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "version": 1,
        "moduleVersion": MODULE_VERSION,
        "operation": operation,
        "appRoot": str(layout.app_root),
        "cursorVersion": layout.version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def _restore_backup(backup_dir: Path, layout: SandLayout) -> list[str]:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SandStreamError(f"备份无效：{backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored: list[str] = []
    for entry in manifest.get("files") or []:
        rel = entry.get("path")
        if not rel:
            continue
        src = backup_dir / "files" / rel
        dst = layout.app_root / rel
        if src.is_file() and dst.is_file():
            shutil.copy2(src, dst)
            restored.append(str(rel))
    return restored


def _commit_plan(
    layout: SandLayout,
    pending: dict[Path, bytes],
    *,
    operation: str,
    originals: dict[Path, bytes],
) -> dict[str, Any]:
    if not pending:
        return {"ok": True, "skipped": True, "changed": []}
    backup_dir = _snapshot_backup(layout, originals, operation=operation)
    for path, data in pending.items():
        if path.name not in WORKBENCH_NAMES:
            continue
        text = data.decode("utf-8")
        orig_text = originals.get(path, b"").decode("utf-8", errors="ignore")
        try:
            assert_safe(text, original=orig_text or None)
        except PreflightError as exc:
            _restore_backup(backup_dir, layout)
            raise SandStreamError("预检未通过：" + "; ".join(exc.issues)) from exc
    _update_extension_hashes(layout, pending)
    product_next = sync_product_checksums(layout.app_root, pending)
    if product_next is not None:
        pending[layout.product_json] = product_next
    changed: list[str] = []
    try:
        for path, data in pending.items():
            if path.is_file() and path.read_bytes() == data:
                continue
            write_atomic(path, data)
            changed.append(path.name)
    except Exception as exc:
        _restore_backup(backup_dir, layout)
        if isinstance(exc, PermissionError):
            raise SandStreamError("没有写入权限或文件被占用，请先关闭 Cursor") from exc
        raise SandStreamError(str(exc)) from exc
    return {
        "ok": True,
        "changed": changed,
        "backup": str(backup_dir),
        "operation": operation,
    }


def _add_stats(total: PatchStats | RemoveStats, stats: PatchStats | RemoveStats) -> None:
    for item in fields(stats):
        setattr(total, item.name, getattr(total, item.name) + getattr(stats, item.name))


def _build_install_plan(
    layout: SandLayout,
    *,
    profile: str,
    include_subagent: bool,
) -> tuple[dict[Path, bytes], PatchStats, dict[Path, bytes]]:
    pending: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}
    total = PatchStats()
    for target in layout.target_paths:
        original = target.read_bytes()
        originals[target] = original
        content = original.decode("utf-8")
        next_content, stats = apply_patch_to_content(
            content,
            profile=profile,
            include_subagent=include_subagent,
            inject_rpc=_is_rpc_target(target, layout.app_root),
        )
        if target.name == "workbench.desktop.main.js" and LAUNCHER_SAND_MARKER not in next_content:
            next_content = LAUNCHER_SAND_MARKER + next_content
        if next_content != content:
            pending[target] = next_content.encode("utf-8")
        _add_stats(total, stats)
    return pending, total, originals


def _build_uninstall_plan(layout: SandLayout) -> tuple[dict[Path, bytes], RemoveStats, dict[Path, bytes]]:
    pending: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}
    total = RemoveStats()
    for target in layout.target_paths:
        original = target.read_bytes()
        originals[target] = original
        content = original.decode("utf-8")
        next_content, stats = remove_patch_from_content(content)
        if next_content != content:
            pending[target] = next_content.encode("utf-8")
        _add_stats(total, stats)
    return pending, total, originals


def _version_hint(version: str) -> str:
    ver = (version or "").strip()
    if ver.startswith(ANCHOR_VERSION):
        return ""
    return f"锚点按 Cursor {ANCHOR_VERSION}；当前 v{ver or '未知'} 可能不全"


def _message(ready: dict[str, Any], installed: bool) -> str:
    if ready.get("fullReady"):
        return "完整档已就绪（工具 + Task/子代理）"
    if ready.get("toolsReady"):
        return "工具层已就绪；Task/子代理未齐，见缺失项"
    if ready.get("streamReady"):
        return "仅 Stream 已就绪（对话应走 InferenceService/Stream）"
    if installed:
        return "检测到部分 Sand 补丁；关 IDE 后重新启用可补全，见缺失项"
    return "未启用；Bot 对话需 Sand Stream 补丁才会走 InferenceService/Stream"


def _status_payload(
    layout: SandLayout,
    patch: PatchStatus,
    *,
    running: bool,
    profile: str = "full",
    include_subagent: bool = True,
) -> dict[str, Any]:
    ready = classify_readiness(
        patch.hits, profile=profile, include_subagent=include_subagent
    )
    hits = dict(patch.hits)
    hits["launcherMarker"] = patch.launcher_markers
    return {
        "ok": True,
        "installed": patch.installed,
        "streamMode": ready["streamReady"],
        "streamReady": ready["streamReady"],
        "toolsReady": ready["toolsReady"],
        "fullReady": ready["fullReady"],
        "complete": ready["complete"],
        "missing": ready["missing"],
        "missingLabels": ready["missingLabels"],
        "running": running,
        "version": layout.version,
        "versionHint": _version_hint(layout.version),
        "appRoot": str(layout.app_root),
        "files": list(patch.patched_files),
        "hits": hits,
        "canApply": not running,
        "canRestore": not running and patch.installed,
        "externalMarkers": patch.external_marker_count,
        "message": _message(ready, patch.installed),
        "endpoint": NEW_RPC_PATH,
        "profile": ready["profile"],
        "includeSubagent": ready["includeSubagent"],
        "layers": {
            "L0": {"hdrfixV2": hits.get("hdrfixV2") or 0, "eligibility": hits.get("eligibility") or 0},
            "L1": {key: hits.get(key) or 0 for key in CORE_HIT_KEYS},
            "L2": {"directStream": hits.get("directStream") or 0},
            "L3": {"transportHost": hits.get("transportHost") or 0},
            "L4": {"rpcRewrite": hits.get("rpcRewrite") or 0, "streamWrap": hits.get("streamWrap") or 0},
            "L5": {"moveExec": hits.get("moveExec") or 0},
            "L6": {key: hits.get(key) or 0 for key in L6_HIT_KEYS},
        },
    }


def status(profile: str = "full", include_subagent: bool = True) -> dict[str, Any]:
    running = is_cursor_running()
    try:
        layout = build_layout()
    except Exception as exc:
        return {
            "ok": False,
            "installed": False,
            "streamMode": False,
            "streamReady": False,
            "toolsReady": False,
            "fullReady": False,
            "running": running,
            "error": str(exc),
        }
    patch = inspect_status(layout)
    return _status_payload(
        layout,
        patch,
        running=running,
        profile=profile,
        include_subagent=include_subagent,
    )


def apply(profile: str = "full", include_subagent: bool = True) -> dict[str, Any]:
    profile = _normalize_profile(profile)
    include_subagent = bool(include_subagent) if profile == "full" else False
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再启用 Sand Stream", "running": True}
    try:
        layout = build_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    before = inspect_status(layout)
    if before.external_marker_count and not before.launcher_markers:
        return {
            "ok": False,
            "error": "检测到其他 Sand 补丁工具留下的标记；请先用原工具卸载，或由启动器「还原 Sand Stream」后再试",
        }

    pending, stats, originals = _build_install_plan(
        layout, profile=profile, include_subagent=include_subagent
    )
    if not pending:
        st = _status_payload(
            layout, before, running=False, profile=profile, include_subagent=include_subagent
        )
        ready = classify_readiness(before.hits, profile=profile, include_subagent=include_subagent)
        if ready["streamReady"] or before.installed:
            desktop = layout.app_root / "out/vs/workbench/workbench.desktop.main.js"
            if desktop.is_file() and LAUNCHER_SAND_MARKER not in desktop.read_text(
                encoding="utf-8", errors="ignore"
            ):
                orig = desktop.read_bytes()
                originals[desktop] = orig
                pending[desktop] = (LAUNCHER_SAND_MARKER + orig.decode("utf-8")).encode("utf-8")
            else:
                st["ok"] = True
                st["skipped"] = True
                st["message"] = "Sand Stream 已按当前档位安装，无需重复操作"
                return st
        else:
            return {
                "ok": False,
                "error": "当前 Cursor 版本未匹配到 Sand Stream 规则（可能需升级 Cursor 或更新启动器）",
                "hits": before.hits,
                "missing": ready["missing"],
                "missingLabels": ready["missingLabels"],
                "versionHint": _version_hint(layout.version),
            }

    try:
        result = _commit_plan(layout, pending, operation="apply", originals=originals)
    except SandStreamError as exc:
        return {"ok": False, "error": str(exc)}
    except WorkbenchWriteError as exc:
        return {"ok": False, "error": str(exc)}

    after = inspect_status(layout)
    st = _status_payload(
        layout, after, running=False, profile=profile, include_subagent=include_subagent
    )
    st.update(result)
    st["stats"] = {item.name: getattr(stats, item.name) for item in fields(stats)}
    ready = classify_readiness(after.hits, profile=profile, include_subagent=include_subagent)
    if ready["coreMissing"]:
        st["ok"] = False
        st["error"] = "核心 Stream 层未打齐：" + "、".join(
            HIT_LABELS.get(key, key) for key in ready["coreMissing"]
        )
        st["partial"] = True
        return st
    st["ok"] = True
    st["complete"] = ready["complete"]
    if not ready["complete"]:
        st["message"] = "已写入能打到的补丁，以下未命中：" + "、".join(ready["missingLabels"])
    return st


def restore() -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再还原 Sand Stream", "running": True}
    try:
        layout = build_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    before = inspect_status(layout)
    if not before.installed:
        st = _status_payload(layout, before, running=False)
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "当前未安装 Sand Stream，无需还原"
        return st

    pending, _stats, originals = _build_uninstall_plan(layout)
    if not pending:
        st = _status_payload(layout, before, running=False)
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "未发现可还原的 Sand Stream 改动"
        return st

    try:
        result = _commit_plan(layout, pending, operation="restore", originals=originals)
    except SandStreamError as exc:
        return {"ok": False, "error": str(exc)}
    except WorkbenchWriteError as exc:
        return {"ok": False, "error": str(exc)}

    after = inspect_status(layout)
    st = _status_payload(layout, after, running=False)
    st.update(result)
    st["message"] = "已还原 Sand Stream 补丁（含 RPC 片段，不留半档）"
    return st
