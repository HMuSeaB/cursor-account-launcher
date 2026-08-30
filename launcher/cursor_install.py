"""Cursor 安装路径解析 — workbench / app_root 统一入口。"""

from __future__ import annotations

from pathlib import Path

from launcher.cursor_process import CursorInstall, resolve_install

WORKBENCH_NAMES = (
    "workbench.desktop.main.js",
    "workbench.glass.main.js",
)


def app_root(install_root: Path | str) -> Path:
    return Path(install_root) / "resources" / "app"


def workbench_dir(app_root_path: Path | str) -> Path:
    return Path(app_root_path) / "out" / "vs" / "workbench"


def workbench_files(
    install_root: Path | str | None = None,
    *,
    app_root_path: Path | str | None = None,
) -> list[Path]:
    """返回存在的 workbench.*.main.js 列表。"""
    root = Path(app_root_path) if app_root_path is not None else app_root(install_root or "")
    wb = workbench_dir(root)
    return [wb / name for name in WORKBENCH_NAMES if (wb / name).is_file()]


def resolve_layout() -> tuple[CursorInstall, Path, list[Path]]:
    layout = resolve_install()
    root = app_root(layout.install_root)
    files = workbench_files(app_root_path=root)
    return layout, root, files
