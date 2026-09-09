"""在云端 Box 上挂 /sand-stream-relay 路由（对照 Claimer 1.4.8 / v136）。

流程：EnsureSandBox 已有票 → createAgent → sendPrompt（改 host-main.cjs）→ 轮询探测。
不写 Cursor；不注入 applyAuthorization。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .config import DEFAULT_RELAY_PATH, default_config_dir, write_upstream_dict
from .provision import (
    ProvisionError,
    grok_rpc,
    parse_ensure_sandbox,
    pb_bool,
    provision_upstream,
)

BOX_RELAY_PROVISION_PROMPT = """
请为当前 Box 幂等安装 Cursor Sand Stream relay。开始前先检查
/home/box/sand-host/host-main.cjs：如果已经存在唯一 POST 路由
/sand-stream-relay/aiserver.v1.InferenceService/Stream，则不要重复写入，只确认
host 正在使用该版本。

若路由不存在：先备份将修改的文件；在现有 host gateway HTTP 服务的
handleRequest 中增加该唯一 POST 路由，并复用现有 isAuthorized /
SAND_GATEWAY_TOKEN 鉴权。原样接收 application/connect+proto 请求体并保持
流式转发、背压和客户端中止。转发到 backendUrl 的
/aiserver.v1.InferenceService/Stream；丢弃客户端 Authorization，调用 Box
内现有 getGrokBotToken 或 credential store 获取短期 token 后写入 Bearer；
设置 Grok Bot 0.44 sand headers；不修改 model request，不定义模型列表；
原样转发 HTTP 状态、Connect 错误响应头和响应流。不要打印、返回、保存或
暴露任何 token/credential。

