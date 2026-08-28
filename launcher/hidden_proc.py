"""在 Windows 上跑控制台程序时不弹出黑框。"""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def _win_kwargs(kwargs: dict) -> dict:
    out = dict(kwargs)
    out["creationflags"] = int(out.get("creationflags") or 0) | CREATE_NO_WINDOW
    startupinfo = out.get("startupinfo") or subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    out["startupinfo"] = startupinfo
    return out


def run(args, **kwargs):
    if sys.platform == "win32":
        kwargs = _win_kwargs(kwargs)
    return subprocess.run(args, **kwargs)
