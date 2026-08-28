"""启动器窗口位置 / 尺寸记忆。"""

from __future__ import annotations

import sys
import threading
from typing import Any

from launcher.cursor_process import _load_config, update_config

MIN_WIDTH = 900
MIN_HEIGHT = 640
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 760


def virtual_screen() -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        vx = int(user32.GetSystemMetrics(76))
        vy = int(user32.GetSystemMetrics(77))
        vw = int(user32.GetSystemMetrics(78))
        vh = int(user32.GetSystemMetrics(79))
        if vw <= 0 or vh <= 0:
            return None
        return (vx, vy, vw, vh)
    except Exception:
        return None


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def geom_visible(x: int, y: int, width: int, height: int, screen: tuple[int, int, int, int]) -> bool:
    vx, vy, vw, vh = screen
    return not (
        x + width < vx + 40
        or y + height < vy + 40
        or x > vx + vw - 40
        or y > vy + vh - 40
    )


def parse_window_geom(cfg: dict, screen: tuple[int, int, int, int] | None = None) -> dict:
    width = max(MIN_WIDTH, _to_int(cfg.get("windowWidth"), DEFAULT_WIDTH))
    height = max(MIN_HEIGHT, _to_int(cfg.get("windowHeight"), DEFAULT_HEIGHT))
    maximized = bool(cfg.get("windowMaximized"))
    has_pos = cfg.get("windowX") is not None and cfg.get("windowY") is not None
    x = _to_int(cfg.get("windowX"), 0) if has_pos else None
    y = _to_int(cfg.get("windowY"), 0) if has_pos else None
    if has_pos and screen is not None and x is not None and y is not None:
        if not geom_visible(x, y, width, height, screen):
            x, y = None, None
    return {
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "maximized": maximized,
    }


def load_window_geom() -> dict:
    return parse_window_geom(_load_config(), virtual_screen())


def attach_window_persistence(window) -> None:
    """记住大小、位置、是否最大化。最大化时不覆盖还原尺寸。"""
    state = {"max": bool(_load_config().get("windowMaximized")), "timer": None}
    lock = threading.Lock()

    def cancel_timer() -> None:
        timer = state["timer"]
        if timer is not None:
            timer.cancel()
            state["timer"] = None

    def save(*, flush: bool = False, maximized: bool | None = None) -> None:
        def write() -> None:
            payload: dict[str, Any] = {}
            if maximized is True:
                payload["windowMaximized"] = True
            else:
                if maximized is False or not state["max"]:
                    try:
                        payload["windowWidth"] = max(MIN_WIDTH, int(window.width))
                        payload["windowHeight"] = max(MIN_HEIGHT, int(window.height))
                        payload["windowX"] = int(window.x)
                        payload["windowY"] = int(window.y)
                    except Exception:
                        pass
                if maximized is False:
                    payload["windowMaximized"] = False
                elif maximized is None and not state["max"]:
                    payload["windowMaximized"] = False
            if payload:
                update_config(**payload)

        with lock:
            cancel_timer()
            if flush:
                write()
                return
            timer = threading.Timer(0.45, write)
            timer.daemon = True
            state["timer"] = timer
            timer.start()

    def on_resized(_w=None, _h=None) -> None:
        if state["max"]:
            return
        save()

    def on_moved(_x=None, _y=None) -> None:
        if state["max"]:
            return
        save()

    def on_maximized() -> None:
        state["max"] = True
        save(flush=True, maximized=True)

    def on_restored() -> None:
        state["max"] = False
        save(flush=True, maximized=False)

    def on_closing() -> None:
        save(flush=True, maximized=True if state["max"] else False)

    window.events.resized += on_resized
    window.events.moved += on_moved
    window.events.maximized += on_maximized
    window.events.restored += on_restored
    window.events.closing += on_closing
