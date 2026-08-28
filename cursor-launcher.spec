# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：Cursor Launcher 单文件 exe。"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

block_cipher = None

webview_datas = collect_data_files("webview")
webview_binaries = collect_dynamic_libs("webview")
launcher_hidden = collect_submodules("launcher")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=webview_binaries,
    datas=[("web", "web"), *webview_datas],
    hiddenimports=[
        "webview",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "clr",
        *launcher_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CursorLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
