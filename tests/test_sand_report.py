"""sand_report：规则状态与可改包判定（不碰真实 Cursor 安装）。"""

from launcher.sand_report import adjust_compat_scope, evaluate_compat
from launcher.sand_stream import (
    ANCHOR_VERSION,
    DIRECT_STREAM_ANCHOR,
    SAND_DIRECT_STREAM_MARKER,
    SAND_RPC_REWRITE_MARKER,
    apply_patch_to_content,
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
    assert ANCHOR_VERSION in data["upgrade"]["advice"]
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
        [("extensionHostProcess.js", "head" + SAND_RPC_REWRITE_MARKER + "tail")]
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


def test_version_hint_against_anchor():
    old = evaluate_compat([], cursor_version="2.0.0")
    assert old["versionOk"] is False
    assert ANCHOR_VERSION in old["versionHint"]
    current = evaluate_compat([], cursor_version=ANCHOR_VERSION)
    assert current["versionOk"] is True
    assert current["versionHint"] == ""
