"""sand_report：规则状态与可改包判定（不碰真实 Cursor 安装）。"""

from launcher.sand_report import adjust_compat_scope, evaluate_compat
from launcher.sand_stream import (
    ANCHOR_VERSION,
    DIRECT_STREAM_ANCHOR,
    SAND_AGENT_IDE_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_RPC_REWRITE_MARKER,
    apply_patch_to_content,
    inspect_content_hits,
)


def _direct_src() -> str:
    return DIRECT_STREAM_ANCHOR + "yield 1;};};"


def _rule(compat: dict, key: str) -> dict:
    return next(row for row in compat["rules"] if row["key"] == key)


def test_stale_hdrfix_without_catalog_keep_is_pending():
    old_fn = (
        '(function(r){try{var u=String((r&&r.url)||""),s=String((r&&r.service&&r.service.typeName)||"");'
        'if(/AgentService|\\/agent\\.v1\\./.test(u+s))return"ide"}catch(x){}return"sand"})'
    )
    src = 'g.header.set("x-cursor-client-type",' + old_fn + "(g)/*SAND_HDRFIX_V2*/)"
    row = _rule(evaluate_compat([("workbench.desktop.main.js", src)]), "hdrfixV2")
    assert row["status"] == "partial"
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert "AvailableModels" in patched
    assert patched.count("/*SAND_HDRFIX_V2*/") == 1


def test_hdrfix_leftover_on_client_type_header():
    src = 'g.header.set("x-cursor-client-type","ide");'
    row = _rule(evaluate_compat([("workbench.desktop.main.js", src)]), "hdrfixV2")
    assert row["status"] == "pending"
    patched, _ = apply_patch_to_content(src, profile="stream")
    row = _rule(evaluate_compat([("workbench.desktop.main.js", patched)]), "hdrfixV2")
    assert row["status"] == "applied"


def test_direct_leftover_is_pending_then_applied():
    pending = evaluate_compat([("workbench.desktop.main.js", _direct_src())])
    row = _rule(pending, "directStream")
    assert row["status"] == "pending"
    assert row["statusLabel"] == "可打未打"
    assert "workbench.desktop.main.js" in row["files"]

    patched, _ = apply_patch_to_content(_direct_src(), profile="stream")
    assert SAND_DIRECT_STREAM_MARKER in patched
    applied = evaluate_compat([("workbench.desktop.main.js", patched)])
    row = _rule(applied, "directStream")
    assert row["status"] == "applied"
    pkg = applied["packages"][0]
    assert "directStream" in pkg["patched"]
    assert "directStream" not in pkg["canPatch"]


def test_missing_when_anchor_absent():
    data = evaluate_compat([("workbench.desktop.main.js", "console.log(1)")])
    row = _rule(data, "directStream")
    assert row["status"] == "missing"
    assert row["missKind"] == "feature_absent"
    assert row["statusLabel"] == "版本没有"
    assert data["packages"][0]["patchable"] is False


def test_rpc_missing_is_package_absent():
    workbench = evaluate_compat([("workbench.desktop.main.js", "plain")])
    row = _rule(workbench, "rpcRewrite")
    assert row["status"] == "missing"
    assert row["missKind"] == "package_absent"
    assert row["statusLabel"] == "包不存在"


def test_eligibility_wrong_shape_is_code_changed():
    src = "function Z3r({experimentService:t,adminSettingsService:n}){if(jl.localMode)"
    row = _rule(evaluate_compat([("workbench.desktop.main.js", src)]), "eligibility")
    assert row["status"] == "missing"
    assert row["missKind"] == "shape_changed"
    assert row["statusLabel"] == "代码变了"


def test_l1_without_agent_host_is_package_absent():
    row = _rule(evaluate_compat([("workbench.desktop.main.js", "plain")]), "managedLocalRoute")
    assert row["status"] == "missing"
    assert row["missKind"] == "package_absent"


def test_upgrade_advice_older_than_anchor():
    data = evaluate_compat([], cursor_version="3.12.30")
    assert data["upgrade"]["relation"] == "older"
    assert data["patchTrack"] == "other"
    assert "3.18" in data["upgrade"]["advice"]
    assert "网关" in data["upgrade"]["advice"]


