"""sand_stream: 补丁逻辑单元测试（不碰真实 Cursor 安装）。"""

import re

from launcher.sand_stream import (
    AGENT_HOST_IDENTITY_ORIGINAL,
    AGENT_HOST_IDENTITY_PATCHED,
    CLIENT_MARKER_GUARD_PATTERN,
    DIRECT_STREAM_ANCHOR,
    ELIGIBILITY_MARKER_GUARD_PATTERN,
    LAUNCHER_SAND_MARKER,
    LEGACY_SAND_MANAGED_ACTION_ROUTE_MARKER,
    LEGACY_SAND_MANAGED_TASK_TOOL_MARKER_V2,
    MANAGED_ACTION_ROUTE_ORIGINAL,
    MANAGED_ACTION_ROUTE_PATCHED_V1,
    MANAGED_SUBAGENT_ROUTE_ORIGINAL,
    MANAGED_SUBAGENT_SESSION_ORIGINAL,
    MANAGED_TASK_TOOL_ORIGINAL,
    MAX_TOKENS_ORIGINAL,
    MCP_FILESYSTEM_ORIGINAL,
    RULES_PRESEED_ORIGINAL,
    RULES_SKILLS_EXEC_ORIGINAL,
    SAND_AGENT_HOST_ENABLEMENT_MARKER,
    SAND_CLIENT_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_ELIGIBILITY_MARKER,
    SAND_HDRFIX_V2_MARKER,
    SAND_MANAGED_ACTION_ROUTE_MARKER,
    SAND_MANAGED_TASK_TOOL_MARKER,
    SAND_MAX_TOKENS_MARKER,
    SAND_MCP_FILESYSTEM_MARKER,
    SAND_MOVE_EXEC_MARKER,
    SAND_PUSH_CONTEXT_TIMEOUT_MARKER,
    SAND_RPC_REWRITE_MARKER,
    SAND_RULES_PRESEED_MARKER,
    SAND_RULES_SKILLS_MARKER,
    SAND_SESSION_STREAM_MARKER,
    SAND_STREAM_WRAP_MARKER,
    SAND_SUBAGENT_COMPLETION_WAKE_MARKER,
    SAND_TRANSPORT_HOST_MARKER,
    SAND_USER_RULES_MARKER,
    SUBAGENT_RESUME_MODE_ORIGINAL,
    USER_RULES_SAMPLE,
    _conditional_direct_stream_injection,
    _managed_task_tool_patched_v126,
    apply_patch_to_content,
    classify_readiness,
    inspect_content_hits,
    remove_patch_from_content,
)


def _core_bundle() -> str:
    return (
        'g.header.set("x-cursor-client-type","ide");'
        + 'header.set("x-cursor-client-type", foo ?? "ide");'
        + "function r4g(e){const{adminSettingsService:t"
        + 'try{return(yield o.checkFeatureGate(ae))?'
        '{runtime:"managed-local",reason:"eligible"}:'
        '{runtime:"connect",reason:"gate-off"}}catch(e)'
        + "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}catch(e){console.error('agent_host_local_loop',e)}"
        + "if(!t)"
        + AGENT_HOST_IDENTITY_ORIGINAL
        + DIRECT_STREAM_ANCHOR
        + "yield 1;};};"
        + "this._agentHostEnabled=x,"
        + "createAgentHost),p=await Promise.resolve(r.cursor.checkFeatureGate(Us)).catch(()=>!1)"
        + "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[kt.typeName]=s.agentBidiTransport"
        + "this._overrideMethodNameToTransportMap[kt.methods.run.name]=s.agentBidiTransport"
        + 'throw new Error("INVARIANT VIOLATION: Transport is undefined for service: "+kt.typeName);return kt.transport.stream(e,t,n)'
    )


def _l6_bundle() -> str:
    return (
        MANAGED_SUBAGENT_ROUTE_ORIGINAL
        + MANAGED_ACTION_ROUTE_ORIGINAL
        + SUBAGENT_RESUME_MODE_ORIGINAL
        + MANAGED_SUBAGENT_SESSION_ORIGINAL
        + MANAGED_TASK_TOOL_ORIGINAL
        + 'x.source==="interactive-child"||x.payload.notificationContext==="user_driven_interactive_child"'
    )


def _l7_bundle() -> str:
    return (
        MAX_TOKENS_ORIGINAL
        + RULES_SKILLS_EXEC_ORIGINAL
        + MCP_FILESYSTEM_ORIGINAL
        + USER_RULES_SAMPLE
    )


def _l8_bundle() -> str:
    return RULES_PRESEED_ORIGINAL + '"[push_req_context]",z=1e4'


