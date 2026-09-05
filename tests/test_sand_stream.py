"""sand_stream: 补丁逻辑单元测试（不碰真实 Cursor 安装）。"""

from launcher.sand_stream import (
    AGENT_HOST_IDENTITY_ORIGINAL,
    AGENT_HOST_IDENTITY_PATCHED,
    DIRECT_STREAM_ANCHOR,
    LAUNCHER_SAND_MARKER,
    MANAGED_ACTION_ROUTE_ORIGINAL,
    MANAGED_SUBAGENT_ROUTE_ORIGINAL,
    MANAGED_SUBAGENT_SESSION_ORIGINAL,
    MANAGED_TASK_TOOL_ORIGINAL,
    SAND_AGENT_HOST_ENABLEMENT_MARKER,
    SAND_CLIENT_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_ELIGIBILITY_MARKER,
    SAND_HDRFIX_V2_MARKER,
    SAND_MANAGED_TASK_TOOL_MARKER,
    SAND_MOVE_EXEC_MARKER,
    SAND_RPC_REWRITE_MARKER,
    SAND_STREAM_WRAP_MARKER,
    SAND_SUBAGENT_COMPLETION_WAKE_MARKER,
    SAND_TRANSPORT_HOST_MARKER,
    SUBAGENT_RESUME_MODE_ORIGINAL,
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
        + 'this._overrideServiceNameToTransportMapLowerPriorityThanMethodOverrides[kt.typeName]=s.agentBidiTransport'
        + 'this._overrideMethodNameToTransportMap[kt.methods.run.name]=s.agentBidiTransport'
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


def _legacy_unconditional_injection() -> str:
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + 'const n=t.requestedModel;'
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        'r=new Map(n.parameters.map(e=>[e.id,e.value])),'
        's=new Joe(e,n,void 0,void 0).getSession(),'
        'p={getExecutor:e=>new RK(s.getExecutor(e))},'
        'a={vendor:"unknown",promptVersion:"latest"};'
        'return{promptSession:s,promptToolSession:p,attempt:{resolvedModel:cre(n),'
        'supportsSelfSummary:!1,routedModelDisplayName:o,'
        'resolvedModelMetadata:nre(a,o),finish:()=>Promise.resolve()}}}'
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


def test_conditional_stream_does_not_skip_runinference():
    src = DIRECT_STREAM_ANCHOR + "e.runInference(t);yield 1"
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert 'if(!(e&&typeof e.runInference==="function")){' in patched
    assert "e.runInference(t);yield 1" in patched
    assert patched.index(SAND_DIRECT_STREAM_MARKER) < patched.index("e.runInference(t)")


def test_strip_legacy_unconditional_stream():
    src = DIRECT_STREAM_ANCHOR + _legacy_unconditional_injection() + "yield 1"
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert patched.count(SAND_DIRECT_STREAM_MARKER) == 1
    assert 'if(!(e&&typeof e.runInference==="function")){' in patched
    assert "n.parameters.map(e=>[e.id,e.value])" not in patched or "n.parameters||[]" in patched


def test_hdrfix_v2_agent_path_returns_ide():
    src = 'g.header.set("x-cursor-client-type","ide");'
    patched, stats = apply_patch_to_content(src, profile="stream")
    assert SAND_HDRFIX_V2_MARKER in patched
    assert stats.set_header == 1
    assert 'AgentService' in patched
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

    tools_only, _ = apply_patch_to_content(src, profile="full", include_subagent=False)
    assert SAND_MOVE_EXEC_MARKER in tools_only
    assert SAND_MANAGED_TASK_TOOL_MARKER not in tools_only

    full, stats = apply_patch_to_content(src, profile="full", include_subagent=True)
    assert SAND_MOVE_EXEC_MARKER in full
    assert SAND_MANAGED_TASK_TOOL_MARKER in full
    assert SAND_SUBAGENT_COMPLETION_WAKE_MARKER in full
    assert stats.managed_task_tool == 1
    assert stats.subagent_completion_wake == 1


def test_remove_restores_ide_identity():
    src = _core_bundle() + _l6_bundle()
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
    src = _core_bundle() + _l6_bundle()
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

    no_wake = patched.replace(SAND_SUBAGENT_COMPLETION_WAKE_MARKER, "")
    # 去掉 wake 注入后 source==="subagent" 前缀也没了，应进 missing
    stripped = no_wake.replace('x.source==="subagent"||', "")
    partial = inspect_content_hits(stripped)
    ready2 = classify_readiness(partial, profile="full", include_subagent=True)
    assert ready2["toolsReady"] is True
    assert ready2["fullReady"] is False
    assert "completionWake" in ready2["missing"]
    assert ready2["complete"] is False


def test_classify_missing_managed_local_is_not_stream_ready():
    src = 'g.header.set("x-cursor-client-type","ide");' + AGENT_HOST_IDENTITY_ORIGINAL
    patched, _ = apply_patch_to_content(src, profile="stream")
    hits = inspect_content_hits(patched)
    ready = classify_readiness(hits, profile="stream")
    assert ready["streamReady"] is False
    assert "managedLocalRoute" in ready["missing"]