def test_rpc_only_counts_extension_host():
    workbench = evaluate_compat([("workbench.desktop.main.js", "plain")])
    assert _rule(workbench, "rpcRewrite")["status"] == "missing"

    pending = evaluate_compat([("extensionHostProcess.js", "function x(){}")])
    row = _rule(pending, "rpcRewrite")
    assert row["status"] == "pending"
    assert pending["packages"][0]["canPatch"] == ["rpcRewrite"]

    rel = evaluate_compat(
        [("out/vs/workbench/api/node/extensionHostProcess.js", "function x(){}")]
    )
    row = _rule(rel, "rpcRewrite")
    assert row["status"] == "pending"
    assert row["files"] == ["out/vs/workbench/api/node/extensionHostProcess.js"]

    marked = evaluate_compat(
        [
            (
                "extensionHostProcess.js",
                SAND_RPC_REWRITE_MARKER
                + 'function catalogUrl(u){return /AvailableModels/.test(u)}'
                + 'set("x-sand-box-namespace","prod");set("x-cursor-client-version","0.18.0")',
            )
        ]
    )
    assert _rule(marked, "rpcRewrite")["status"] == "applied"


def test_rpc_partial_across_host_and_worker():
    data = evaluate_compat(
        [
            ("extensionHostProcess.js", SAND_RPC_REWRITE_MARKER),
            ("extensionHostWorkerMain.js", "plain"),
        ]
    )
    row = _rule(data, "rpcRewrite")
    assert row["status"] == "partial"
    assert row["statusLabel"] == "部分生效"


def test_packages_keep_relative_main_js():
    data = evaluate_compat(
        [
            ("extensions/cursor-always-local/dist/main.js", _direct_src()),
            ("extensions/cursor-agent-exec/dist/main.js", "noop"),
        ]
    )
    names = [pkg["name"] for pkg in data["packages"]]
    assert names == [
        "extensions/cursor-always-local/dist/main.js",
        "extensions/cursor-agent-exec/dist/main.js",
    ]
    assert "directStream" in data["packages"][0]["canPatch"]
    assert data["packages"][1]["patchable"] is False


def test_adjust_compat_stream_marks_l5_l6_optional():
    data = evaluate_compat(
        [("workbench.desktop.main.js", "x")],
        profile="full",
        include_subagent=True,
    )
    assert _rule(data, "moveExec")["optional"] is False
    assert _rule(data, "taskTool")["optional"] is False

    stream = adjust_compat_scope(data, profile="stream", include_subagent=True)
    assert _rule(stream, "moveExec")["optional"] is True
    assert _rule(stream, "taskTool")["optional"] is True
    assert "工具执行器" not in stream["summary"]["missing"]
    assert "Task V3" not in stream["summary"]["missing"]
    assert stream["notes"][0]["title"] == "请求头伪装"

    no_l6 = adjust_compat_scope(data, profile="full", include_subagent=False)
    assert _rule(no_l6, "moveExec")["optional"] is False
    assert _rule(no_l6, "taskTool")["optional"] is True


def test_version_hint_matches_tested_builds():
    for ver in ("3.18.9", "3.18.25", "3.19.13"):
        data = evaluate_compat([], cursor_version=ver)
        assert data["versionOk"] is True
        assert data["versionHint"] == ""
        assert data["upgrade"]["relation"] == "match"
    old = evaluate_compat([], cursor_version="2.0.0")
    assert old["versionOk"] is False
    assert old["upgrade"]["relation"] == "older"
    current_318 = evaluate_compat([], cursor_version=ANCHOR_VERSION)
    assert current_318["versionOk"] is True
    assert current_318["versionHint"] == ""
    untested = evaluate_compat([], cursor_version="3.18.30")
    assert untested["versionOk"] is False
    assert untested["upgrade"]["relation"] == "same-track"
    assert "同族未测" in untested["versionHint"]
    v319 = evaluate_compat([], cursor_version="3.19.13")
    assert v319["patchTrack"] == "3.19"
    assert "3.19.13" in v319["anchorVersion"]


def test_319_l6_leftovers_are_pending_not_feature_absent():
    src = (
        'isHostedSubagentChild:Boolean(e.runOptions.subagentTypeName||e.runOptions.parentAgentToolCallId)'
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        "function(e){return e.requestedMode===o.xy.AGENT||"
        "e.isHostedSubagentChild&&e.requestedMode===o.xy.UNSPECIFIED}(e)?"
        'e.simulatedUserMessage?"simulated-message-not-supported":y(e,r):"mode-not-supported"'
        "outputNotificationLimit:1e3,useClientSideSubagent:!0}"
        "isGenerateImageModelRestricted:!1,taskToolProps:Ne({parentModelId:null!=p?p:n.modelName,modelInfo:n})},resolvers:"
        "e.resumeAgentId&&e.mode===Mn.FL.UNSPECIFIED&&!e.readonly?o.xy.UNSPECIFIED:"
    )
    data = evaluate_compat([("extensions/cursor-agent-host/dist/main.js", src)])
    assert _rule(data, "subagentRoute")["status"] == "pending"
    assert _rule(data, "actionRoute")["status"] == "pending"
    assert _rule(data, "subagentSession")["status"] == "pending"
    assert _rule(data, "taskTool")["status"] == "pending"
    assert _rule(data, "resumeMode")["status"] == "pending"


