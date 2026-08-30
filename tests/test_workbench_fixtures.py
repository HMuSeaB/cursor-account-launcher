"""Regression against real Cursor workbench pattern windows."""

from pathlib import Path

from launcher.model_unlock import apply_show_max_to_content, apply_to_content
from launcher.workbench.layers import scan_content
from launcher.workbench.preflight import validate_content

FIXTURE = Path(__file__).parent / "fixtures" / "workbench_snippets.js"


def test_fixture_exists_and_usable():
    assert FIXTURE.is_file(), "run scripts/extract-wb-fixtures.py first"
    text = FIXTURE.read_text(encoding="utf-8")
    assert "hideMaxToggle" in text or "43111" in text


def test_show_max_on_fixture_windows():
    raw = FIXTURE.read_text(encoding="utf-8")
    # apply only to chunks that still have unpatched hideMaxToggle
    applied = 0
    for chunk in raw.split("\n---\n"):
        if "hideMaxToggle:" not in chunk or "MODEL_SHOW_MAX" in chunk:
            continue
        if "hideMaxToggle:!1" in chunk:
            continue
        patched, stats = apply_show_max_to_content(chunk)
        if not stats.show_max:
            continue
        applied += 1
        assert "hideMaxToggle:!1;" not in patched
        assert "MODEL_SHOW_MAX_V1" in patched
        # 片段窗口本身括号不全，只查黑屏类问题
        issues = [
            i
            for i in validate_content(patched)
            if "hideMaxToggle" in i or "会员短路" in i
        ]
        assert not issues
    assert applied >= 1



def test_full_apply_does_not_mass_mem_on_fixture():
    raw = FIXTURE.read_text(encoding="utf-8")
    # concatenate as a mini corpus — must not explode mem hits
    patched, stats = apply_to_content(raw, "pro")
    assert stats.mem_pro <= 4
    scan = scan_content(patched)
    assert scan.mem_pro <= 4
