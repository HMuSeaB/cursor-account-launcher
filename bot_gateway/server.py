"""本机 HTTP 网关：/health + Stream 路径 stub/透传。"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import urlparse

from . import __version__
from .config import (
    DEFAULT_RELAY_PATH,
    UpstreamConfig,
    default_upstream_path,
    load_upstream,
    redacted_summary,
)
from .upstream import forward_stream, merge_status_headers

STREAM_PATH = DEFAULT_RELAY_PATH


class GatewayState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._upstream: Optional[UpstreamConfig] = None
        self._load_error: str = ""
        self.reload()

    def reload(self) -> None:
        with self._lock:
            try:
                self._upstream = load_upstream()
                self._load_error = ""
            except Exception as exc:  # noqa: BLE001 — surface to health
                self._upstream = None
                self._load_error = str(exc)

    @property
    def upstream(self) -> Optional[UpstreamConfig]:
        with self._lock:
            return self._upstream

    @property
    def load_error(self) -> str:
        with self._lock:
            return self._load_error

    def health(self) -> dict[str, Any]:
        cfg = self.upstream
        return {
            "ok": True,
            "service": "bot-gateway",
            "version": __version__,
            "streamPath": STREAM_PATH,
            "upstreamPath": str(default_upstream_path()),
            "upstream": redacted_summary(cfg),
            "loadError": self.load_error or None,
            "ready": cfg is not None and not self.load_error,
            "note": (
                "skeleton: ready 仅表示已加载 upstream JSON；"
                "计 Bot 额度仍依赖有效 Box/Bot 票，且勿与启动器 Direct 叠打"
            ),
        }


STATE = GatewayState()


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = f"BotGateway/{__version__}"

    def log_message(self, fmt: str, *args: Any) -> None:
        # 避免默认 stderr 打出可能含 query 的整行；只打 method+path+code 形态由调用方控制
        try:
            code = args[1] if len(args) > 1 else ""
            print(f"[bot-gateway] {self.command} {self.path} {code}")
        except Exception:
            pass

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Bot-Gateway", f"cursor-launcher-bot-gateway/{__version__}")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            if path == "/health" and self.headers.get("X-Bot-Gateway-Reload") == "1":
                STATE.reload()
            self._send_json(200, STATE.health())
            return
        self._send_json(404, {"ok": False, "error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != STREAM_PATH:
            self._send_json(404, {"ok": False, "error": "not found", "path": path})
            return
        body = self._read_body()
        upstream = STATE.upstream
        if upstream is None:
            STATE.reload()
            upstream = STATE.upstream
        if upstream is None:
            self._send_json(
                503,
                {
                    "ok": False,
                    "error": "upstream not configured",
                    "hint": (
                        f"写入 {default_upstream_path()} "
                        "（或设置 BOT_GATEWAY_UPSTREAM 指向 grok-box-relay.json），"
                        "字段对齐 v136：baseUrl + token + relayPath"
                    ),
                    "loadError": STATE.load_error or None,
                },
            )
            return
        try:
            incoming = {k: v for k, v in self.headers.items()}
            status, headers, raw = forward_stream(
                upstream,
                method="POST",
                body=body,
                incoming_headers=incoming,
            )
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                502,
                {"ok": False, "error": "upstream forward failed", "detail": str(exc)},
            )
            return
        out_headers = merge_status_headers(status, headers)
        self.send_response(status)
        for key, value in out_headers.items():
            if key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def make_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> ThreadingHTTPServer:
    host = host or os.environ.get("BOT_GATEWAY_HOST", "127.0.0.1")
    port = int(port if port is not None else os.environ.get("BOT_GATEWAY_PORT", "8765"))
    STATE.reload()
    return ThreadingHTTPServer((host, port), GatewayHandler)


def serve_forever(host: Optional[str] = None, port: Optional[int] = None) -> None:
    httpd = make_server(host, port)
    bound_host, bound_port = httpd.server_address[:2]
    health = STATE.health()
    print(
        f"[bot-gateway] listening http://{bound_host}:{bound_port}"
        f"  stream={STREAM_PATH}"
        f"  ready={health['ready']}"
    )
    print(f"[bot-gateway] upstream file: {health['upstreamPath']}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[bot-gateway] stopped")
    finally:
        httpd.server_close()