def _legacy_unconditional_injection() -> str:
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + "const n=t.requestedModel;"
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        "r=new Map(n.parameters.map(e=>[e.id,e.value])),"
        "s=new Joe(e,n,void 0,void 0).getSession(),"
        "p={getExecutor:e=>new RK(s.getExecutor(e))},"
        'a={vendor:"unknown",promptVersion:"latest"};'
        "return{promptSession:s,promptToolSession:p,attempt:{resolvedModel:cre(n),"
        "supportsSelfSummary:!1,routedModelDisplayName:o,"
        "resolvedModelMetadata:nre(a,o),finish:()=>Promise.resolve()}}}"
    )


def test_apply_injects_stream_markers():
    src = _core_bundle()
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert SAND_CLIENT_MARKER in patched
    assert SAND_ELIGIBILITY_MARKER in patched
    assert SAND_DIRECT_STREAM_MARKER in patched
    assert SAND_HDRFIX_V2_MARKER in patched
    assert 'runtime:"managed-local",reason:"sand-client"' in patched
    assert AGENT_HOST_IDENTITY_PATCHED in patched
    assert SAND_AGENT_HOST_ENABLEMENT_MARKER in patched
    assert stats.direct_stream == 1
    assert stats.managed_local_route == 1
    assert SAND_MOVE_EXEC_MARKER not in patched
    assert SAND_MANAGED_TASK_TOOL_MARKER not in patched


def test_direct_stream_injects_even_when_runinference_present():
    src = DIRECT_STREAM_ANCHOR + "e.runInference(t);yield 1"
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert SAND_DIRECT_STREAM_MARKER in patched
    assert 'if(!(e&&typeof e.runInference==="function")){' not in patched
    assert "e.runInference(t);yield 1" in patched
    assert "agentTokenLimit:" in patched
    assert "supportsSelfSummary:!1" in patched
    assert "supportsSelfSummary:!0" not in patched
    assert patched.index(SAND_DIRECT_STREAM_MARKER) < patched.index("e.runInference(t)")


def test_direct_stream_anchor_is_not_hardcoded_hre():
    src = (
        "function qwe(e){return t=>{return n=this,o=void 0,s=function*(){"
        "yield 1;};};"
    )
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert stats.direct_stream == 1
    assert SAND_DIRECT_STREAM_MARKER in patched
    assert "function qwe(e){return t=>{return n=this,o=void 0,s=function*(){" in patched


def test_strip_conditional_direct_stream():
    src = DIRECT_STREAM_ANCHOR + _conditional_direct_stream_injection() + "yield 1"
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert patched.count(SAND_DIRECT_STREAM_MARKER) == 1
    assert 'if(!(e&&typeof e.runInference==="function")){' not in patched
    assert stats.migrated_direct_stream >= 1
    assert "(n.parameters||[])" in patched


def test_strip_legacy_and_session_stream():
    src = (
        DIRECT_STREAM_ANCHOR
        + _legacy_unconditional_injection()
        + SAND_SESSION_STREAM_MARKER
        + "yield 1"
    )
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert patched.count(SAND_DIRECT_STREAM_MARKER) == 1
    assert SAND_SESSION_STREAM_MARKER not in patched
    assert 'if(!(e&&typeof e.runInference==="function")){' not in patched
    assert "(n.parameters||[])" in patched
    restored, _ = remove_patch_from_content(patched)
    assert SAND_DIRECT_STREAM_MARKER not in restored
    assert SAND_SESSION_STREAM_MARKER not in restored


def test_hdrfix_v2_agent_path_returns_ide():
    src = 'g.header.set("x-cursor-client-type","ide");'
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert SAND_HDRFIX_V2_MARKER in patched
    assert stats.set_header == 1
    assert "AgentService" in patched
    assert "AvailableModels" in patched
    restored, _ = remove_patch_from_content(patched)
    assert SAND_HDRFIX_V2_MARKER not in restored
    assert 'g.header.set("x-cursor-client-type","ide")' in restored


def test_rpc_inject_and_strip():
    src = _core_bundle()
    patched, stats = apply_patch_to_content(src, profile="stream", inject_rpc=True)
    assert SAND_RPC_REWRITE_MARKER in patched
    assert SAND_STREAM_WRAP_MARKER in patched
    assert SAND_TRANSPORT_HOST_MARKER in patched
    assert stats.rpc_rewrite >= 1
    restored, _ = remove_patch_from_content(patched)
    assert SAND_RPC_REWRITE_MARKER not in restored
    assert SAND_STREAM_WRAP_MARKER not in restored
    assert SAND_TRANSPORT_HOST_MARKER not in restored
    assert "s.agentBidiTransport" in restored


