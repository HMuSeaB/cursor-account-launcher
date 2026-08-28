"""launch args tests."""

import os
import sys

from launcher.cursor_process import launch_args, light_workspace_dir


def test_light_args_open_empty_workspace():
    args = launch_args(light=True)
    assert "--disable-gpu" in args
    assert "--classic" in args
    folder = str(light_workspace_dir())
    assert args[-1] == folder
    assert (light_workspace_dir() / "README.md").is_file()


def test_normal_args_stay_classic_only():
    assert launch_args(light=False) == ["--classic"]


def test_child_env_strips_pyinstaller_mei(monkeypatch, tmp_path):
    from launcher.cursor_process import child_env

    mei = tmp_path / "_MEI00abc"
    mei.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(mei), raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([str(mei), r"C:\Windows\System32"]))
    monkeypatch.setenv("_MEIPASS", str(mei))
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", str(tmp_path / "app.exe"))
    env = child_env({"HTTPS_PROXY": "socks5://127.0.0.1:7891"})
    assert str(mei) not in env["PATH"]
    assert "_MEIPASS" not in env
    assert "_PYI_ARCHIVE_FILE" not in env
    assert env["HTTPS_PROXY"] == "socks5://127.0.0.1:7891"


def test_configured_path_empty_by_default():
    from launcher.cursor_process import configured_cursor_path

    assert isinstance(configured_cursor_path(), str)


def test_peek_local_identity_shape():
    from launcher.local_cursor import peek_local_identity

    ident = peek_local_identity()
    assert "email" in ident
    assert "userId" in ident
    assert isinstance(ident["email"], str)
    assert isinstance(ident["userId"], str)
    assert not ident["userId"].startswith("auth0|")
