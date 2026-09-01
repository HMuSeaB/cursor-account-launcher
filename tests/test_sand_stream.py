"""sand_stream: 补丁逻辑单元测试（不碰真实 Cursor 安装）。"""

from launcher.sand_stream import (
    AGENT_HOST_IDENTITY_ORIGINAL,
    AGENT_HOST_IDENTITY_PATCHED,
    DIRECT_STREAM_ANCHOR,
    LAUNCHER_SAND_MARKER,
    LOCAL_RUNTIME_LOAD_ORIGINAL,
    LOCAL_RUNTIME_LOAD_PATCHED,
    MANAGED_LOCAL_ROUTE_ORIGINAL,
    MANAGED_LOCAL_ROUTE_PATCHED,
    SAND_AGENT_HOST_ENABLEMENT_MARKER,
    SAND_CLIENT_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_ELIGIBILITY_MARKER,
    apply_patch_to_content,
    remove_patch_from_content,
)


def _minimal_bundle() -> str:
    return (
        'header.set("x-cursor-client-type", foo ?? "ide");'
        + "function r4g(e){const{adminSettingsService:t"
        + MANAGED_LOCAL_ROUTE_ORIGINAL
        + LOCAL_RUNTIME_LOAD_ORIGINAL
        + AGENT_HOST_IDENTITY_ORIGINAL
        + DIRECT_STREAM_ANCHOR
        + "yield 1;};};"
        + "this._agentHostEnabled=x,"
    )


def test_apply_injects_stream_markers():
    src = _minimal_bundle()
    patched, stats = apply_patch_to_content(src)
    assert SAND_CLIENT_MARKER in patched
    assert SAND_ELIGIBILITY_MARKER in patched
    assert SAND_DIRECT_STREAM_MARKER in patched
    assert MANAGED_LOCAL_ROUTE_PATCHED in patched
    assert LOCAL_RUNTIME_LOAD_PATCHED in patched
    assert AGENT_HOST_IDENTITY_PATCHED in patched
    assert SAND_AGENT_HOST_ENABLEMENT_MARKER in patched
    assert stats.direct_stream == 1
    assert stats.managed_local_route == 1
    assert 'x-cursor-client-type","sand"' in patched or "sand" in patched


def test_remove_restores_ide_identity():
    src = _minimal_bundle()
    patched, _ = apply_patch_to_content(src)
    restored, stats = remove_patch_from_content(patched)
    assert SAND_DIRECT_STREAM_MARKER not in restored
    assert MANAGED_LOCAL_ROUTE_ORIGINAL in restored
    assert AGENT_HOST_IDENTITY_ORIGINAL in restored
    assert stats.direct_stream >= 1


def test_launcher_marker_roundtrip():
    src = LAUNCHER_SAND_MARKER + _minimal_bundle()
    restored, _ = remove_patch_from_content(src)
    assert LAUNCHER_SAND_MARKER not in restored


def test_idempotent_apply():
    src = _minimal_bundle()
    first, _ = apply_patch_to_content(src)
    second, stats2 = apply_patch_to_content(first)
    assert second == first
    assert stats2.direct_stream == 0