def test_full_adds_move_exec_and_optional_l6():
    src = _core_bundle() + _l6_bundle()
    stream_only, _ = apply_patch_to_content(src, profile="stream", include_subagent=True)
    assert SAND_MOVE_EXEC_MARKER not in stream_only
    assert SAND_MANAGED_TASK_TOOL_MARKER not in stream_only
    assert SAND_SUBAGENT_COMPLETION_WAKE_MARKER not in stream_only
    assert SAND_RULES_PRESEED_MARKER not in stream_only

    tools_only, _ = apply_patch_to_content(src, profile="full", include_subagent=False)
    assert SAND_MOVE_EXEC_MARKER in tools_only
    assert SAND_MANAGED_TASK_TOOL_MARKER not in tools_only

    full, stats = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert SAND_MOVE_EXEC_MARKER in full
    assert SAND_MANAGED_TASK_TOOL_MARKER in full
    assert SAND_SUBAGENT_COMPLETION_WAKE_MARKER in full
    assert stats.managed_task_tool == 1
    assert stats.subagent_completion_wake == 1
    assert "void 0!==e.runOptions.subagentTypeName?void 0:" in full
    assert "parentRequestedModelName:e.requestedModel.modelId" in full
    assert "t=>t===e.requestedModel.modelId||t===i" in full
    assert "e=>e===e.requestedModel" not in full
    assert "summarizeAction" in full
    assert "resumeAction" in full
    assert "executePlanAction" in full
    assert SAND_MANAGED_ACTION_ROUTE_MARKER in full
    action_idx = full.index(SAND_MANAGED_ACTION_ROUTE_MARKER)
    action_chunk = full[action_idx : action_idx + 900]
    assert "mode-not-supported" not in action_chunk


def test_migrate_action_v1_and_task_v2():
    src = MANAGED_ACTION_ROUTE_PATCHED_V1 + _managed_task_tool_patched_v126()
    patched, stats = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert LEGACY_SAND_MANAGED_ACTION_ROUTE_MARKER not in patched
    assert SAND_MANAGED_ACTION_ROUTE_MARKER in patched
    assert LEGACY_SAND_MANAGED_TASK_TOOL_MARKER_V2 not in patched
    assert SAND_MANAGED_TASK_TOOL_MARKER in patched
    assert stats.migrated_action_route >= 1
    assert stats.migrated_task_tool >= 1


def test_l7_and_l8_full_only():
    src = _core_bundle() + _l6_bundle() + _l7_bundle() + _l8_bundle()
    stream_only, _ = apply_patch_to_content(src, profile="stream")
    assert SAND_MAX_TOKENS_MARKER not in stream_only
    assert SAND_RULES_PRESEED_MARKER not in stream_only
    assert SAND_PUSH_CONTEXT_TIMEOUT_MARKER not in stream_only

    full, _ = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert SAND_MAX_TOKENS_MARKER in full
    assert SAND_RULES_SKILLS_MARKER in full
    assert SAND_MCP_FILESYSTEM_MARKER in full
    assert SAND_USER_RULES_MARKER in full
    assert SAND_RULES_PRESEED_MARKER in full
    assert SAND_PUSH_CONTEXT_TIMEOUT_MARKER in full
    assert "this._lastPushedRulesProto=[]" in full
    assert '"[push_req_context]",z=50' in full
    assert "if(!1&&!f.localMode)" in full

    cam_timeout = _core_bundle() + _l6_bundle() + '"[push_req_context]",z=200' + SAND_PUSH_CONTEXT_TIMEOUT_MARKER
    migrated_timeout, _ = apply_patch_to_content(cam_timeout, profile="full", include_subagent=True)
    assert '"[push_req_context]",z=50' + SAND_PUSH_CONTEXT_TIMEOUT_MARKER in migrated_timeout
    assert '"[push_req_context]",z=200' not in migrated_timeout

    restored, _ = remove_patch_from_content(full)
    assert SAND_MAX_TOKENS_MARKER not in restored
    assert SAND_RULES_PRESEED_MARKER not in restored
    assert SAND_PUSH_CONTEXT_TIMEOUT_MARKER not in restored
    assert RULES_PRESEED_ORIGINAL in restored
    assert '"[push_req_context]",z=1e4' in restored
    assert MAX_TOKENS_ORIGINAL in restored