def test_agent_ide_pending_then_applied():
    src = "return{headers:e,credentialFingerprint:t}"
    row = _rule(evaluate_compat([("workbench.desktop.main.js", src)]), "agentIde")
    assert row["status"] == "pending"
    patched, _ = apply_patch_to_content(src, profile="stream")
    assert SAND_AGENT_IDE_MARKER in patched
    assert inspect_content_hits(patched)["agentIde"] >= 1
    row = _rule(evaluate_compat([("workbench.desktop.main.js", patched)]), "agentIde")
    assert row["status"] == "applied"
    assert "MODEL_MEMBERSHIP_SPOOF" not in patched
    assert "SAND_MEMBERSHIP_SPOOF" not in patched


def test_agent_ide_missing_without_fingerprint():
    row = _rule(evaluate_compat([("workbench.desktop.main.js", "console.log(1)")]), "agentIde")
    assert row["status"] == "missing"
    assert row["missKind"] == "feature_absent"


def test_rpc_stale_without_catalog_is_partial():
    row = _rule(
        evaluate_compat(
            [("extensionHostProcess.js", "head" + SAND_RPC_REWRITE_MARKER + "tail")]
        ),
        "rpcRewrite",
    )
    assert row["status"] == "partial"
    assert "目录" in (row["fix"] or "")


def test_rpc_current_sand_rpc_js_is_applied():
    from pathlib import Path

    from launcher.sand_stream import _rpc_snippet

    snippet = _rpc_snippet()
    assert "catalogUrl" in snippet
    row = _rule(evaluate_compat([("extensionHostProcess.js", snippet)]), "rpcRewrite")
    assert row["status"] == "applied"
    assert Path(__file__).resolve().parent.parent.joinpath("launcher", "sand_rpc.js").is_file()


def test_membership_fetch_is_optional_and_read_only():
    empty = evaluate_compat([("workbench.desktop.main.js", "plain")])
    row = _rule(empty, "membershipFetch")
    assert row["status"] == "pending"
    assert row["optional"] is True
    assert row["title"] not in empty["summary"]["missing"]
    assert "membershipFetch" not in empty["packages"][0]["canPatch"]
    assert empty["packages"][0]["patchable"] is False
    assert "fetch" in empty["packages"][0]["roles"]

    marked = evaluate_compat(
        [("workbench.desktop.main.js", "/*MODEL_MEMBERSHIP_SPOOF_V1*/(function(){})();")]
    )
    row = _rule(marked, "membershipFetch")
    assert row["status"] == "applied"
    assert row["optional"] is True


def test_header_layers_and_package_roles():
    data = evaluate_compat(
        [
            ("workbench.desktop.main.js", 'g.header.set("x-cursor-client-type","ide");'),
            ("extensionHostProcess.js", "function x(){}"),
        ],
        cursor_version="3.12.30",
    )
    layers = data["headerLayers"]
    assert layers["relation"] == "older"
    keys = [row["key"] for row in layers["rows"]]
    assert keys == ["hdrfixV2", "rpcRewrite", "agentIde", "membershipFetch"]
    assert _rule(data, "managedLocalRoute")["missKind"] == "package_absent"
    assert _rule(data, "rpcRewrite")["status"] == "pending"
    assert _rule(data, "rpcRewrite")["missKind"] != "package_absent"

    host = next(pkg for pkg in data["packages"] if pkg["name"].endswith("extensionHostProcess.js"))
    assert "header" in host["roles"]
    assert host["canPatch"] == ["rpcRewrite"]

    wb = next(pkg for pkg in data["packages"] if pkg["name"].endswith("workbench.desktop.main.js"))
    assert "header" in wb["roles"]
    assert "hdrfixV2" in wb["canPatch"]
    assert "membershipFetch" not in wb["canPatch"]


def test_evaluate_compat_marks_direct_stream_missing_without_anchor():
    data = evaluate_compat([("workbench.desktop.main.js", "x" * 8000)])
    assert _rule(data, "directStream")["status"] == "missing"
