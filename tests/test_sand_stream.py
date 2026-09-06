"""sand_stream: 补丁逻辑单元测试（不碰真实 Cursor 安装）。"""

import re
from pathlib import Path

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
    SAND_SESSION_STREAM_MARKER,
    SAND_STREAM_WRAP_MARKER,
    SAND_SUBAGENT_COMPLETION_WAKE_MARKER,
    SAND_SUBAGENT_RESUME_MODE_MARKER,
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
    resolve_patch_track,
    SandLayout,
    PatchStatus,
    _build_install_plan,
    _bytes_may_have_sand_patch,
    _status_payload,
    inspect_status,
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
    assert "isGrok46ProductPrompt" in patched
    assert 'isGrok45ProductPrompt:i.includes("grok")&&!grok46' in patched


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
    assert "isGrok46ProductPrompt" in patched
    assert patched.count(SAND_DIRECT_STREAM_MARKER) == 1
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


def test_bytes_may_need_sand_patch_skips_unrelated():
    from launcher.sand_stream import _bytes_may_have_sand_patch, _bytes_may_need_sand_patch

    assert _bytes_may_need_sand_patch(b"function hre(e){return 1}") is True
    assert _bytes_may_need_sand_patch(
        b"return t=>{return n=this,o=void 0,s=function*(){"
    ) is True
    assert _bytes_may_need_sand_patch(b"class J{constructor") is True
    assert _bytes_may_need_sand_patch(b"console.log(1)") is False
    assert _bytes_may_have_sand_patch(b"/*SAND_FOO_V1*/") is True
    assert _bytes_may_have_sand_patch(b"console.log(1)") is False


def test_chunk_657_direct_stream_apply(tmp_path):
    chunk = tmp_path / "657.js"
    chunk.write_text(DIRECT_STREAM_ANCHOR + "yield 1;};};", encoding="utf-8")
    layout = SandLayout(
        install_root=tmp_path,
        app_root=tmp_path,
        product_json=tmp_path / "product.json",
        executable=tmp_path / "Cursor.exe",
        target_paths=(chunk,),
        ext_host_path=None,
        version="3.18.25",
    )
    pending, stats, _originals = _build_install_plan(
        layout, profile="stream", include_subagent=False
    )
    assert chunk in pending
    assert SAND_DIRECT_STREAM_MARKER in pending[chunk].decode("utf-8")
    assert stats.direct_stream >= 1


def test_empty_4884_does_not_block_full_ready():
    src = _core_bundle() + _l6_bundle()
    patched, _ = apply_patch_to_content(src, profile="full", include_subagent=True)
    ready = classify_readiness(inspect_content_hits(patched), profile="full", include_subagent=True)
    assert ready["fullReady"] is True
    assert "4884" not in " ".join(ready["missing"])


def test_resolve_patch_track_tested_318_builds():
    for ver in ("3.18.9", "3.18.25"):
        out = resolve_patch_track(ver)
        assert out["track"] == "3.18"
        assert out["source"] == "version"
        assert out["tested"] is True
        assert out["versionOk"] is True
        assert out["hint"] == ""


def test_resolve_patch_track_tested_319():
    out = resolve_patch_track("3.19.13")
    assert out["track"] == "3.19"
    assert out["source"] == "version"
    assert out["tested"] is True
    assert out["versionOk"] is True


def test_resolve_patch_track_same_family_untested():
    out = resolve_patch_track("3.18.30")
    assert out["track"] == "3.18"
    assert out["tested"] is False
    assert out["versionOk"] is False
    assert "同族未测" in out["hint"]


def test_resolve_patch_track_older_is_other():
    out = resolve_patch_track("3.12.30")
    assert out["track"] == "other"
    assert out["tested"] is False
    assert out["versionOk"] is False


def test_resolve_patch_track_sniff_319_when_version_missing():
    content = "class J{constructor(e,t,n,o){this.a=e} foo.Ycw(x)"
    out = resolve_patch_track("", content)
    assert out["track"] == "3.19"
    assert out["source"] == "content"


def test_resolve_patch_track_sniff_318_joe_when_version_missing():
    out = resolve_patch_track("", "s=new Joe(e,n,void 0,void 0).getSession()")
    assert out["track"] == "3.18"
    assert out["source"] == "content"


def test_resolve_patch_track_default_318_when_unknown():
    out = resolve_patch_track("", "console.log(1)")
    assert out["track"] == "3.18"
    assert out["source"] == "default"
    assert "版本未知" in out["hint"]


