"""ctxwin patch helpers."""

from pathlib import Path

from launcher.ctxwin import FROM_TOKENS, MARK_START, TO_TOKENS, file_has_patch, find_node


def test_mark_detected_at_file_start(tmp_path: Path):
    target = tmp_path / "extensionHostProcess.js"
    target.write_bytes((MARK_START + "\nrest of file").encode("utf-8"))
    assert file_has_patch(target) is True


def test_clean_file_has_no_mark(tmp_path: Path):
    target = tmp_path / "extensionHostProcess.js"
    target.write_bytes(b"not patched at all")
    assert file_has_patch(target) is False


def test_mark_detected_past_first_chunk(tmp_path: Path):
    target = tmp_path / "extensionHostProcess.js"
    target.write_bytes(b"x" * (300 * 1024) + MARK_START.encode("ascii") + b"tail")
    assert file_has_patch(target) is True


def test_unpatched_large_file_only_reads_head(tmp_path: Path):
    target = tmp_path / "extensionHostProcess.js"
    target.write_bytes(b"x" * (600 * 1024))
    assert file_has_patch(target) is False


def test_window_token_sizes_match_script():
    assert FROM_TOKENS == 256000
    assert TO_TOKENS == 500000


def test_find_node_returns_existing_file_or_none():
    node = find_node()
    if node is not None:
        assert node.is_file()


def test_bundled_script_exists():
    from launcher.ctxwin import bundled_script

    assert bundled_script().is_file()