完成后做不含真实生成内容的空 Connect 路由健康检查，并按当前 Box 的标准
方式重启 sand host。若没有安全挂载点，停止修改并明确报告原因。
""".strip()


def _box_gateway_url(config: Mapping[str, object], path: str) -> str:
    base = urlsplit(str(config["baseUrl"]))
    if (
        base.scheme != "https"
        or not base.netloc
        or base.username is not None
        or base.password is not None
    ):
        raise ProvisionError("Grok Bot Box gateway 地址无效")
    joined = base.path.rstrip("/") + "/" + path.lstrip("/")
    return urlunsplit((base.scheme, base.netloc, joined, "", ""))


def _box_gateway_headers(
    config: Mapping[str, object],
    extra: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    blocked = {"authorization", "host", "content-length", "transfer-encoding"}
    headers: Dict[str, str] = {}
    values = config.get("headers")
    if isinstance(values, dict):
        for name, value in values.items():
            if (
                isinstance(name, str)
                and isinstance(value, str)
                and value
                and name.casefold() not in blocked
            ):
                headers[name] = value
    headers["Authorization"] = "Bearer " + str(config["token"])
    if extra:
        overridden = {name.casefold() for name in extra}
        headers = {
            name: value
            for name, value in headers.items()
            if name.casefold() not in overridden
        }
        headers.update(extra)
    return headers


def box_http_request(
    config: Mapping[str, object],
    path: str,
    *,
    method: str,
    data: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 20,
) -> Tuple[int, Dict[str, str], bytes]:
    request = Request(
        _box_gateway_url(config, path),
        data=data,
        headers=_box_gateway_headers(config, headers),
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ProvisionError("Grok Bot Box gateway 响应过大")
            return int(getattr(response, "status", 200)), dict(response.headers.items()), body
    except HTTPError as exc:
        try:
            body = exc.read(64 * 1024)
        finally:
            exc.close()
        return exc.code, dict(exc.headers.items()), body
    except (URLError, TimeoutError, OSError) as exc:
        raise ProvisionError("无法连接当前 Grok Bot Box gateway") from exc


def connect_stream_has_end_frame(body: bytes) -> bool:
    offset = 0
    saw_end = False
    while offset + 5 <= len(body):
        flags = body[offset]
        length = int.from_bytes(body[offset + 1 : offset + 5], "big")
        offset += 5
        if offset + length > len(body):
            return False
        if flags & 0x02:
            saw_end = True
        offset += length
    return saw_end and offset == len(body)


def probe_box_relay(config: Mapping[str, object]) -> Tuple[int, str, bool]:
    status, response_headers, body = box_http_request(
        config,
        DEFAULT_RELAY_PATH,
        method="POST",
        data=b"\x00\x00\x00\x00\x00",
        headers={
            "Content-Type": "application/connect+proto",
            "Connect-Protocol-Version": "1",
            "X-Request-Id": str(uuid.uuid4()),
        },
        timeout=25,
    )
    content_type = next(
        (
            value
            for name, value in response_headers.items()
            if name.casefold() == "content-type"
        ),
        "",
    )
    relay_ok = (
        status == 200
        and content_type.casefold().startswith("application/connect+proto")
        and connect_stream_has_end_frame(body)
    )
    return status, content_type, relay_ok


def find_agent_id_in_record(value: object) -> str:
    stack = [value]
    fallback = ""
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key in ("agentId", "id"):
                candidate = current.get(key)
                if isinstance(candidate, str) and candidate:
                    if key == "agentId":
                        return candidate
                    if not fallback:
                        fallback = candidate
            for nested in current.values():
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
        elif isinstance(current, list):
            stack.extend(current)
    return fallback


def gateway_create_box_agent(config: Mapping[str, object]) -> str:
    body = json.dumps(
        {
            "name": "Cursor Sand Relay",
            "description": "Hosts the Cursor Sand Stream relay route.",
            "creationRoute": {"kind": "box"},
            "harness": "box",
            "isIntroductionSuppressed": True,
            "isKickstartRequested": False,
            "clientNonce": str(uuid.uuid4()),
            "supportsTemporalHarness": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    status, _headers, response_body = box_http_request(
        config,
        "/api/createAgent",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json", "x-sand-slim-avatars": "1"},
        timeout=30,
    )
    detail = response_body.decode("utf-8", errors="replace")
    if status < 200 or status >= 300:
        raise ProvisionError(f"在 Box 内创建 relay agent 失败：HTTP {status} {detail[:400]}")
    try:
        record = json.loads(detail)
    except Exception as exc:
        raise ProvisionError("Box 网关 createAgent 返回格式无效") from exc
    agent_id = find_agent_id_in_record(record)
    if not agent_id:
        raise ProvisionError(f"Box 网关 createAgent 未返回 agent id：{detail[:300]}")
    return agent_id


def send_box_provision_prompt(config: Mapping[str, object], agent_id: str) -> None:
    events_resp = None
    try:
        events_req = Request(
            _box_gateway_url(config, "/events"),
            headers=_box_gateway_headers(config, {"Accept": "text/event-stream"}),
            method="GET",
        )
        try:
            events_resp = urlopen(events_req, timeout=15)
        except Exception:
            events_resp = None

        body = json.dumps(
            {
                "prompt": BOX_RELAY_PROVISION_PROMPT,
                "agentId": agent_id,
                "clientNonce": str(uuid.uuid4()),
                "source": "desktop",
                "sessionId": "",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, _headers, response_body = box_http_request(
            config,
            "/api/sendPrompt",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json", "x-sand-slim-avatars": "1"},
            timeout=25,
        )
    finally:
        if events_resp is not None:
            try:
                events_resp.close()
            except Exception:
                pass
    if status < 200 or status >= 300:
        detail = response_body.decode("utf-8", errors="replace")[:400]
        raise ProvisionError(f"向 Box Agent 发送挂路由指令失败：HTTP {status} {detail}")
    try:
        response = json.loads(response_body.decode("utf-8"))
    except Exception as exc:
        raise ProvisionError("Box Agent 返回格式无效") from exc
    if not isinstance(response, dict) or response.get("accepted") is not True:
        raise ProvisionError("Box Agent 未接受挂路由指令")


def ensure_box_running(
    *,
    wait_seconds: float = 150,
    log: Optional[Callable[[str], None]] = None,
) -> int:
    deadline = time.monotonic() + wait_seconds
    run_state = 0
    while True:
        response = grok_rpc("EnsureSandBox", pb_bool(2, True))
        parsed = parse_ensure_sandbox(response)
        run_state = int(parsed.get("runState") or 0)
        if run_state == 3:
            return run_state
        if time.monotonic() >= deadline:
            return run_state
        if log:
            label = {1: "ABSENT", 2: "HIBERNATED", 4: "STARTING"}.get(run_state, str(run_state))
            log(f"Box 尚未 RUNNING（{label}），等待…")
        time.sleep(4)


def _provision_state_path() -> Path:
    return default_config_dir() / "box-relay-state.json"


def _load_provision_state() -> dict[str, Any]:
    path = _provision_state_path()
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_provision_state(state: Mapping[str, Any]) -> None:
    path = _provision_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mount_box_relay(
    config: Mapping[str, Any],
    *,
    wait_seconds: float = 240,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """在已有 upstream 票的前提下，挂 Box 内 relay 路由。"""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    status, content_type, relay_ok = probe_box_relay(config)
    _log(f"relay 探测：HTTP {status} Content-Type={content_type or 'unknown'}")
    if relay_ok:
        return {
            "ok": True,
            "result": "already-installed",
            "probe": {"status": status, "contentType": content_type, "ok": True},
            "note": "Box relay 路由已存在，无需重复挂载",
        }
    if status in (401, 403):
        raise ProvisionError("Box gateway 拒绝鉴权；请确认 Cursor 已登录且有 Grok 资格后重领票")
    if status == 200:
        raise ProvisionError(
            f"Box 返回 200 但不是 Connect 流，relay 未正确挂载；Content-Type={content_type or 'unknown'}"
        )
    if status not in (0, 404):
        raise ProvisionError(f"无法确认 Box relay 状态：HTTP {status}")

    account_fp = str(config.get("accountFingerprint") or "")
    state = _load_provision_state()
    entry = state.get(account_fp) if isinstance(state.get(account_fp), dict) else {}
    agent_id = entry.get("relayAgentId") if isinstance(entry.get("relayAgentId"), str) else ""
    last_sent_ms = (
        entry.get("lastSentMs") if isinstance(entry.get("lastSentMs"), (int, float)) else 0
    )

    _log("确认 Box 处于 RUNNING…")
    run_state = ensure_box_running(log=log)
    if run_state != 3:
        raise ProvisionError(f"Box 未进入 RUNNING（runState={run_state}）")

    # refresh ticket after wake
    refreshed = provision_upstream(wake=True, probe=False, log=None)
    if not refreshed.get("ok"):
        raise ProvisionError(refreshed.get("error") or "刷新 Box 票失败")
    # reload config from write result path via caller payload merge
    from .config import load_upstream

    cfg_obj = load_upstream()
    if cfg_obj is None:
        raise ProvisionError("刷新后仍无 upstream.json")
    config = {
        "version": 1,
        "baseUrl": cfg_obj.base_url,
        "token": cfg_obj.token,
        "headers": dict(cfg_obj.headers),
        "relayPath": cfg_obj.relay_path,
        "accountFingerprint": cfg_obj.account_fingerprint or account_fp,
    }
    account_fp = str(config.get("accountFingerprint") or account_fp)

    need_send = False
    if not agent_id:
        _log("在 Box 内创建 relay agent…")
        agent_id = gateway_create_box_agent(config)
        _log(f"relay agent：{agent_id}")
        need_send = True
    else:
        _log(f"复用 relay agent：{agent_id}")
        if (time.time() * 1000 - float(last_sent_ms or 0)) > 900_000:
            need_send = True

    if need_send:
        try:
            send_box_provision_prompt(config, agent_id)
        except ProvisionError as exc:
            if "does not exist" in str(exc):
                _log("原 agent 已失效，重新创建…")
                agent_id = gateway_create_box_agent(config)
                send_box_provision_prompt(config, agent_id)
            else:
                raise
        last_sent_ms = int(time.time() * 1000)
        _log("指令已受理，Box 正在改 host-main.cjs（可能数分钟）…")
    else:
        _log("agent 已在处理中，直接轮询…")

    state[account_fp] = {"relayAgentId": agent_id, "lastSentMs": last_sent_ms}
    _save_provision_state(state)

    deadline = time.monotonic() + wait_seconds
    started = time.monotonic()
    last_status = 404
    last_ctype = ""
    while time.monotonic() < deadline:
        time.sleep(5)
        try:
            last_status, last_ctype, relay_ok = probe_box_relay(config)
        except ProvisionError:
            continue
        _log(f"等待中（{int(time.monotonic() - started)}s）HTTP {last_status}")
        if relay_ok:
            return {
                "ok": True,
                "result": "installed",
                "agentId": agent_id,
                "probe": {"status": last_status, "contentType": last_ctype, "ok": True},
                "note": "Box relay 路由已挂载并通过探测",
            }
        if last_status in (401, 403):
            raise ProvisionError("挂载期间网关拒绝鉴权，请重领票后再试")

    return {
        "ok": True,
        "result": "provisioning",
        "agentId": agent_id,
        "probe": {"status": last_status, "contentType": last_ctype, "ok": False},
        "note": (
            "指令已发，超时内未等到 Connect 200。"
            "可稍后重跑「挂路由」复用同一 agent，不会重复创建。"
        ),
    }


def provision_and_mount(
    *,
    wait_seconds: float = 240,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """A 完整版：领票 + 挂 Box 路由（仍不写 Cursor）。"""
    ticket = provision_upstream(wake=True, probe=True, log=log)
    if not ticket.get("ok"):
        return ticket
    probe = ticket.get("probe") or {}
    if probe.get("ok"):
        ticket["mount"] = {"ok": True, "result": "already-installed", "note": ticket.get("note")}
        ticket["note"] = "票已领到，且 Box relay 路由已可用"
        return ticket

    from .config import load_upstream

    cfg = load_upstream()
    if cfg is None:
        return {**ticket, "ok": False, "error": "领票后找不到 upstream.json"}
    config = {
        "version": 1,
        "baseUrl": cfg.base_url,
        "token": cfg.token,
        "headers": dict(cfg.headers),
        "relayPath": cfg.relay_path,
        "accountFingerprint": cfg.account_fingerprint,
    }
    try:
        mount = mount_box_relay(config, wait_seconds=wait_seconds, log=log)
    except ProvisionError as exc:
        return {**ticket, "ok": False, "error": str(exc), "mountFailed": True}
    # refresh ticket after possible host restart
    write_upstream_dict(
        {
            "version": 1,
            "baseUrl": cfg.base_url,
            "token": cfg.token,
            "headers": dict(cfg.headers),
            "relayPath": cfg.relay_path,
            "accountFingerprint": cfg.account_fingerprint,
            "mintedAtMs": cfg.minted_at_ms,
            "refreshAfterMs": cfg.refresh_after_ms,
            **({"refresh": dict(cfg.refresh)} if cfg.refresh else {}),
        }
    )
    return {
        **ticket,
        "ok": True,
        "mount": mount,
        "note": mount.get("note") or ticket.get("note"),
    }
