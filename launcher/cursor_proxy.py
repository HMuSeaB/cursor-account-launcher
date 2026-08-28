"""向 Cursor 注入代理：settings.json + argv.json + 启动环境变量。

只写 ``http.proxy`` 不够：Agent 对话很多走 Chromium 网络栈和独立的
``cursor-bridge.exe``（Go）。后者不读 VS Code 设置，只认进程环境里的
``HTTPS_PROXY`` / ``ALL_PROXY``。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .local_cursor import settings_json_path

SETTINGS_PROXY_KEYS = (
    "http.proxy",
    "http.proxySupport",
    "http.proxyStrictSSL",
    "http.useLocalProxyConfiguration",
    "http.electronFetch",
    "http.noProxy",
    "cursorGateway.downloadProxy",
)
ARGV_PROXY_KEYS = ("proxy-server", "proxy-bypass-list", "proxy-pac-url", "no-proxy-server")
PROXY_BYPASS = "localhost;127.0.0.1;::1;<local>"
NO_PROXY = "localhost,127.0.0.1,::1"
ARGV_HEADER = "// Cursor argv.json — proxy-server 由 Cursor Launcher 管理，改完请重启 Cursor。\n"


@dataclass
class ProxyConfig:
    enabled: bool = True
    proxy_type: str = "socks5"  # http | socks5（进程 DLL 推荐 socks5）
    host: str = "127.0.0.1"
    port: int = 7891
    strict_ssl: bool = False
    apply_on_launch: bool = False
    bypass_gateway: bool = True
    process_hook: bool = True
    dll_source: str = ""

    def http_proxy_url(self) -> str:
        scheme = "socks5h" if self.proxy_type == "socks5" else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def chromium_proxy_url(self) -> str:
        scheme = "socks5" if self.proxy_type == "socks5" else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProxyConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            proxy_type=str(data.get("proxy_type") or data.get("proxyType") or "socks5"),
            host=str(data.get("host") or "127.0.0.1"),
            port=int(data.get("port") or 7891),
            strict_ssl=bool(data.get("strict_ssl", data.get("strictSsl", False))),
            apply_on_launch=bool(data.get("apply_on_launch", data.get("applyOnLaunch", False))),
            bypass_gateway=bool(data.get("bypass_gateway", data.get("bypassGateway", True))),
            process_hook=bool(data.get("process_hook", data.get("processHook", True))),
            dll_source=str(data.get("dll_source") or data.get("dllSource") or ""),
        )


def _strip_json_comments(text: str) -> str:
    """去掉 VS Code settings 的整行 // 注释；不能匹配字符串里的 http://。"""
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _load_jsonc(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        text = _strip_json_comments(target.read_text(encoding="utf-8-sig"))
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_settings() -> dict[str, Any]:
    path = settings_json_path()
    if not path:
        return {}
    return _load_jsonc(path)


def _save_settings(data: dict[str, Any]) -> None:
    path = settings_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def argv_json_path() -> Path:
    return Path.home() / ".cursor" / "argv.json"


def merge_argv_proxy(data: dict[str, Any], config: ProxyConfig) -> dict[str, Any]:
    out = dict(data)
    if not config.enabled:
        for key in ARGV_PROXY_KEYS:
            out.pop(key, None)
        return out
    out["proxy-server"] = config.chromium_proxy_url()
    out["proxy-bypass-list"] = PROXY_BYPASS
    out.pop("no-proxy-server", None)
    out.pop("proxy-pac-url", None)
    return out


def _save_argv(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent="\t")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(ARGV_HEADER + body + "\n", encoding="utf-8")
    tmp.replace(path)


def apply_argv_proxy(config: ProxyConfig, path: Path | None = None) -> dict:
    target = path or argv_json_path()
    existing = _load_jsonc(target)
    if not existing and target.is_file():
        return {
            "ok": False,
            "error": f"无法解析 {target}，已跳过以免覆盖 crash-reporter-id",
            "path": str(target),
        }
    merged = merge_argv_proxy(existing, config)
    _save_argv(target, merged)
    return {"ok": True, "path": str(target), "proxyServer": merged.get("proxy-server", "")}


def proxy_env(config: ProxyConfig) -> dict[str, str]:
    """给 Cursor.exe 及其子进程（含 cursor-bridge）用的环境变量。"""
    if not config.enabled:
        return {}
    url = config.chromium_proxy_url()
    return {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "ALL_PROXY": url,
        "NO_PROXY": NO_PROXY,
        "http_proxy": url,
        "https_proxy": url,
        "all_proxy": url,
        "no_proxy": NO_PROXY,
    }


def proxy_chromium_args(config: ProxyConfig) -> list[str]:
    if not config.enabled:
        return []
    # QUIC/HTTP3 会绕过 HTTP 代理直连；关掉后 HTTPS 才会走 CONNECT→Clash
    return [
        f"--proxy-server={config.chromium_proxy_url()}",
        f"--proxy-bypass-list={PROXY_BYPASS}",
        "--disable-quic",
        "--disable-features=Http3",
    ]


def apply_proxy(config: ProxyConfig) -> dict:
    """写入 settings.json 与 argv.json（仅改代理相关键）。"""
    path = settings_json_path()
    settings = _load_settings()
    if not settings and path and os.path.isfile(path):
        return {
            "ok": False,
            "error": "无法解析 settings.json，已跳过写入以免覆盖 cursorYc 等现有配置",
            "path": path,
        }
    if not config.enabled:
        for key in SETTINGS_PROXY_KEYS:
            settings.pop(key, None)
    else:
        settings["http.proxy"] = config.http_proxy_url()
        settings["http.proxySupport"] = "override"
        settings["http.proxyStrictSSL"] = config.strict_ssl
        settings["http.useLocalProxyConfiguration"] = True
        settings["http.electronFetch"] = True
        settings["http.noProxy"] = NO_PROXY
        if config.proxy_type == "socks5":
            settings["cursorGateway.downloadProxy"] = config.http_proxy_url()
        else:
            settings.pop("cursorGateway.downloadProxy", None)
    _save_settings(settings)
    argv = apply_argv_proxy(config)
    if not argv.get("ok"):
        return argv
    return {
        "ok": True,
        "path": settings_json_path(),
        "argvPath": argv.get("path"),
        "applied": config.to_dict(),
        "chromium": config.chromium_proxy_url() if config.enabled else "",
    }


def read_current_proxy() -> dict:
    settings = _load_settings()
    argv = _load_jsonc(argv_json_path())
    return {
        "httpProxy": settings.get("http.proxy"),
        "proxySupport": settings.get("http.proxySupport"),
        "electronFetch": settings.get("http.electronFetch"),
        "downloadProxy": settings.get("cursorGateway.downloadProxy"),
        "argvProxyServer": argv.get("proxy-server"),
    }
