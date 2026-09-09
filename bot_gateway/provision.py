"""A：EnsureSandBox 领 Box 网关票，写入 upstream.json。

本模块只把「当前 Cursor 登录号对应的 Box HTTPS 入口 + 短票」落到本地。
在 Box 内挂 `/sand-stream-relay` 见同包 `box_mount.py`（对照 Claimer 1.4.8 / v136）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import (
    DEFAULT_RELAY_PATH,
    default_upstream_path,
    parse_upstream,
    redacted_summary,
    write_upstream_dict,
)

GROK_BACKEND_DEFAULT_URL = "https://api2.cursor.sh"


class ProvisionError(RuntimeError):
    """领取 Box 票失败。"""


def _state_db_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if sys_platform_darwin():
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def sys_platform_darwin() -> bool:
    import sys

    return sys.platform == "darwin"


def _read_state_value(key: str) -> str:
    path = _state_db_path()
    if not path.is_file():
        raise ProvisionError(f"未找到 Cursor 状态库：{path}。请先在 Cursor 登录。")
    uri = "file:" + str(path).replace("?", "%3F").replace("#", "%23") + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise ProvisionError("无法打开 Cursor 状态库") from exc
    try:
        row = con.execute("select value from ItemTable where key=? limit 1", (key,)).fetchone()
    except sqlite3.Error as exc:
        raise ProvisionError("读取 Cursor 状态库失败") from exc
    finally:
        con.close()
    if not row or row[0] is None:
        raise ProvisionError(f"Cursor 未登录或状态库缺少 {key}")
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = str(raw)
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, str):
            return decoded
    except Exception:
        pass
    return raw


def _cursor_checksum(machine_id: str) -> str:
    import base64

    epoch = int(time.time() * 1000) // 1_000_000

    def js_shr(value: int, count: int) -> int:
        v = value & 0xFFFFFFFF
        if v & 0x80000000:
            v -= 0x100000000
        return v >> (count & 31)

    raw = [
        js_shr(epoch, 40) & 255,
        js_shr(epoch, 32) & 255,
        js_shr(epoch, 24) & 255,
        js_shr(epoch, 16) & 255,
        js_shr(epoch, 8) & 255,
        epoch & 255,
    ]
    previous = 165
    for index in range(len(raw)):
        raw[index] = ((raw[index] ^ previous) + (index % 256)) & 255
        previous = raw[index]
    prefix = base64.urlsafe_b64encode(bytes(raw)).decode("ascii").rstrip("=")
    return prefix + machine_id


def _pb_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _pb_read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ProvisionError("protobuf varint 越界")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
        if shift > 70:
            raise ProvisionError("protobuf varint 过长")


def _pb_tag(field: int, wire: int) -> bytes:
    return _pb_varint((field << 3) | wire)


def pb_bool(field: int, value: bool) -> bytes:
    return _pb_tag(field, 0) + _pb_varint(1 if value else 0)


def iter_pb_fields(data: bytes):
    offset = 0
    length = len(data)
    while offset < length:
        key, offset = _pb_read_varint(data, offset)
        field = key >> 3
        wire = key & 7
        if wire == 0:
            value, offset = _pb_read_varint(data, offset)
            yield field, wire, value
        elif wire == 2:
            size, offset = _pb_read_varint(data, offset)
            end = offset + size
            if end > length:
                raise ProvisionError("protobuf 长度越界")
            yield field, wire, data[offset:end]
            offset = end
        elif wire == 1:
            yield field, wire, data[offset : offset + 8]
            offset += 8
        elif wire == 5:
            yield field, wire, data[offset : offset + 4]
            offset += 4
        else:
            raise ProvisionError(f"不支持的 protobuf wire 类型 {wire}")


def parse_ensure_sandbox(response: bytes) -> dict[str, Any]:
    gateway_url = ""
    gateway_token = ""
    network_token = ""
    run_state = 0
    for field, wire, value in iter_pb_fields(response):
        if wire == 2 and field == 10:
            gateway_url = value.decode("utf-8", errors="replace")
        elif wire == 2 and field == 11:
            gateway_token = value.decode("utf-8", errors="replace")
        elif wire == 2 and field == 4:
            network_token = value.decode("utf-8", errors="replace")
        elif wire == 0 and field == 13:
            run_state = value
    return {
        "baseUrl": gateway_url,
        "token": gateway_token,
        "networkToken": network_token,
        "runState": run_state,
    }


def grok_backend_url() -> str:
    value = (
        os.environ.get("SAND_BACKEND_URL")
        or os.environ.get("CURSOR_API_BASE_URL")
        or GROK_BACKEND_DEFAULT_URL
    )
    base = urlsplit(value)
    if base.scheme != "https" or not base.netloc:
        raise ProvisionError("Grok Bot 后端地址无效")
    return value.rstrip("/")


def grok_rpc(method_name: str, request: bytes, timeout: float = 30, retries: int = 5) -> bytes:
    access_token = _read_state_value("cursorAuth/accessToken")
    machine_id = _read_state_value("storage.serviceMachineId")
    url = grok_backend_url() + "/aiserver.v1.GrokBotService/" + method_name
    attempt = 0
    while True:
        headers = {
            "Authorization": "Bearer " + access_token,
            "Connect-Protocol-Version": "1",
            "Content-Type": "application/proto",
            "x-cursor-checksum": _cursor_checksum(machine_id),
            "x-cursor-client-type": "sand",
            "x-cursor-client-version": "0.44.0",
            "x-sand-box-namespace": "prod",
            "x-ghost-mode": "true",
            "x-request-id": str(uuid.uuid4()),
        }
        req = Request(url, data=request, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=timeout) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise ProvisionError("Grok Bot 后端响应过大")
                return body
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(4096).decode("utf-8", errors="replace")
            finally:
                exc.close()
            retryable = exc.code in (429, 500, 502, 503, 504)
            if retryable and attempt < retries:
                attempt += 1
                time.sleep(min(2**attempt, 15))
                continue
            raise ProvisionError(
                f"GrokBotService/{method_name} 失败：HTTP {exc.code} {detail[:240]}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                attempt += 1
                time.sleep(min(2**attempt, 15))
                continue
            raise ProvisionError(f"无法连接 Grok Bot 后端（{method_name}）") from exc


def probe_relay(cfg: Mapping[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    parsed = parse_upstream(cfg)
    req = Request(
        parsed.stream_url,
        data=b"",
        headers={
            "Authorization": "Bearer " + parsed.token,
            "Content-Type": "application/connect+proto",
            "Connect-Protocol-Version": "1",
            **dict(parsed.headers),
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            ctype = response.headers.get("Content-Type") or ""
            return {"ok": status == 200, "status": status, "contentType": ctype}
    except HTTPError as exc:
        ctype = ""
        try:
            ctype = exc.headers.get("Content-Type") or ""
        finally:
            exc.close()
        return {"ok": False, "status": exc.code, "contentType": ctype}
    except (URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": 0, "error": str(exc), "contentType": ""}


def provision_upstream(
    *,
    wake: bool = True,
    probe: bool = True,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """调用 EnsureSandBox，写入默认 upstream.json。"""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log("读取本机 Cursor 登录态…")
    cursor_token = _read_state_value("cursorAuth/accessToken")
    try:
        machine_id = _read_state_value("storage.serviceMachineId")
    except ProvisionError:
        machine_id = ""
    fingerprint = hashlib.sha256(cursor_token.encode("utf-8")).hexdigest()[:16]

    _log("调用 EnsureSandBox（领取当前账号的 Box 网关票）…")
    body = grok_rpc("EnsureSandBox", pb_bool(2, True) if wake else b"")
    parsed = parse_ensure_sandbox(body)
    if not str(parsed.get("baseUrl") or "").startswith("https://") or not parsed.get("token"):
        raise ProvisionError(
            "EnsureSandBox 未返回可用的 Box gateway；"
            f"runState={parsed.get('runState')}。账号可能没有 Grok Bot 资格，或 Box 未就绪。"
        )
    headers: dict[str, str] = {}
    if parsed.get("networkToken"):
        headers["x-anyrun-network-token"] = str(parsed["networkToken"])
    payload: dict[str, Any] = {
        "version": 1,
        "baseUrl": parsed["baseUrl"],
        "token": parsed["token"],
        "headers": headers,
        "relayPath": DEFAULT_RELAY_PATH,
        "accountFingerprint": fingerprint,
        "runState": parsed.get("runState") or 0,
        "mintedAtMs": int(time.time() * 1000),
        "refreshAfterMs": 3_600_000,
        "refresh": {
            "backendUrl": grok_backend_url(),
            "accessToken": cursor_token,
            "machineId": machine_id,
        },
    }
    path = write_upstream_dict(payload)
    _log(f"已写入 {path}")

    probe_info: Optional[dict[str, Any]] = None
    if probe:
        _log("探测 Box 上 /sand-stream-relay 是否已挂路由…")
        probe_info = probe_relay(payload)
        status = int(probe_info.get("status") or 0)
        if probe_info.get("ok"):
            note = "Box relay 路由已可转发"
        elif status == 404:
            note = (
                "票已领到，但 Box 上还没有 /sand-stream-relay 路由（常见 404）。"
                "本机网关可以转发，上游仍会 404，直到该 Box 按 v136 方式挂过一次路由。"
            )
        elif status in (401, 403):
            note = "Box 拒绝鉴权：票可能过期，或账号无资格。可再点一次领取。"
        else:
            note = f"探测 HTTP {status or probe_info.get('error')}"
    else:
        note = "已跳过探测"

    cfg = parse_upstream(payload, source_path=str(path))
    return {
        "ok": True,
        "path": str(path),
        "runState": parsed.get("runState"),
        "probe": probe_info,
        "upstream": redacted_summary(cfg),
        "note": note,
    }