def _core_bundle_319() -> str:
    return (
        'g.header.set("x-cursor-client-type","ide");'
        + "function r4g(e){const{adminSettingsService:t"
        + 'if(!o)return{runtime:"connect",reason:"gate-off"};'
        + 'const s=g(t),i=A(s,e,r);return void 0!==i?f(i,s):{runtime:"managed-local",reason:"eligible"}'
        + "let t=!1;try{t=await r.cursor.checkFeatureGate(Ms)}"
        + "catch(e){console.error('agent_host_local_loop',e)}"
        + "if(!t)"
        + AGENT_HOST_IDENTITY_ORIGINAL
        + "class J{constructor(e,t,n,o){this.x=e}"
        + "foo.Ycw(bar)"
        + "function qwe(e){return t=>{return n=this,o=void 0,s=function*(){"
        + "yield 1;};};"
        + "this._agentHostEnabled=x,"
        + "createAgentHost),h=await Promise.resolve(r.cursor.checkFeatureGate(Js)).catch(()=>!1)"
        + "this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[kt.typeName]=s.agentBidiTransport"
        + "this._overrideMethodNameToTransportMap[kt.methods.run.name]=s.agentBidiTransport"
        + 'throw new Error("INVARIANT VIOLATION: Transport is undefined for service: "+kt.typeName);return kt.transport.stream(e,t,n)'
    )


def test_319_stream_injects_early_return_and_prompt_model_info():
    src = _core_bundle_319()
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert SAND_MANAGED_LOCAL_ROUTE_MARKER in patched
    assert 'if(!o)return{runtime:"connect",reason:"gate-off"}' in patched
    assert stats.managed_local_route == 1
    assert SAND_DIRECT_STREAM_MARKER in patched
    assert "promptModelInfo" in patched
    assert "useDsv3Harness:!1" in patched
    assert "isGrok46ProductPrompt" in patched
    assert "resolvedModelMetadata:nre(" not in patched
    assert "supportsSelfSummary:!1" in patched
    restored, _ = remove_patch_from_content(patched)
    assert SAND_DIRECT_STREAM_MARKER not in restored
    assert SAND_MANAGED_LOCAL_ROUTE_MARKER not in restored
    assert 'if(!o)return{runtime:"connect",reason:"gate-off"}' in restored


def test_318_direct_migrates_to_319_when_kernel_markers_appear():
    first, _ = apply_patch_to_content(_core_bundle(), profile="stream")
    assert "resolvedModelMetadata:nre(" in first
    mixed = first + "class J{constructor(e,t,n,o)}" + "foo.Ycw("
    second, stats = apply_patch_to_content(mixed, profile="stream")
    assert stats.migrated_direct_stream >= 1
    assert "promptModelInfo" in second
    assert "resolvedModelMetadata:nre(" not in second
    assert second.count(SAND_DIRECT_STREAM_MARKER) == 1


_ACTION_319_ORIGINAL = (
    '"userMessageAction"!==e.actionCase?"action-not-supported":'
    "function(e){return e.requestedMode===o.xy.AGENT||"
    "e.isHostedSubagentChild&&e.requestedMode===o.xy.UNSPECIFIED}(e)?"
    'e.simulatedUserMessage?"simulated-message-not-supported":y(e,r):"mode-not-supported"'
)
_SUBAGENT_ROUTE_319_ORIGINAL = (
    "isHostedSubagentChild:Boolean(e.runOptions.subagentTypeName||e.runOptions.parentAgentToolCallId)"
)
_SUBAGENT_SESSION_319_ORIGINAL = "outputNotificationLimit:1e3,useClientSideSubagent:!0}"
_TASK_319_ORIGINAL = (
    "isGenerateImageModelRestricted:!1,taskToolProps:Ne({parentModelId:null!=p?p:n.modelName,modelInfo:n})},resolvers:"
)
_RESUME_319_ORIGINAL = (
    "e.resumeAgentId&&e.mode===Mn.FL.UNSPECIFIED&&!e.readonly?o.xy.UNSPECIFIED:"
)


def _l6_bundle_319() -> str:
    return (
        _SUBAGENT_ROUTE_319_ORIGINAL
        + _ACTION_319_ORIGINAL
        + _RESUME_319_ORIGINAL
        + _SUBAGENT_SESSION_319_ORIGINAL
        + _TASK_319_ORIGINAL
        + 'x.source==="interactive-child"||x.payload.notificationContext==="user_driven_interactive_child"'
    )


def test_319_l6_action_v2_has_whitelist_without_mode_not_supported():
    src = _core_bundle_319() + _ACTION_319_ORIGINAL
    patched, _ = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert SAND_MANAGED_ACTION_ROUTE_MARKER in patched
    assert "summarizeAction" in patched
    assert "resumeAction" in patched
    assert "executePlanAction" in patched
    action_idx = patched.index(SAND_MANAGED_ACTION_ROUTE_MARKER)
    action_chunk = patched[action_idx : action_idx + 900]
    assert "mode-not-supported" not in action_chunk
    restored, _ = remove_patch_from_content(patched)
    assert _ACTION_319_ORIGINAL in restored
    assert SAND_MANAGED_ACTION_ROUTE_MARKER not in restored


