"""本机代理探测：环境变量 / 系统代理 / 常见本地端口。"""

from __future__ import annotations

import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

# (port, preferred_type, label)
COMMON_LOCAL = (
    (7890, "http", "Clash / Mihomo HTTP"),
    (7891, "socks5", "Clash SOCKS"),
    (7897, "http", "Clash Meta mixed"),
    (10809, "http", "v2rayN HTTP"),
    (10808, "socks5", "v2rayN SOCKS"),
    (1080, "socks5", "通用 SOCKS"),
    (8080, "http", "HTTP 8080"),
    (8888, "http", "HTTP 8888"),
    (20171, "http", "其它客户端"),
    (6152, "http", "Surge"),
)


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_proxy_url(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "http://" + text
    try:
        u = urlparse(text)
    except Exception:
        return None
    if not u.hostname:
        return None
    scheme = (u.scheme or "http").lower()
    if scheme.startswith("socks5"):
        ptype = "socks5"
    elif scheme in ("http", "https"):
        ptype = "http"
    else:
        ptype = "http"
    port = u.port or (1080 if ptype == "socks5" else 8080)
    return {
        "proxy_type": ptype,
        "host": u.hostname,
        "port": int(port),
        "source": "url",
        "url": f"{ptype}://{u.hostname}:{port}",
    }


def _from_env() -> list[dict]:
    out = []
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        val = os.environ.get(key)
        if not val:
            continue
        item = _parse_proxy_url(val)
        if item:
            item["source"] = f"env:{key}"
            item["label"] = f"环境变量 {key}"
            out.append(item)
    return out


def _from_windows_system() -> list[dict]:
    if os.name != "nt":
        return []
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return []
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        finally:
            winreg.CloseKey(key)
    except Exception:
        return []
    server = str(server or "").strip()
    if not server:
        return []
    candidates = []
    if "=" in server:
        for part in server.split(";"):
            part = part.strip()
            if "=" in part:
                _, _, rhs = part.partition("=")
                candidates.append(rhs.strip())
            elif part:
                candidates.append(part)
    else:
        candidates.append(server)
    out = []
    for raw in candidates:
        item = _parse_proxy_url(raw if "://" in raw else f"http://{raw}")
        if item:
            item["source"] = "wininet"
            item["label"] = "Windows 系统代理"
            out.append(item)
    return out


def _from_clash_configs() -> list[dict]:
    homes = []
    for env in ("USERPROFILE", "HOME"):
        base = os.environ.get(env)
        if base:
            homes.append(base)
    paths = []
    for home in homes:
        paths.extend(
            [
                os.path.join(home, ".config", "clash", "config.yaml"),
                os.path.join(home, ".config", "mihomo", "config.yaml"),
                os.path.join(home, "AppData", "Roaming", "clash", "config.yaml"),
            ]
        )
    out = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        mixed = re.search(r"(?m)^\s*mixed-port:\s*(\d+)", text)
        http_port = re.search(r"(?m)^\s*port:\s*(\d+)", text)
        socks = re.search(r"(?m)^\s*socks-port:\s*(\d+)", text)
        if mixed:
            out.append(
                {
                    "proxy_type": "http",
                    "host": "127.0.0.1",
                    "port": int(mixed.group(1)),
                    "source": f"clash:{path}",
                    "label": "Clash mixed-port",
                    "url": f"http://127.0.0.1:{mixed.group(1)}",
                }
            )
        if http_port:
            out.append(
                {
                    "proxy_type": "http",
                    "host": "127.0.0.1",
                    "port": int(http_port.group(1)),
                    "source": f"clash:{path}",
                    "label": "Clash HTTP port",
                    "url": f"http://127.0.0.1:{http_port.group(1)}",
                }
            )
        if socks:
            out.append(
                {
                    "proxy_type": "socks5",
                    "host": "127.0.0.1",
                    "port": int(socks.group(1)),
                    "source": f"clash:{path}",
                    "label": "Clash SOCKS port",
                    "url": f"socks5://127.0.0.1:{socks.group(1)}",
                }
            )
    return out


def _from_listening_ports() -> list[dict]:
    out = []
    for port, ptype, label in COMMON_LOCAL:
        if _port_open("127.0.0.1", port):
            out.append(
                {
                    "proxy_type": ptype,
                    "host": "127.0.0.1",
                    "port": port,
                    "source": "portscan",
                    "label": label,
                    "url": f"{ptype}://127.0.0.1:{port}",
                    "open": True,
                }
            )
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("proxy_type"), it.get("host"), int(it.get("port") or 0))
        if key in seen or not key[2]:
            continue
        seen.add(key)
        out.append(it)
    return out


def probe_proxy(proxy_type: str, host: str, port: int, timeout: float = 4.0) -> dict:
    """用该代理请求 cursor.com，验证能否过 SSL。"""
    scheme = "socks5h" if proxy_type == "socks5" else "http"
    url = f"{scheme}://{host}:{int(port)}"
    proxies = {"http": url, "https": url}
    try:
        import requests

        resp = requests.get(
            "https://cursor.com/api/auth/sessions",
            proxies=proxies,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            allow_redirects=False,
        )
        ok = resp.status_code < 500
        return {
            "ok": ok,
            "status": resp.status_code,
            "proxy_type": proxy_type,
            "host": host,
            "port": int(port),
            "url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "proxy_type": proxy_type,
            "host": host,
            "port": int(port),
            "url": url,
        }


def detect_local_proxies(*, probe: bool = True) -> dict[str, Any]:
    """探测本机可用代理，返回 candidates + recommended。"""
    candidates = _dedupe(
        _from_env() + _from_windows_system() + _from_clash_configs() + _from_listening_ports()
    )
    for item in candidates:
        item.setdefault("open", _port_open(item["host"], int(item["port"])))

    probed = []
    if probe:
        for item in candidates:
            if not item.get("open", True) and item.get("source") == "portscan":
                continue
            result = probe_proxy(item["proxy_type"], item["host"], int(item["port"]))
            item["probe"] = result
            item["reachable"] = bool(result.get("ok"))
            probed.append(item)
    else:
        probed = candidates

    recommended = None
    reachable = [c for c in probed if c.get("reachable")]
    if reachable:
        # HTTP 优先：对本工具请求 HTTPS API 更稳，少 SSL handshake failure
        reachable.sort(key=lambda c: (0 if c.get("proxy_type") == "http" else 1, c.get("port") or 99999))
        recommended = reachable[0]
    else:
        open_ones = [c for c in probed if c.get("open")]
        if open_ones:
            open_ones.sort(key=lambda c: (0 if c.get("proxy_type") == "http" else 1, c.get("port") or 99999))
            recommended = open_ones[0]

    return {
        "ok": True,
        "candidates": probed,
        "recommended": recommended,
        "hint": (
            "对本启动器请求 cursor.com，HTTP 代理通常比 SOCKS5 更稳（少 SSL 握手失败）。"
            " SOCKS5 适合部分下载场景；若两者都通，优先填 HTTP。"
        ),
    }
