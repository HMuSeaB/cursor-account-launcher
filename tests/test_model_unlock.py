"""model_unlock: 不依赖 Sand 的模型选择器解锁。"""

from launcher.model_unlock import (
    MARKER_FETCH,
    MARKER_MAX,
    MARKER_MEM,
    MARKER_MODEL,
    apply_to_content,
    remove_from_content,
)


SAMPLE = (
    "foo(hasResolvedTeamMembership:e,teamId:t}){return e===a.FREE&&t&&n===void 0}"
    "bar(_membershipType=()=>this.storageService.get("
    "baz(hasValidPaymentMethod=async()=>{const x=1;})"
)


def test_apply_and_remove_roundtrip():
    patched, stats = apply_to_content(SAMPLE)
    assert stats.model_lock == 1
    assert stats.mem_pro == 1
    assert stats.maxmode == 1
    assert stats.fetch == 1
    assert MARKER_MODEL in patched
    assert MARKER_MEM in patched
    assert MARKER_MAX in patched
    assert MARKER_FETCH in patched
    assert "return!1;" + MARKER_MODEL in patched
    assert '"pro"||' + MARKER_MEM in patched
    assert "return!0;" + MARKER_MAX in patched
    # 不伪装 Sand
    assert "sand" not in patched.lower() or "cursor-client-type" not in patched
    assert "x-cursor-client-type" not in patched

    restored, rstats = remove_from_content(patched)
    assert rstats.model_lock == 1
    assert rstats.mem_pro == 1
    assert rstats.maxmode == 1
    assert rstats.fetch == 1
    assert MARKER_MODEL not in restored
    assert MARKER_FETCH not in restored
    assert restored == SAMPLE or (
        "return e===a.FREE" in restored and "_membershipType=()=>this.storageService" in restored
    )


def test_idempotent_second_apply():
    once, _ = apply_to_content(SAMPLE)
    twice, stats = apply_to_content(once)
    # FREE 锁不应重复插入
    assert once.count(MARKER_MODEL) == twice.count(MARKER_MODEL) == 1
    assert stats.model_lock == 0
    assert MARKER_FETCH in twice


def test_no_sand_identity_in_snippet():
    patched, _ = apply_to_content("plain")
    assert MARKER_FETCH in patched
    low = patched.lower()
    assert "client-type" not in low or "sand" not in low
    assert 'x-cursor-client-type":"sand"' not in patched
    assert "glass→sand" not in patched
    assert "isSand" not in patched
