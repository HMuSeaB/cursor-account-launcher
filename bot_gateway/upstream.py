"""把本机收到的 Stream 请求透传到 Box / Bot upstream。"""

from __future__ import annotations

import http.client
import ssl
from typing import Mapping, MutableMapping, Tuple
from urllib.parse import urlparse

from .config import UpstreamConfig

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _filter_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP:
            continue
        out[key] = value
    return out


def forward_stream(
    upstream: UpstreamConfig,
    *,
    method: str,
    body: bytes,
    incoming_headers: Mapping[str, str],
    timeout: float = 120.0,
) -> Tuple[int, dict[str, str], bytes]:
    """POST/透传 body 到 upstream.stream_url；返回 status, headers, body。"""
    parsed = urlparse(upstream.stream_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"非法 upstream URL: {upstream.stream_url}")

    headers = _filter_request_headers(incoming_headers)
    headers["Authorization"] = f"Bearer {upstream.token}"
    for key, value in upstream.headers.items():
        headers.setdefault(key, value)
    # Box relay 常见身份头：若上游配置未给，调用方仍可自带
    headers.setdefault("x-cursor-client-type", "sand")
    headers.setdefault("x-cursor-client-version", "0.44.0")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port or 443,
        timeout=timeout,
        context=context,
    )
    try:
        conn.request(method.upper(), path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        resp_headers: dict[str, str] = {}
        for key, value in response.getheaders():
            if key.lower() in HOP_BY_HOP:
                continue
            resp_headers[key] = value
        return response.status, resp_headers, raw
    finally:
        conn.close()


def merge_status_headers(
    status: int,
    headers: Mapping[str, str],
) -> MutableMapping[str, str]:
    out = dict(headers)
    out.setdefault("X-Bot-Gateway", "cursor-launcher-bot-gateway/0.1")
    out.setdefault("X-Bot-Gateway-Upstream-Status", str(status))
    return out
