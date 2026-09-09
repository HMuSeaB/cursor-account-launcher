"""解析 / 校验与 v136 对齐的 upstream relay 配置。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_RELAY_PATH = "/sand-stream-relay/aiserver.v1.InferenceService/Stream"
CONFIG_ENV = "BOT_GATEWAY_UPSTREAM"


class GatewayConfigError(ValueError):
    """配置缺失或非法。"""


@dataclass(frozen=True)
class UpstreamConfig:
    version: int
    base_url: str
    token: str
    relay_path: str = DEFAULT_RELAY_PATH
    headers: Mapping[str, str] = field(default_factory=dict)
    account_fingerprint: str = ""
    minted_at_ms: int = 0
    refresh_after_ms: int = 3_600_000
    refresh: Optional[Mapping[str, Any]] = None
    source_path: str = ""

    @property
    def stream_url(self) -> str:
        base = self.base_url.rstrip("/") + "/"
        path = self.relay_path if self.relay_path.startswith("/") else "/" + self.relay_path
        # URL join without dropping host path segments incorrectly
        from urllib.parse import urljoin

        return urljoin(base, path.lstrip("/"))


def default_config_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "CursorLauncher" / "bot-gateway"


def default_upstream_path() -> Path:
    override = os.environ.get(CONFIG_ENV, "").strip()
    if override:
        return Path(override)
    return default_config_dir() / "upstream.json"


def _as_str_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, raw in value.items():
        if isinstance(key, str) and isinstance(raw, str) and raw:
            out[key] = raw
    return out


def parse_upstream(data: Mapping[str, Any], *, source_path: str = "") -> UpstreamConfig:
    if not isinstance(data, Mapping):
        raise GatewayConfigError("upstream 必须是 JSON 对象")
    version = data.get("version", 1)
    if version != 1:
        raise GatewayConfigError(f"不支持的 upstream.version: {version}")
    base_url = data.get("baseUrl")
    token = data.get("token")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise GatewayConfigError("baseUrl 必须是 https:// 开头的字符串")
    if not isinstance(token, str) or not token.strip():
        raise GatewayConfigError("token 不能为空")
    relay_path = data.get("relayPath") or DEFAULT_RELAY_PATH
    if not isinstance(relay_path, str) or not relay_path.startswith("/"):
        raise GatewayConfigError("relayPath 必须以 / 开头")
    refresh = data.get("refresh")
    if refresh is not None and not isinstance(refresh, dict):
        raise GatewayConfigError("refresh 必须是对象或省略")
    return UpstreamConfig(
        version=int(version),
        base_url=base_url.rstrip("/"),
        token=token.strip(),
        relay_path=relay_path,
        headers=_as_str_map(data.get("headers")),
        account_fingerprint=str(data.get("accountFingerprint") or ""),
        minted_at_ms=int(data.get("mintedAtMs") or 0),
        refresh_after_ms=int(data.get("refreshAfterMs") or 3_600_000),
        refresh=dict(refresh) if isinstance(refresh, dict) else None,
        source_path=source_path,
    )


def write_upstream_dict(data: Mapping[str, Any], path: Optional[Path] = None) -> Path:
    """校验后原子写入 upstream.json。"""
    parsed = parse_upstream(data)
    target = path or default_upstream_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": parsed.version,
        "baseUrl": parsed.base_url,
        "token": parsed.token,
        "headers": dict(parsed.headers),
        "relayPath": parsed.relay_path,
        "accountFingerprint": parsed.account_fingerprint,
        "mintedAtMs": parsed.minted_at_ms,
        "refreshAfterMs": parsed.refresh_after_ms,
    }
    if "runState" in data:
        payload["runState"] = data["runState"]
    if parsed.refresh:
        payload["refresh"] = dict(parsed.refresh)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def load_upstream(path: Optional[Path] = None) -> Optional[UpstreamConfig]:
    target = path or default_upstream_path()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GatewayConfigError(f"无法读取 upstream: {target}") from exc
    return parse_upstream(raw, source_path=str(target))


def redacted_summary(cfg: Optional[UpstreamConfig]) -> dict[str, Any]:
    if cfg is None:
        return {"configured": False}
    return {
        "configured": True,
        "version": cfg.version,
        "baseUrlHost": _host_only(cfg.base_url),
        "relayPath": cfg.relay_path,
        "accountFingerprint": cfg.account_fingerprint,
        "mintedAtMs": cfg.minted_at_ms,
        "refreshAfterMs": cfg.refresh_after_ms,
        "hasRefresh": bool(cfg.refresh),
        "headerKeys": sorted(cfg.headers.keys()),
        "sourcePath": cfg.source_path,
        # never include token
    }


def _host_only(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.netloc or "(invalid)"