def test_remove_restores_ide_identity():
    src = _core_bundle() + _l6_bundle() + _l7_bundle() + _l8_bundle()
    patched, _ = apply_patch_to_content(src, profile="full", include_subagent=True, inject_rpc=True)
    restored, stats = remove_patch_from_content(patched)
    assert SAND_DIRECT_STREAM_MARKER not in restored
    assert AGENT_HOST_IDENTITY_ORIGINAL in restored
    assert SAND_MOVE_EXEC_MARKER not in restored
    assert SAND_MANAGED_TASK_TOOL_MARKER not in restored
    assert SAND_HDRFIX_V2_MARKER not in restored
    assert stats.direct_stream >= 1


def test_launcher_marker_roundtrip():
    src = LAUNCHER_SAND_MARKER + _core_bundle()
    restored, _ = remove_patch_from_content(src)
    assert LAUNCHER_SAND_MARKER not in restored


def test_idempotent_apply():
    src = _core_bundle() + _l6_bundle() + _l7_bundle() + _l8_bundle()
    first, _ = apply_patch_to_content(src, profile="full", include_subagent=True, inject_rpc=True)
    second, stats2 = apply_patch_to_content(first, profile="full", include_subagent=True, inject_rpc=True)
    assert second == first
    assert stats2.direct_stream == 0
    assert stats2.managed_task_tool == 0


def test_classify_missing_wake_keeps_tools_ready():
    hits = inspect_content_hits(_core_bundle() + _l6_bundle())
    patched, _ = apply_patch_to_content(_core_bundle() + _l6_bundle(), profile="full", include_subagent=True)
    after = inspect_content_hits(patched)
    ready = classify_readiness(after, profile="full", include_subagent=True)
    assert ready["streamReady"] is True
    assert ready["toolsReady"] is True
    assert ready["fullReady"] is True
    assert hits["managedLocalRoute"] == 0
    assert "maxTokens" in ready["missing"]
    assert ready["complete"] is False

    no_wake = patched.replace(SAND_SUBAGENT_COMPLETION_WAKE_MARKER, "")
    stripped = no_wake.replace('x.source==="subagent"||', "")
    partial = inspect_content_hits(stripped)
    ready2 = classify_readiness(partial, profile="full", include_subagent=True)
    assert ready2["toolsReady"] is True
    assert ready2["fullReady"] is False
    assert "completionWake" in ready2["missing"]
    assert ready2["complete"] is False


def test_classify_missing_direct_is_not_stream_ready():
    hits = {
        "managedLocalRoute": 1,
        "localRuntimeLoad": 1,
        "agentHostEnablement": 1,
        "agentHostIdentity": 1,
        "directStream": 0,
        "hdrfixV2": 1,
        "rpcRewrite": 1,
        "streamWrap": 1,
        "transportHost": 1,
    }
    ready = classify_readiness(hits, profile="stream")
    assert ready["streamReady"] is False
    assert "directStream" in ready["missing"]


def test_classify_missing_managed_local_is_not_stream_ready():
    src = 'g.header.set("x-cursor-client-type","ide");' + AGENT_HOST_IDENTITY_ORIGINAL
    patched, _ = apply_patch_to_content(src, profile="stream")
    hits = inspect_content_hits(patched)
    ready = classify_readiness(hits, profile="stream")
    assert ready["streamReady"] is False
    assert "managedLocalRoute" in ready["missing"]


def _external_marker_count(content: str) -> int:
    hits = inspect_content_hits(content)
    client_count = hits.get("client") or 0
    eligibility_count = hits.get("eligibility") or 0
    external = max(
        0,
        len(re.findall(CLIENT_MARKER_GUARD_PATTERN, content)) - client_count,
    )
    external += max(
        0,
        len(re.findall(ELIGIBILITY_MARKER_GUARD_PATTERN, content)) - eligibility_count,
    )
    return external


def test_known_v131_markers_are_not_foreign_hits():
    src = _core_bundle() + _l6_bundle() + _l7_bundle() + _l8_bundle()
    patched, _ = apply_patch_to_content(src, profile="full", include_subagent=True)
    hits = inspect_content_hits(patched)
    assert hits["directStream"] >= 1
    assert hits["taskTool"] >= 1
    assert hits["maxTokens"] >= 1
    assert hits["rulesPreseed"] >= 1
    assert hits["pushContextTimeout"] >= 1
    assert _external_marker_count(patched) == 0
    cam_only = (
        SAND_DIRECT_STREAM_MARKER
        + SAND_MANAGED_TASK_TOOL_MARKER
        + SAND_MANAGED_ACTION_ROUTE_MARKER
        + SAND_RULES_PRESEED_MARKER
        + SAND_PUSH_CONTEXT_TIMEOUT_MARKER
        + '"sand"'
        + SAND_CLIENT_MARKER
    )
    assert _external_marker_count(cam_only) == 0
    assert _external_marker_count('"sand"/*ZZZ_SAND_CLIENT_MODE_V1*/') >= 1
