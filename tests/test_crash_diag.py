"""崩溃日志归因：纯函数测试，不读真实 Cursor 目录。"""

from launcher.crash_diag import analyze_extensions, analyze_log_text, summarize_crash


def test_extension_host_crash_names_plugin():
    log = (
        "[error] Activating extension 'evil.copilot-plus' failed: Cannot find module './native.node'\n"
        "[error] Extension host terminated unexpectedly. Code: 0\n"
    )
    findings = analyze_log_text(log)
    kinds = {f["kind"] for f in findings}
    assert "extension_activate_fail" in kinds
    assert "extension_host_crash" in kinds
    assert any("evil.copilot-plus" in f.get("extensionId", "") for f in findings)


def test_native_abi_and_gpu_and_workbench():
    log = (
        "Error: The module was compiled against a different Node.js version\n"
        "GPU process exited unexpectedly: exit_code=1\n"
        "SyntaxError: Unexpected token ';' in workbench.desktop.main.js\n"
    )
    kinds = {f["kind"] for f in analyze_log_text(log)}
    assert "native_abi" in kinds
    assert "gpu_crash" in kinds
    assert "workbench_syntax" in kinds


def test_recent_extensions_ranked_by_mtime(tmp_path):
    root = tmp_path / "extensions"
    root.mkdir()
    old = root / "old.theme-1.0.0"
    new = root / "new.crashy-2.0.0"
    old.mkdir()
    new.mkdir()
    (old / "package.json").write_text('{"name":"old.theme"}', encoding="utf-8")
    (new / "package.json").write_text('{"name":"new.crashy"}', encoding="utf-8")
    import os

    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(new, (1_800_000_000, 1_800_000_000))
    ranked = analyze_extensions(root)
    assert ranked[0]["id"] == "new.crashy"
    assert ranked[1]["id"] == "old.theme"


def test_summarize_prefers_named_extension_over_generic():
    log = (
        "Activating extension 'publisher.broken' failed: boom\n"
        "Extension host terminated unexpectedly\n"
    )
    summary = summarize_crash(analyze_log_text(log), [])
    assert summary["ok"] is True
    assert summary["likely"][0]["kind"] == "extension_activate_fail"
    assert "publisher.broken" in summary["headline"]
