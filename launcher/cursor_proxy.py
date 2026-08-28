"""向 Cursor settings.json 注入/移除本地代理。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

from .local_cursor import settings_json_path


@dataclass
class ProxyConfig:
    enabled: bool = True
    proxy_type: str = "http"  # http | socks5
    host: str = "127.0.0.1"
    port: int = 7890
    strict_ssl: bool = False
    apply_on_launch: bool = False

    def http_proxy_url(self) -> str:
        scheme = "socks5" if self.proxy_type == "socks5" else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProxyConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            proxy_type=str(data.get("proxy_type") or data.get("proxyType") or "http"),
            host=str(data.get("host") or "127.0.0.1"),
            port=int(data.get("port") or 7890),
            strict_ssl=bool(data.get("strict_ssl", data.get("strictSsl", False))),
            apply_on_launch=bool(data.get("apply_on_launch", data.get("applyOnLaunch", False))),
        )


def _strip_json_comments(text: str) -> str:
    """去掉 VS Code settings 的整行 // 注释；不能匹配字符串里的 http://。"""
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _load_settings() -> dict[str, Any]:
    path = settings_json_path()
    if not path or not __import__("os").path.isfile(path):
        return {}
    try:
        text = open(path, "r", encoding="utf-8-sig").read()
        text = _strip_json_comments(text)
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data: dict[str, Any]) -> None:
    path = settings_json_path()
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def apply_proxy(config: ProxyConfig) -> dict:
    """写入 Cursor User/settings.json 代理项（仅改代理相关键，保留其它配置）。"""
    path = settings_json_path()
    import os

    settings = _load_settings()
    if not settings and path and os.path.isfile(path):
        return {
            "ok": False,
            "error": "无法解析 settings.json，已跳过写入以免覆盖 cursorYc 等现有配置",
            "path": path,
        }
    if not config.enabled:
        for key in ("http.proxy", "http.proxySupport", "http.proxyStrictSSL", "cursorGateway.downloadProxy"):
            settings.pop(key, None)
    else:
        settings["http.proxy"] = config.http_proxy_url()
        settings["http.proxySupport"] = "override"
        settings["http.proxyStrictSSL"] = config.strict_ssl
        if config.proxy_type == "socks5":
            settings["cursorGateway.downloadProxy"] = config.http_proxy_url()
    _save_settings(settings)
    return {"ok": True, "path": settings_json_path(), "applied": config.to_dict()}


def read_current_proxy() -> dict:
    settings = _load_settings()
    proxy = settings.get("http.proxy")
    return {
        "httpProxy": proxy,
        "proxySupport": settings.get("http.proxySupport"),
        "downloadProxy": settings.get("cursorGateway.downloadProxy"),
    }
