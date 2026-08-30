"""model_unlock: 不依赖 Sand 的模型选择器解锁。"""

from launcher.model_unlock import (
    MARKER_CATALOG,
    MARKER_FETCH,
    MARKER_FULL,
    MARKER_MAX,
    MARKER_MEM,
    MARKER_MODEL,
    MARKER_NAMED,
    MARKER_SHOW_MAX,
    MARKER_TREAT,
    apply_show_max_to_content,
    apply_to_content,
    remove_from_content,
)


SAMPLE = (
    "foo(hasResolvedTeamMembership:e,teamId:t}){return e===a.FREE&&t&&n===void 0}"
    "function NYf({isAuthSettling:e,isPotentiallyFreeUserModelPickerLocked:t,"
    "isFreeUserMembershipConfirmedToAllowFullPicker:n,isRestrictedModelPicker:i})"
    "{return!e&&!i&&(!t||n)}"
    "function LYf({group:e,isConfirmedFreeUser:t,isStatsigIdentityReady:n})"
    '{return t&&n&&e==="treatment"}'
    "function lYf(e,t){return e.some(n=>X4d(n)&&n.defaultOn!==!1&&n.namedModelSectionIndex!==void 0&&(t===void 0||t(n)))}"
    "function Lfg(e){const t=kRs(e);return t.variants=t.variants??[],t.parameterDefinitions=t.parameterDefinitions??[],t}"
    "hideMaxToggle:C()||E(),hideMaxToggle:S()||k(),hideMaxToggle:Ee||j,"
    "bar(_membershipType=()=>this.storageService.get("
    "baz(hasValidPaymentMethod=async()=>{const x=1;})"
)


def test_apply_and_remove_roundtrip():
    patched, stats = apply_to_content(SAMPLE)
    assert stats.model_lock == 1
    assert stats.full_picker == 1
    assert stats.treatment == 1
    assert stats.named_view == 1
    assert stats.catalog == 1
    assert stats.show_max == 3
    assert stats.mem_pro == 1
    assert stats.maxmode == 1
    assert stats.fetch == 1
    assert MARKER_SHOW_MAX in patched
    assert "hideMaxToggle:!1" + MARKER_SHOW_MAX in patched
    assert "hideMaxToggle:!1;" not in patched
    assert "/*ORIG:C()||E()*/" in patched
    assert "hideMaxToggle:C()||E()" not in patched

    restored, rstats = remove_from_content(patched)
    assert rstats.show_max == 3
    assert MARKER_SHOW_MAX not in restored
    assert "hideMaxToggle:C()||E()" in restored
    assert "hideMaxToggle:Ee||j" in restored


def test_idempotent_second_apply():
    once, _ = apply_to_content(SAMPLE)
    twice, stats = apply_to_content(once)
    assert once.count(MARKER_SHOW_MAX) == twice.count(MARKER_SHOW_MAX) == 3
    assert stats.show_max == 0


def test_upgrades_existing_pro_membership_short_circuit():
    src = '_membershipType=()=>"enterprise"||' + MARKER_MEM + "this.storageService.get("
    patched, stats = apply_to_content(src, "pro")
    assert stats.mem_pro == 1
    assert '"pro"||' + MARKER_MEM in patched
    assert '"enterprise"||' + MARKER_MEM not in patched


def test_mem_regex_does_not_mass_inject_on_pro_strings():
    src = '"profile","pro","enterprise","prometheus"'
    patched, stats = apply_to_content(src, "pro")
    assert stats.mem_pro == 0
    assert MARKER_MEM not in patched


def test_mem_inject_only_at_membership_getter():
    src = '_membershipType=()=>this.storageService.get('
    patched, stats = apply_to_content(src, "ultra")
    assert stats.mem_pro == 1
    assert '"ultra"||' + MARKER_MEM in patched
    assert patched.count(MARKER_MEM) == 1


def test_membership_level_in_fetch_snippet():
    patched, _ = apply_to_content("plain", "ultra")
    assert 'membershipType:"ultra"' in patched
    patched2, _ = apply_to_content(patched, "pro")
    assert 'membershipType:"pro"' in patched2
    assert 'membershipType:"ultra"' not in patched2


def test_max_only_skips_mem_and_fetch():
    src = (
        '"profile","pro"'
        "hideMaxToggle:C()||E(),"
        "bar(_membershipType=()=>this.storageService.get("
    )
    patched, stats = apply_to_content(src, max_only=True)
    assert stats.show_max == 1
    assert stats.mem_pro == 0
    assert stats.fetch == 0
    assert MARKER_MEM not in patched
    assert MARKER_FETCH not in patched
    assert "hideMaxToggle:!1" + MARKER_SHOW_MAX in patched


def test_no_sand_identity_in_snippet():
    patched, _ = apply_to_content("plain")
    assert MARKER_FETCH in patched
    assert 'x-cursor-client-type":"sand"' not in patched


def test_show_max_on_real_312_snippet():
    desktop = "hideMaxToggle:C()||E(),other:!0"
    glass = "hideMaxToggle:S()||k(),hideMaxToggle:Ee||j,"
    for src, n in ((desktop, 1), (glass, 2)):
        patched, stats = apply_to_content(src)
        assert stats.show_max == n
        assert "hideMaxToggle:!1" + MARKER_SHOW_MAX in patched
        assert "hideMaxToggle:!1;" not in patched
        restored, _ = remove_from_content(patched)
        assert src in restored or all(part in restored for part in src.split(",") if part)


def test_show_max_keeps_object_literal_valid():
    src = "const o={hideAutoToggle:!0,hideMaxToggle:C()||E(),hideSearchBar:!1};"
    patched, stats = apply_to_content(src)
    assert stats.show_max == 1
    assert "hideMaxToggle:!1;" not in patched
    obj = patched[patched.find("{") : patched.rfind("}") + 1]
    assert "hideSearchBar" in obj
    assert "hideMaxToggle:!1;" not in obj[1:-1]


def test_repairs_broken_semicolon_show_max():
    src = "hideMaxToggle:!1;" + MARKER_SHOW_MAX + "/*ORIG:C()||E()*/,z:1"
    patched, stats = apply_to_content(src)
    assert "hideMaxToggle:!1;" not in patched
    assert "hideMaxToggle:!1" + MARKER_SHOW_MAX in patched
    restored, _ = remove_from_content(patched)
    assert "hideMaxToggle:C()||E()" in restored
