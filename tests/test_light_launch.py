"""launch args tests."""

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
