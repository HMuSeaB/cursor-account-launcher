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
# 环境变量 NO_PROXY 必须是逗号分隔字符串；settings 的 http.noProxy 必须是数组
# （Cursor 主进程会对它 .map，写成字符串会直接炸成黑屏/闪退）
NO_PROXY_HOSTS = ("localhost", "127.0.0.1", "::1")
NO_PROXY = ",".join(NO_PROXY_HOSTS)
SETTINGS_NO_PROXY = list(NO_PROXY_HOSTS)
ARGV_HEADER = "// Cursor argv.json — proxy-server 由 Cursor Launcher 管理，改完请重启 Cursor。\n"
SETTINGS_SLICE_NAME = "settings-proxy-keys.json"
ARGV_BACKUP_NAME = "argv.json"
META_NAME = "meta.json"


def _proxy_backup_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "proxy-backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def proxy_backup_status() -> dict:
    bak = _proxy_backup_dir()
    has_settings = (bak / SETTINGS_SLICE_NAME).is_file()
    has_argv = (bak / ARGV_BACKUP_NAME).is_file()
    meta: dict[str, Any] = {}
    meta_path = bak / META_NAME
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return {
        "ok": True,
        "hasBackup": has_settings or has_argv,
        "hasSettingsSlice": has_settings,
        "hasArgv": has_argv,
        "dir": str(bak),
        "savedAt": meta.get("savedAt") or "",
    }


def snapshot_before_proxy_write() -> dict:
    """写入前备份 settings 代理键 + 完整 argv，供一键还原。"""
    from datetime import datetime, timezone

    bak = _proxy_backup_dir()
    settings = _load_settings()
    slice_data = {k: settings[k] for k in SETTINGS_PROXY_KEYS if k in settings}
    # 用哨兵区分「从未有过这些键」与「键值为 null」
    payload = {"_keys_present": list(slice_data.keys()), "values": slice_data}
    (bak / SETTINGS_SLICE_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    argv_path = argv_json_path()
    argv_copied = False
    if argv_path.is_file():
        (bak / ARGV_BACKUP_NAME).write_text(
            argv_path.read_text(encoding="utf-8-sig"),
            encoding="utf-8",
        )
        argv_copied = True
    else:
        # 没有 argv 时记空对象，还原时清掉我们加的键
        (bak / ARGV_BACKUP_NAME).write_text(
            ARGV_HEADER + "{\n}\n",
            encoding="utf-8",
        )
    meta = {
        "savedAt": datetime.now(timezone.utc).isoformat(),
        "settingsPath": settings_json_path() or "",
        "argvPath": str(argv_path),
        "argvExisted": argv_copied,
    }
    (bak / META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "backup": proxy_backup_status()}


def restore_proxy_files() -> dict:
    """把上次写入前的 settings 代理键与 argv 还原回去。"""
    st = proxy_backup_status()
    if not st.get("hasBackup"):
        return {"ok": False, "error": "没有代理写入备份。先成功「保存」过一次才会留下快照。"}
    bak = _proxy_backup_dir()
    restored: list[str] = []

    slice_path = bak / SETTINGS_SLICE_NAME
    if slice_path.is_file():
        try:
            payload = json.loads(slice_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"无法读取 settings 备份：{exc}"}
        settings = _load_settings()
        path = settings_json_path()
        if not settings and path and os.path.isfile(path):
            return {
                "ok": False,
                "error": "无法解析当前 settings.json，已跳过以免覆盖其它配置",
            }
        present = set(payload.get("_keys_present") or [])
        values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
        # 先清掉启动器会写的全部代理键
        for key in SETTINGS_PROXY_KEYS:
            settings.pop(key, None)
        # 再放回备份里原先存在的键
        for key in present:
            if key in values:
                settings[key] = values[key]
        # 若备份里残留字符串 noProxy，一并修成数组，避免还原后仍崩
        normalize_settings_no_proxy(settings)
        if isinstance(settings.get("http.noProxy"), str):
            settings.pop("http.noProxy", None)
        _save_settings(settings)
        restored.append("settings.json")

    argv_bak = bak / ARGV_BACKUP_NAME
    if argv_bak.is_file():
        target = argv_json_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            text = argv_bak.read_text(encoding="utf-8-sig")
            # 备份可能是带注释的 jsonc；直接原样写回
            tmp = target.with_suffix(".tmp")
            tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            tmp.replace(target)
            restored.append("argv.json")
        except OSError as exc:
            return {"ok": False, "error": str(exc), "restored": restored}

    return {
        "ok": True,
        "restored": restored,
        "message": "已还原代理写入前的 settings/argv" if restored else "备份为空，无需还原",
    }


@dataclass
class ProxyConfig:
    enabled: bool = False
    proxy_type: str = "socks5"  # http | socks5（进程 DLL 推荐 socks5）
    host: str = "127.0.0.1"
    port: int = 7891
    strict_ssl: bool = False
    apply_on_launch: bool = False
    bypass_gateway: bool = False
    process_hook: bool = False
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
            # 缺省关闭：避免残缺 proxy.json 被当成「开着」而在启动时乱写 settings
            enabled=bool(data.get("enabled", False)),
            proxy_type=str(data.get("proxy_type") or data.get("proxyType") or "socks5"),
            host=str(data.get("host") or "127.0.0.1"),
            port=int(data.get("port") or 7891),
            strict_ssl=bool(data.get("strict_ssl", data.get("strictSsl", False))),
            apply_on_launch=bool(data.get("apply_on_launch", data.get("applyOnLaunch", False))),
            # 默认网关原生（不改 workbench）；改回官方需用户显式选 clash
            bypass_gateway=bool(data.get("bypass_gateway", data.get("bypassGateway", False))),
            process_hook=bool(data.get("process_hook", data.get("processHook", False))),
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


def normalize_settings_no_proxy(settings: dict[str, Any]) -> bool:
    """把错误的字符串 http.noProxy 修成数组；返回是否改过。"""
    raw = settings.get("http.noProxy")
    if raw is None:
        return False
    if isinstance(raw, list):
        cleaned = [str(x).strip() for x in raw if str(x).strip()]
        if cleaned == list(raw):
            return False
        settings["http.noProxy"] = cleaned or list(SETTINGS_NO_PROXY)
        return True
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        settings["http.noProxy"] = parts or list(SETTINGS_NO_PROXY)
        return True
    settings["http.noProxy"] = list(SETTINGS_NO_PROXY)
    return True


def apply_proxy(config: ProxyConfig) -> dict:
    """写入 settings.json 与 argv.json（仅改代理相关键）。仅应由「保存」触发，勿在每次启动时调用。"""
    path = settings_json_path()
    settings = _load_settings()
    if not settings and path and os.path.isfile(path):
        return {
            "ok": False,
            "error": "无法解析 settings.json，已跳过写入以免覆盖 cursorYc 等现有配置",
            "path": path,
        }
    snap = snapshot_before_proxy_write()
    repaired = normalize_settings_no_proxy(settings)
    if not config.enabled:
        for key in SETTINGS_PROXY_KEYS:
            settings.pop(key, None)
    else:
        settings["http.proxy"] = config.http_proxy_url()
        settings["http.proxySupport"] = "override"
        settings["http.proxyStrictSSL"] = config.strict_ssl
        settings["http.useLocalProxyConfiguration"] = True
        settings["http.electronFetch"] = True
        # Cursor 主进程对 http.noProxy 调 .map，必须是 string[]
        settings["http.noProxy"] = list(SETTINGS_NO_PROXY)
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
        "repairedNoProxy": repaired,
        "backup": snap.get("backup"),
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
