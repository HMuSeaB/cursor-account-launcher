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