def test_319_l6_encodes_v3_task_and_319_route_session():
    src = _core_bundle_319() + _l6_bundle_319()
    patched, stats = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert SAND_MANAGED_SUBAGENT_ROUTE_MARKER in patched
    assert SAND_MANAGED_SUBAGENT_SESSION_MARKER in patched
    assert SAND_MANAGED_TASK_TOOL_MARKER in patched
    assert SAND_SUBAGENT_RESUME_MODE_MARKER in patched
    assert "o.xy.AGENT" in patched
    assert "void 0!==e.runOptions.subagentTypeName?void 0:" in patched
    assert "parentRequestedModelName:e.requestedModel.modelId" in patched
    assert "Object.assign(Ne({parentModelId:null!=p?p:n.modelName,modelInfo:n})," in patched
    assert stats.managed_task_tool == 1
    restored, _ = remove_patch_from_content(patched)
    assert _SUBAGENT_ROUTE_319_ORIGINAL in restored
    assert _SUBAGENT_SESSION_319_ORIGINAL in restored
    assert _TASK_319_ORIGINAL in restored
    assert _RESUME_319_ORIGINAL in restored
    assert SAND_MANAGED_TASK_TOOL_MARKER not in restored


def test_319_l6_without_task_anchor_does_not_fake_full_ready():
    src = (
        _core_bundle_319()
        + _SUBAGENT_ROUTE_319_ORIGINAL
        + _ACTION_319_ORIGINAL
        + _RESUME_319_ORIGINAL
        + _SUBAGENT_SESSION_319_ORIGINAL
        + 'x.source==="interactive-child"||x.payload.notificationContext==="user_driven_interactive_child"'
    )
    patched, _ = apply_patch_to_content(src, profile="full", include_subagent=True)
    ready = classify_readiness(inspect_content_hits(patched), profile="full", include_subagent=True)
    assert SAND_MANAGED_ACTION_ROUTE_MARKER in patched
    assert "taskTool" in ready["missing"]
    assert ready["fullReady"] is False


def test_stream_profile_skips_319_l6():
    src = _core_bundle_319() + _l6_bundle_319()
    patched, _ = apply_patch_to_content(src, profile="stream", include_subagent=True)
    assert SAND_MANAGED_ACTION_ROUTE_MARKER not in patched
    assert SAND_MANAGED_TASK_TOOL_MARKER not in patched
    assert SAND_MANAGED_SUBAGENT_ROUTE_MARKER not in patched
    assert SAND_MANAGED_SUBAGENT_SESSION_MARKER not in patched


def test_route_label_only_when_present_and_not_bound_to_stream_ready():
    none, _ = apply_patch_to_content("hello workbench", profile="stream")
    assert "本次使用" not in none
    assert "> grok-bot route to" not in none

    src = _core_bundle() + '["Routed to "'
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert stats.route_label == 1
    assert '/*ROUTE_LABEL_V1*/["本次使用 "' in patched
    assert '["Routed to "' not in patched
    assert "> grok-bot route to" not in patched
    hits = inspect_content_hits(patched)
    assert hits["routeLabel"] == 1
    ready = classify_readiness(hits, profile="stream")
    assert ready["streamReady"] is True
    assert "routeLabel" not in ready["missing"]
    restored, rst = remove_patch_from_content(patched)
    assert rst.route_label == 1
    assert '["Routed to "' in restored
    assert "本次使用" not in restored
    assert _bytes_may_have_sand_patch(patched.encode("utf-8")) is True
    assert _bytes_may_have_sand_patch('/*ROUTE_LABEL_V1*/["本次使用 "'.encode("utf-8")) is True


def test_status_payload_exposes_patch_track():
    layout = SandLayout(
        install_root=Path("."),
        app_root=Path("."),
        product_json=Path("product.json"),
        executable=Path("Cursor.exe"),
        target_paths=(),
        ext_host_path=None,
        version="3.19.13",
    )
    payload = _status_payload(layout, PatchStatus(), running=False)
    assert payload["patchTrack"] == "3.19"
    assert payload["trackSource"] == "version"
    assert payload["testedBuild"] is True
    assert payload["versionOk"] is True
    assert "3.18" in payload["supportedTracks"]
    assert "3.19" in payload["supportedTracks"]


def test_install_plan_other_track_skips_specialized(tmp_path):
    chunk = tmp_path / "main.js"
    chunk.write_text(_core_bundle(), encoding="utf-8")
    layout = SandLayout(
        install_root=tmp_path,
        app_root=tmp_path,
        product_json=tmp_path / "product.json",
        executable=tmp_path / "Cursor.exe",
        target_paths=(chunk,),
        ext_host_path=None,
        version="3.12.30",
    )
    pending, _stats, _originals = _build_install_plan(
        layout, profile="stream", include_subagent=False
    )
    text = pending[chunk].decode("utf-8")
    assert SAND_HDRFIX_V2_MARKER in text
    assert SAND_MANAGED_LOCAL_ROUTE_MARKER not in text
    assert SAND_DIRECT_STREAM_MARKER not in text


def test_319_direct_markers_are_not_external(tmp_path):
    patched, _ = apply_patch_to_content(_core_bundle_319(), profile="stream")
    target = tmp_path / "main.js"
    target.write_text(patched, encoding="utf-8")
    layout = SandLayout(
        install_root=tmp_path,
        app_root=tmp_path,
        product_json=tmp_path / "product.json",
        executable=tmp_path / "Cursor.exe",
        target_paths=(target,),
        ext_host_path=None,
        version="3.19.13",
    )
    status = inspect_status(layout, include_compat=False)
    assert status.hits["directStream"] >= 1
    assert status.external_marker_count == 0
