"""把 Cursor Stream 改道到本机 Bot 网关（独立 marker，可还原）。

只改两处 applyAuthorization（agent-host / always-local），锚点对齐 v136。
不写 Direct / Joe / RPC；不碰 v136 的 SAND_GROK_BOX_RELAY_AUTH_V1。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from .config import DEFAULT_RELAY_PATH, default_config_dir

MARKER = "/*SAND_LOCAL_BOT_GATEWAY_AUTH_V1*/"
FOREIGN_MARKERS = (
    "/*SAND_GROK_BOX_RELAY_AUTH_V1*/",
    "/*SAND_GROK_RUNTIME_AUTH_V1*/",
    "/*SAND_DIRECT_INFERENCE_STREAM_V1*/",
)

LISTEN_ENV = "BOT_GATEWAY_LISTEN_CONFIG"
LISTEN_NAME = "listen.json"

AUTH_METHOD_PREFIX = "applyAuthorization(e,t){return a(this,void 0,void 0,function*(){"
AUTH_SUFFIX = "if(t.overrideAuthToken){"
AUTH_VAR_DECLS: Tuple[str, ...] = (
    "var n,r,o,s,i,a,l,c,u,d,m,p;",  # cursor-agent-host
    "var n,r,s,o,i,a,l,u,m,c,d,p;",  # cursor-always-local
)

ORIGINALS: Tuple[str, ...] = tuple(
    AUTH_METHOD_PREFIX + vars_ + AUTH_SUFFIX for vars_ in AUTH_VAR_DECLS
)

# Cursor → 本机 listen.json（http://127.0.0.1:8765）；票由网关 upstream 持有并改写 Authorization。
_RELAY_BLOCK = (
    MARKER
    + 'const __clBgStream=e?.service?.typeName==="aiserver.v1.InferenceService"'
    '&&e?.method?.name==="Stream";'
    "if(__clBgStream){"
    'const __clFs=require("node:fs"),__clPath=require("node:path"),'
    '__clOs=require("node:os");'
    f'const __clCfgPath=process.env.{LISTEN_ENV}||('
    'process.platform==="win32"?'
    '__clPath.join(process.env.LOCALAPPDATA||process.env.APPDATA||'
    '__clPath.join(__clOs.homedir(),"AppData","Local"),'
    '"CursorLauncher","bot-gateway","listen.json"):'
    '__clPath.join(__clOs.homedir(),'
    'process.platform==="darwin"?"Library/Application Support":".config",'
    '"CursorLauncher","bot-gateway","listen.json"));'
    'const __clCfg=JSON.parse(__clFs.readFileSync(__clCfgPath,"utf8"));'
    'if(!__clCfg?.baseUrl)throw new Error('
    '"[SAND_LOCAL_BOT_GATEWAY_CONFIG] listen.json missing baseUrl");'
    'e.url=new URL(__clCfg.relayPath||'
    f'"{DEFAULT_RELAY_PATH}",'
    '__clCfg.baseUrl).toString();'
    'if("string"==typeof __clCfg.token&&__clCfg.token.length)'
    'e.header.set("Authorization",`Bearer ${__clCfg.token}`);'
    'for(const[__h,__v]of Object.entries(__clCfg.headers||{}))'
    '"string"==typeof __v&&__v.length&&e.header.set(__h,__v);'
    'e.header.set("x-cursor-client-type",String("sand")),'
    'e.header.set("x-cursor-client-source","sand-desktop"),'
    'e.header.set("x-cursor-client-version","0.44.0"),'
    'e.header.set("x-sand-box-namespace","prod");return}'
)

PATCHES: Tuple[str, ...] = tuple(
    AUTH_METHOD_PREFIX + vars_ + _RELAY_BLOCK + AUTH_SUFFIX for vars_ in AUTH_VAR_DECLS
)

TARGET_RELS = (
    "extensions/cursor-agent-host/dist/main.js",
    "extensions/cursor-always-local/dist/main.js",
)


class InjectError(RuntimeError):
    """注入 / 剥离失败。"""


def default_listen_path() -> Path:
    override = os.environ.get(LISTEN_ENV, "").strip()
    if override:
        return Path(override)
    return default_config_dir() / LISTEN_NAME


def write_listen_config(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    path: Optional[Path] = None,
) -> Path:
    target = path or default_listen_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "baseUrl": f"http://{host}:{port}",
        "token": "local-gateway",
        "relayPath": DEFAULT_RELAY_PATH,
        "headers": {},
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def foreign_markers_in(content: str) -> list[str]:
    return [m for m in FOREIGN_MARKERS if m in content]


def count_marker(content: str) -> int:
    return content.count(MARKER)


def apply_to_content(content: str) -> Tuple[str, int]:
    """对单文件内容注入；返回 (新内容, 替换次数)。"""
    foreign = foreign_markers_in(content)
    if foreign and MARKER not in content:
        raise InjectError(
            "检测到冲突补丁："
            + ", ".join(foreign)
            + "。请先还原 Direct / 卸载 v136 Box Relay，再启用本机网关改道。"
        )
    if MARKER in content:
        return content, 0
    next_content = content
    replaced = 0
    for original, patched in zip(ORIGINALS, PATCHES):
        if original not in next_content:
            continue
        count = next_content.count(original)
        next_content = next_content.replace(original, patched)
        replaced += count
    if replaced == 0:
        raise InjectError(
            "未找到可注入的 applyAuthorization 锚点（需要 Cursor 3.19.x 双站点，"
            "或文件已被未知改写）。"
        )
    return next_content, replaced


def remove_from_content(content: str) -> Tuple[str, int]:
    """剥离本 marker；不影响 Direct / v136。"""
    if MARKER not in content:
        return content, 0
    next_content = content
    stripped = 0
    for original, patched in zip(ORIGINALS, PATCHES):
        if patched not in next_content:
            continue
        count = next_content.count(patched)
        next_content = next_content.replace(patched, original)
        stripped += count
    if MARKER in next_content:
        pattern = re.compile(
            re.escape(AUTH_METHOD_PREFIX)
            + r"(var n,r,[^;]+;)"
            + re.escape(MARKER)
            + r".*?"
            + re.escape(AUTH_SUFFIX),
            re.DOTALL,
        )

        def _sub(match: re.Match[str]) -> str:
            return AUTH_METHOD_PREFIX + match.group(1) + AUTH_SUFFIX

        next_content, n = pattern.subn(_sub, next_content)
        stripped += n
    if MARKER in next_content:
        raise InjectError("无法干净剥离本机网关 marker，请用备份还原对应 JS")
    return next_content, stripped


def resolve_inject_targets(app_root: Path) -> list[Path]:
    out: list[Path] = []
    for rel in TARGET_RELS:
        path = app_root.joinpath(*rel.split("/"))
        if path.is_file():
            out.append(path.resolve())
    return out


def inspect_paths(paths: Sequence[Path]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total = 0
    foreign: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            files.append({"path": str(path), "error": str(exc)})
            continue
        hits = count_marker(text)
        total += hits
        f = foreign_markers_in(text)
        foreign.extend(f)
        files.append(
            {
                "path": str(path),
                "markerHits": hits,
                "foreign": f,
                "hasAuthAnchor": any(o in text for o in ORIGINALS),
            }
        )
    return {
        "marker": MARKER,
        "totalHits": total,
        "injected": total > 0,
        "foreign": sorted(set(foreign)),
        "files": files,
    }


def apply_to_files(
    paths: Iterable[Path],
    *,
    backup_dir: Optional[Path] = None,
) -> dict[str, Any]:
    path_list = list(paths)
    if not path_list:
        raise InjectError("没有可注入的 Cursor 目标文件（缺 agent-host / always-local）")
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
    changed: list[dict[str, Any]] = []
    for path in path_list:
        original = path.read_text(encoding="utf-8", errors="strict")
        try:
            next_content, n = apply_to_content(original)
        except InjectError:
            raise
        if n == 0:
            continue
        if backup_dir is not None:
            rel_name = path.name
            # disambiguate same basename
            stamp = path.parent.parent.name if path.parent.name == "dist" else path.parent.name
            bak = backup_dir / f"{stamp}-{rel_name}"
            bak.write_text(original, encoding="utf-8")
        path.write_text(next_content, encoding="utf-8", newline="\n")
        changed.append({"path": str(path), "replacements": n})
    if not changed and not any(count_marker(p.read_text(encoding="utf-8", errors="ignore")) for p in path_list):
        raise InjectError("锚点未命中，未写入任何文件")
    return {"ok": True, "changed": changed, "inspect": inspect_paths(path_list)}


def remove_from_files(paths: Iterable[Path]) -> dict[str, Any]:
    path_list = list(paths)
    changed: list[dict[str, Any]] = []
    for path in path_list:
        original = path.read_text(encoding="utf-8", errors="strict")
        next_content, n = remove_from_content(original)
        if n == 0:
            continue
        path.write_text(next_content, encoding="utf-8", newline="\n")
        changed.append({"path": str(path), "stripped": n})
    return {"ok": True, "changed": changed, "inspect": inspect_paths(path_list)}
