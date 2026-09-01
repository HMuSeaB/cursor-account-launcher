"""Sand Stream 模式：client-type=sand + InferenceService/Stream 直连。

与 model_unlock 分离：会改 Sand 身份与 Agent Host，对话走
``aiserver.v1.InferenceService/Stream``，不是 ``agent.v1.AgentService/Run``。
逻辑移植自 ``sand_stream_installer(4).py``，写入走统一备份 + 预检（workbench）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from launcher.cursor_install import app_root as install_app_root
from launcher.cursor_process import is_cursor_running, resolve_install
from launcher.workbench.manager import WorkbenchWriteError, sync_product_checksums, write_atomic
from launcher.workbench.preflight import PreflightError, assert_safe

MODULE_VERSION = "1.0.0"

SAND_CLIENT_MARKER = "/*SAND_CLIENT_MODE_V1*/"
SAND_CLIENT_EXISTING_MARKER = "/*SAND_CLIENT_EXISTING_V1*/"
SAND_ELIGIBILITY_MARKER = "/*SAND_ELIGIBILITY_MODE_V1*/"
SAND_MANAGED_LOCAL_ROUTE_MARKER = "/*SAND_MANAGED_LOCAL_ROUTE_V1*/"
SAND_DIRECT_STREAM_MARKER = "/*SAND_DIRECT_INFERENCE_STREAM_V1*/"
SAND_AGENT_HOST_ENABLEMENT_MARKER = "/*SAND_AGENT_HOST_ENABLEMENT_V1*/"
SAND_LOCAL_RUNTIME_LOAD_MARKER = "/*SAND_LOCAL_RUNTIME_LOAD_V1*/"
SAND_AGENT_HOST_IDENTITY_MARKER = "/*SAND_AGENT_HOST_IDENTITY_V1*/"
LAUNCHER_SAND_MARKER = "/*CURSOR_LAUNCHER_SAND_STREAM_V1*/"

LEGACY_SAND_CLIENT_MARKER = "/*K" + "C_SAND_CLIENT_V1*/"
LEGACY_SAND_ELIGIBILITY_MARKER = "/*K" + "C_SAND_ELIGIBILITY_V1*/"
CLIENT_MARKER_PATTERN = re.escape(SAND_CLIENT_MARKER)
CLIENT_EXISTING_MARKER_PATTERN = re.escape(SAND_CLIENT_EXISTING_MARKER)
ELIGIBILITY_MARKER_PATTERN = re.escape(SAND_ELIGIBILITY_MARKER)
LEGACY_CLIENT_MARKER_PATTERN = re.escape(LEGACY_SAND_CLIENT_MARKER)
LEGACY_ELIGIBILITY_MARKER_PATTERN = re.escape(LEGACY_SAND_ELIGIBILITY_MARKER)
CLIENT_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_CLIENT(?:_(?:MODE|EXISTING))?_V1\*/"
ELIGIBILITY_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_ELIGIBILITY(?:_MODE)?_V1\*/"

TARGET_SPECS: tuple[tuple[str, str | None], ...] = (
    ("out/main.js", None),
    ("out/vs/workbench/api/worker/extensionHostWorkerMain.js", None),
    ("out/vs/workbench/api/node/extensionHostProcess.js", None),
    ("out/vs/workbench/workbench.glass.main.js", None),
    ("out/vs/workbench/workbench.desktop.main.js", None),
    ("extensions/cursor-always-local/dist/main.js", "cursor-always-local"),
    ("extensions/cursor-local-agent-runtime/dist/main.js", "cursor-local-agent-runtime"),
    ("extensions/cursor-agent-host/dist/main.js", "cursor-agent-host"),
    ("extensions/cursor-agent-exec/dist/main.js", "cursor-agent-exec"),
    ("extensions/cursor-agent-host/dist/657.js", None),
    ("extensions/cursor-agent-host/dist/675.js", None),
)

EXT_HOST_REL = "out/vs/workbench/api/node/extensionHostProcess.js"
WORKBENCH_NAMES = frozenset({"workbench.desktop.main.js", "workbench.glass.main.js"})

ELIGIBILITY_PREFIXES: tuple[str, ...] = (
    "function r4g(e){const{adminSettingsService:t",
    "function Vj_(t){const{adminSettingsService:e",
    "function inf(e){const{adminSettingsService:t",
    "function HSy(t){const{adminSettingsService:e",
    "function Q_f(e){const{adminSettingsService:t",
    "function BpS(t){const{adminSettingsService:e",
)

MANAGED_LOCAL_ROUTE_ORIGINAL = (
    'try{return(yield o.checkFeatureGate(ae))?'
    '{runtime:"managed-local",reason:"eligible"}:'
    '{runtime:"connect",reason:"gate-off"}}catch(e)'
)
MANAGED_LOCAL_ROUTE_PATCHED = (
    "try{return"
    + SAND_MANAGED_LOCAL_ROUTE_MARKER
    + '{runtime:"managed-local",reason:"sand-client"}}catch(e)'
)
LOCAL_RUNTIME_LOAD_ORIGINAL = "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}"
LOCAL_RUNTIME_LOAD_PATCHED = "let t=!0;" + SAND_LOCAL_RUNTIME_LOAD_MARKER + "try{t=!0}"
AGENT_HOST_IDENTITY_ORIGINAL = 'clientIdentity:{clientType:"ide"}'
AGENT_HOST_IDENTITY_PATCHED = (
    'clientIdentity:{clientType:"sand"' + SAND_AGENT_HOST_IDENTITY_MARKER + "}"
)
DIRECT_STREAM_ANCHOR = (
    "function hre(e){return t=>{return n=this,o=void 0,s=function*(){"
)
AGENT_HOST_ENABLEMENT_RE = re.compile(
    r"(this\._agentHostEnabled=)([A-Za-z_$][A-Za-z0-9_$]*)(,)"
)
AGENT_HOST_ENABLEMENT_PATCH_RE = re.compile(
    rf"([A-Za-z_$][A-Za-z0-9_$]*)=!0;"
    rf"{re.escape(SAND_AGENT_HOST_ENABLEMENT_MARKER)}"
    rf"(this\._agentHostEnabled=)\1(,)"
)


class SandStreamError(RuntimeError):
    pass


def _compile_client_rules() -> tuple[tuple[str, re.Pattern[str]], ...]:
    marker_guard = rf"(?!{CLIENT_MARKER_GUARD_PATTERN})"
    return (
        (
            "is_glass",
            re.compile(
                rf"(isGlass\s*\?\s*[\"']glass[\"']\s*:\s*)([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
        (
            "object_header",
            re.compile(
                rf"([\"']x-cursor-client-type[\"']\s*:\s*)([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
        (
            "set_header",
            re.compile(
                rf"(header\.set\(\s*[\"']x-cursor-client-type[\"']\s*,\s*"
                rf"[A-Za-z_$][A-Za-z0-9_$.]*\s*(?:\?\?|\|\|)\s*)"
                rf"([\"'])(ide|sand)\2{marker_guard}"
            ),
        ),
    )


CLIENT_RULES = _compile_client_rules()


@dataclass
class PatchStats:
    is_glass: int = 0
    object_header: int = 0
    set_header: int = 0
    eligibility: int = 0
    adopted_sand: int = 0
    migrated_client: int = 0
    migrated_eligibility: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0

    @property
    def total(self) -> int:
        return sum(
            getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "total"
        )


@dataclass
class RemoveStats:
    client_type: int = 0
    eligibility: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, name) for name in self.__dataclass_fields__)


@dataclass(frozen=True)
class SandLayout:
    install_root: Path
    app_root: Path
    product_json: Path
    executable: Path
    target_paths: tuple[Path, ...]
    ext_host_path: Path | None
    version: str


@dataclass
class PatchStatus:
    client_markers: int = 0
    eligibility_markers: int = 0
    external_marker_count: int = 0
    managed_local_route_markers: int = 0
    local_runtime_load_markers: int = 0
    direct_stream_markers: int = 0
    agent_host_enablement_markers: int = 0
    agent_host_identity_markers: int = 0
    launcher_markers: int = 0
    patched_files: tuple[str, ...] = ()

    @property
    def installed(self) -> bool:
        return (
            self.client_markers
            + self.eligibility_markers
            + self.managed_local_route_markers
            + self.local_runtime_load_markers
            + self.direct_stream_markers
            + self.agent_host_enablement_markers
            + self.agent_host_identity_markers
            > 0
        )

    @property
    def stream_mode_installed(self) -> bool:
        return (
            self.managed_local_route_markers > 0
            and self.local_runtime_load_markers > 0
            and self.direct_stream_markers > 0
            and self.agent_host_enablement_markers > 0
            and self.agent_host_identity_markers > 0
        )


def _direct_stream_injection() -> str:
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + 'const n=t.requestedModel;'
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        'r=new Map(n.parameters.map(e=>[e.id,e.value])),'
        's=new Joe(e,n,void 0,void 0).getSession(),'
        'p={getExecutor:e=>new RK(s.getExecutor(e))},'
        'a={vendor:i.includes("grok")?"xai":i.includes("gemini")?"gemini":'
        'i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable")?'
        '"anthropic":i.includes("gpt")||i.includes("codex")?"openai":"unknown",'
        'promptVersion:"latest",reasoningEffort:r.get("effort"),'
        'isGrok45ProductPrompt:i.includes("grok"),'
        'isClaude4x:i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable"),'
        'isFable5:i.includes("fable-5"),'
        'isOpus5:i.includes("opus-5")||i.includes("opus5"),'
        'isOpus48:i.includes("opus-4.8")||i.includes("opus48"),'
        'isOpus46:i.includes("opus-4.6")||i.includes("opus46"),'
        'isOpus45:i.includes("opus-4.5")||i.includes("opus45"),'
        'isSonnet45:i.includes("sonnet-4.5")||i.includes("sonnet45"),'
        'isSonnet4:i.includes("sonnet-4")||i.includes("sonnet4"),'
        'isGemini3:i.includes("gemini-3")||i.includes("gemini3"),'
        'isGpt56:i.includes("gpt-5.6")||i.includes("gpt5.6"),'
        'isGpt55:i.includes("gpt-5.5")||i.includes("gpt5.5"),'
        'isGpt54:i.includes("gpt-5.4")||i.includes("gpt5.4"),'
        'isGpt53Codex:i.includes("gpt-5.3-codex"),'
        'isGpt52Codex:i.includes("gpt-5.2-codex"),'
        'isCodexFamily:i.includes("codex"),isGpt5Family:i.includes("gpt-5")};'
        'return{promptSession:s,promptToolSession:p,attempt:{resolvedModel:cre(n),'
        'supportsSelfSummary:!1,routedModelDisplayName:o,'
        'resolvedModelMetadata:nre(a,o),finish:()=>Promise.resolve()}}}'
    )


def _store_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "sand-stream"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_root() -> Path:
    path = _store_root() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def build_layout() -> SandLayout:
    layout = resolve_install()
    app_root = install_app_root(layout.install_root)
    product_json = app_root / "product.json"
    if not product_json.is_file():
        raise SandStreamError(f"找不到 product.json：{product_json}")
    try:
        product = json.loads(product_json.read_bytes().decode("utf-8-sig"))
    except Exception as exc:
        raise SandStreamError(f"无法解析 product.json：{exc}") from exc

    targets: list[Path] = []
    for rel, _ext in TARGET_SPECS:
        target = app_root.joinpath(*rel.split("/"))
        if target.is_file():
            real = target.resolve()
            if not _is_within(real, app_root.resolve()):
                raise SandStreamError(f"目标文件逃逸 app 目录：{target}")
            targets.append(real)
    if not targets:
        raise SandStreamError("当前 Cursor 没有可识别的 Sand Stream 目标文件（可能用了 app.asar）")

    ext_host = app_root.joinpath(*EXT_HOST_REL.split("/"))
    ext_host_real = ext_host.resolve() if ext_host.is_file() else None
    version = str(product.get("version") or product.get("commit") or layout.version or "未知")
    return SandLayout(
        install_root=Path(layout.install_root),
        app_root=app_root.resolve(),
        product_json=product_json.resolve(),
        executable=Path(layout.executable),
        target_paths=tuple(targets),
        ext_host_path=ext_host_real,
        version=version,
    )


def apply_patch_to_content(content: str) -> tuple[str, PatchStats]:
    stats = PatchStats()
    next_content = content

    legacy_client_re = re.compile(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}")
    next_content, stats.migrated_client = legacy_client_re.subn(
        lambda m: m.group(1) + "sand" + m.group(1) + SAND_CLIENT_MARKER,
        next_content,
    )
    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    stats.migrated_eligibility = next_content.count(legacy_eligibility)
    next_content = next_content.replace(
        legacy_eligibility,
        "return!1;" + SAND_ELIGIBILITY_MARKER,
    )

    for key, rule in CLIENT_RULES:

        def replace_client(match: re.Match[str], stat_key: str = key) -> str:
            current = match.group(3)
            setattr(stats, stat_key, getattr(stats, stat_key) + 1)
            marker = (
                SAND_CLIENT_EXISTING_MARKER if current == "sand" else SAND_CLIENT_MARKER
            )
            if current == "sand":
                stats.adopted_sand += 1
            return match.group(1) + match.group(2) + "sand" + match.group(2) + marker

        next_content = rule.sub(replace_client, next_content)

    for prefix in ELIGIBILITY_PREFIXES:
        count = next_content.count(prefix)
        if count == 0:
            continue
        patched = prefix.replace(
            "{const{adminSettingsService:",
            "{return!1;" + SAND_ELIGIBILITY_MARKER + "const{adminSettingsService:",
        )
        next_content = next_content.replace(prefix, patched)
        stats.eligibility += count

    route_count = next_content.count(MANAGED_LOCAL_ROUTE_ORIGINAL)
    if route_count:
        next_content = next_content.replace(
            MANAGED_LOCAL_ROUTE_ORIGINAL,
            MANAGED_LOCAL_ROUTE_PATCHED,
        )
        stats.managed_local_route += route_count

    runtime_load_count = next_content.count(LOCAL_RUNTIME_LOAD_ORIGINAL)
    if runtime_load_count:
        next_content = next_content.replace(
            LOCAL_RUNTIME_LOAD_ORIGINAL,
            LOCAL_RUNTIME_LOAD_PATCHED,
        )
        stats.local_runtime_load += runtime_load_count

    identity_count = next_content.count(AGENT_HOST_IDENTITY_ORIGINAL)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_ORIGINAL,
            AGENT_HOST_IDENTITY_PATCHED,
        )
        stats.agent_host_identity += identity_count

    direct_injection = _direct_stream_injection()
    if (
        SAND_DIRECT_STREAM_MARKER not in next_content
        and DIRECT_STREAM_ANCHOR in next_content
    ):
        next_content = next_content.replace(
            DIRECT_STREAM_ANCHOR,
            DIRECT_STREAM_ANCHOR + direct_injection,
            1,
        )
        stats.direct_stream += 1

    if SAND_AGENT_HOST_ENABLEMENT_MARKER not in next_content:

        def enable_agent_host(match: re.Match[str]) -> str:
            variable = match.group(2)
            return (
                variable
                + "=!0;"
                + SAND_AGENT_HOST_ENABLEMENT_MARKER
                + match.group(1)
                + variable
                + match.group(3)
            )

        next_content, agent_host_count = AGENT_HOST_ENABLEMENT_RE.subn(
            enable_agent_host,
            next_content,
            count=1,
        )
        stats.agent_host_enablement += agent_host_count

    return next_content, stats


def remove_patch_from_content(content: str) -> tuple[str, RemoveStats]:
    stats = RemoveStats()
    next_content = content

    if LAUNCHER_SAND_MARKER in next_content:
        next_content = next_content.replace(LAUNCHER_SAND_MARKER, "", 1)

    legacy_client_re = re.compile(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}")
    next_content, legacy_client_count = legacy_client_re.subn(
        lambda m: m.group(1) + "ide" + m.group(1),
        next_content,
    )
    stats.client_type += legacy_client_count

    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    legacy_eligibility_count = next_content.count(legacy_eligibility)
    next_content = next_content.replace(legacy_eligibility, "")
    stats.eligibility += legacy_eligibility_count

    client_re = re.compile(rf"([\"'])sand\1{CLIENT_MARKER_PATTERN}")
    existing_re = re.compile(rf"([\"'])sand\1{CLIENT_EXISTING_MARKER_PATTERN}")

    def remove_client(match: re.Match[str]) -> str:
        stats.client_type += 1
        return match.group(1) + "ide" + match.group(1)

    next_content = client_re.sub(remove_client, next_content)
    next_content, existing_count = existing_re.subn(
        lambda m: m.group(1) + "sand" + m.group(1),
        next_content,
    )
    stats.client_type += existing_count

    eligibility_re = re.compile(rf"return!1;{ELIGIBILITY_MARKER_PATTERN}")
    next_content, eligibility_count = eligibility_re.subn("", next_content)
    stats.eligibility += eligibility_count

    route_count = next_content.count(MANAGED_LOCAL_ROUTE_PATCHED)
    if route_count:
        next_content = next_content.replace(
            MANAGED_LOCAL_ROUTE_PATCHED,
            MANAGED_LOCAL_ROUTE_ORIGINAL,
        )
        stats.managed_local_route += route_count

    runtime_load_count = next_content.count(LOCAL_RUNTIME_LOAD_PATCHED)
    if runtime_load_count:
        next_content = next_content.replace(
            LOCAL_RUNTIME_LOAD_PATCHED,
            LOCAL_RUNTIME_LOAD_ORIGINAL,
        )
        stats.local_runtime_load += runtime_load_count

    identity_count = next_content.count(AGENT_HOST_IDENTITY_PATCHED)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_PATCHED,
            AGENT_HOST_IDENTITY_ORIGINAL,
        )
        stats.agent_host_identity += identity_count

    direct_injection = _direct_stream_injection()
    direct_count = next_content.count(direct_injection)
    if direct_count:
        next_content = next_content.replace(direct_injection, "")
        stats.direct_stream += direct_count

    next_content, agent_host_count = AGENT_HOST_ENABLEMENT_PATCH_RE.subn(
        lambda m: m.group(2) + m.group(1) + m.group(3),
        next_content,
    )
    stats.agent_host_enablement += agent_host_count
    return next_content, stats


def inspect_status(layout: SandLayout) -> PatchStatus:
    client_markers = 0
    eligibility_markers = 0
    managed_local_route_markers = 0
    local_runtime_load_markers = 0
    direct_stream_markers = 0
    agent_host_enablement_markers = 0
    agent_host_identity_markers = 0
    launcher_markers = 0
    external_marker_count = 0
    patched_files: list[str] = []

    for target in layout.target_paths:
        content = target.read_text(encoding="utf-8", errors="ignore")
        client_count = content.count(SAND_CLIENT_MARKER) + content.count(
            SAND_CLIENT_EXISTING_MARKER
        )
        eligibility_count = content.count(SAND_ELIGIBILITY_MARKER)
        managed_local_route_count = content.count(SAND_MANAGED_LOCAL_ROUTE_MARKER)
        local_runtime_load_count = content.count(SAND_LOCAL_RUNTIME_LOAD_MARKER)
        direct_stream_count = content.count(SAND_DIRECT_STREAM_MARKER)
        agent_host_enablement_count = content.count(SAND_AGENT_HOST_ENABLEMENT_MARKER)
        agent_host_identity_count = content.count(SAND_AGENT_HOST_IDENTITY_MARKER)
        launcher_count = content.count(LAUNCHER_SAND_MARKER)
        legacy_client_count = len(
            re.findall(rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}", content)
        )
        legacy_eligibility_count = content.count(
            "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
        )
        external_marker_count += max(
            0,
            len(re.findall(CLIENT_MARKER_GUARD_PATTERN, content))
            - client_count
            - legacy_client_count,
        )
        external_marker_count += max(
            0,
            len(re.findall(ELIGIBILITY_MARKER_GUARD_PATTERN, content))
            - eligibility_count
            - legacy_eligibility_count,
        )
        if (
            client_count
            + eligibility_count
            + legacy_client_count
            + legacy_eligibility_count
            + managed_local_route_count
            + local_runtime_load_count
            + direct_stream_count
            + agent_host_enablement_count
            + agent_host_identity_count
            + launcher_count
        ):
            patched_files.append(target.name)
        client_markers += client_count
        eligibility_markers += eligibility_count
        managed_local_route_markers += managed_local_route_count
        local_runtime_load_markers += local_runtime_load_count
        direct_stream_markers += direct_stream_count
        agent_host_enablement_markers += agent_host_enablement_count
        agent_host_identity_markers += agent_host_identity_count
        launcher_markers += launcher_count

    return PatchStatus(
        client_markers=client_markers,
        eligibility_markers=eligibility_markers,
        external_marker_count=external_marker_count,
        managed_local_route_markers=managed_local_route_markers,
        local_runtime_load_markers=local_runtime_load_markers,
        direct_stream_markers=direct_stream_markers,
        agent_host_enablement_markers=agent_host_enablement_markers,
        agent_host_identity_markers=agent_host_identity_markers,
        launcher_markers=launcher_markers,
        patched_files=tuple(patched_files),
    )


def _target_extension_name(layout: SandLayout, file_path: Path) -> str | None:
    for rel, extension_name in TARGET_SPECS:
        if not extension_name:
            continue
        candidate = layout.app_root.joinpath(*rel.split("/")).resolve()
        if candidate == file_path.resolve():
            return extension_name
    return None


def _update_extension_hashes(
    layout: SandLayout,
    pending: dict[Path, bytes],
) -> None:
    if layout.ext_host_path is None:
        return
    ext_path = layout.ext_host_path
    ext_bytes = pending.get(ext_path, ext_path.read_bytes())
    ext_content = ext_bytes.decode("utf-8")
    original = ext_content

    for file_path, data in pending.items():
        extension_name = _target_extension_name(layout, file_path)
        if not extension_name:
            continue
        extension_id = "anysphere." + extension_name
        if f'"{extension_id}"' not in ext_content:
            continue
        digest = hashlib.sha256(data).hexdigest()
        pattern = re.compile(
            rf'(\"{re.escape(extension_id)}\"\s*:\s*\{{[\s\S]{{0,2400}}?'
            rf'\"main\.js\"\s*:\s*\")[0-9a-f]{{64}}(\")'
        )
        ext_content, count = pattern.subn(
            lambda m: m.group(1) + digest + m.group(2),
            ext_content,
            count=1,
        )
        if count > 1:
            raise SandStreamError(f"{extension_id} 的内嵌 main.js 哈希不唯一")

    if ext_content != original:
        pending[ext_path] = ext_content.encode("utf-8")


def _snapshot_backup(
    layout: SandLayout,
    originals: dict[Path, bytes],
    *,
    operation: str,
) -> Path:
    app_hash = hashlib.sha256(str(layout.app_root).encode("utf-8")).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = _backup_root() / app_hash / f"{stamp}-{operation}"
    files_dir = backup_dir / "files"
    entries: list[dict[str, Any]] = []
    for path, data in originals.items():
        rel = path.resolve().relative_to(layout.app_root.resolve())
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entries.append(
            {
                "path": rel.as_posix(),
                "originalSha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "version": 1,
        "moduleVersion": MODULE_VERSION,
        "operation": operation,
        "appRoot": str(layout.app_root),
        "cursorVersion": layout.version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_dir


def _restore_backup(backup_dir: Path, layout: SandLayout) -> list[str]:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SandStreamError(f"备份无效：{backup_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored: list[str] = []
    for entry in manifest.get("files") or []:
        rel = entry.get("path")
        if not rel:
            continue
        src = backup_dir / "files" / rel
        dst = layout.app_root / rel
        if src.is_file() and dst.is_file():
            shutil.copy2(src, dst)
            restored.append(str(rel))
    return restored


def _commit_plan(
    layout: SandLayout,
    pending: dict[Path, bytes],
    *,
    operation: str,
    originals: dict[Path, bytes],
) -> dict[str, Any]:
    if not pending:
        return {"ok": True, "skipped": True, "changed": []}

    backup_dir = _snapshot_backup(layout, originals, operation=operation)

    # workbench 预检
    for path, data in pending.items():
        if path.name not in WORKBENCH_NAMES:
            continue
        text = data.decode("utf-8")
        orig_text = originals.get(path, b"").decode("utf-8", errors="ignore")
        try:
            assert_safe(text, original=orig_text or None)
        except PreflightError as exc:
            _restore_backup(backup_dir, layout)
            raise SandStreamError("预检未通过：" + "; ".join(exc.issues)) from exc

    _update_extension_hashes(layout, pending)

    product_next = sync_product_checksums(layout.app_root, pending)
    if product_next is not None:
        pending[layout.product_json] = product_next

    changed: list[str] = []
    try:
        for path, data in pending.items():
            if path.is_file() and path.read_bytes() == data:
                continue
            write_atomic(path, data)
            changed.append(path.name)
    except Exception as exc:
        _restore_backup(backup_dir, layout)
        if isinstance(exc, PermissionError):
            raise SandStreamError("没有写入权限或文件被占用，请先关闭 Cursor") from exc
        raise SandStreamError(str(exc)) from exc

    return {
        "ok": True,
        "changed": changed,
        "backup": str(backup_dir),
        "operation": operation,
    }


def _build_install_plan(layout: SandLayout) -> tuple[dict[Path, bytes], PatchStats, dict[Path, bytes]]:
    pending: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}
    total = PatchStats()
    for target in layout.target_paths:
        original = target.read_bytes()
        originals[target] = original
        content = original.decode("utf-8")
        next_content, stats = apply_patch_to_content(content)
        if target.name == "workbench.desktop.main.js" and LAUNCHER_SAND_MARKER not in next_content:
            next_content = LAUNCHER_SAND_MARKER + next_content
        if next_content != content:
            pending[target] = next_content.encode("utf-8")
        for field_name in PatchStats.__dataclass_fields__:
            if field_name == "total":
                continue
            setattr(total, field_name, getattr(total, field_name) + getattr(stats, field_name))
    return pending, total, originals


def _build_uninstall_plan(layout: SandLayout) -> tuple[dict[Path, bytes], RemoveStats, dict[Path, bytes]]:
    pending: dict[Path, bytes] = {}
    originals: dict[Path, bytes] = {}
    total = RemoveStats()
    for target in layout.target_paths:
        original = target.read_bytes()
        originals[target] = original
        content = original.decode("utf-8")
        next_content, stats = remove_patch_from_content(content)
        if next_content != content:
            pending[target] = next_content.encode("utf-8")
        for field_name in RemoveStats.__dataclass_fields__:
            if field_name == "total":
                continue
            setattr(total, field_name, getattr(total, field_name) + getattr(stats, field_name))
    return pending, total, originals


def _stats_dict(patch: PatchStatus) -> dict[str, int]:
    return {
        "client": patch.client_markers,
        "eligibility": patch.eligibility_markers,
        "managedLocalRoute": patch.managed_local_route_markers,
        "localRuntimeLoad": patch.local_runtime_load_markers,
        "directStream": patch.direct_stream_markers,
        "agentHostEnablement": patch.agent_host_enablement_markers,
        "agentHostIdentity": patch.agent_host_identity_markers,
        "launcherMarker": patch.launcher_markers,
    }


def _message(patch: PatchStatus) -> str:
    if patch.stream_mode_installed:
        return "Sand Stream 已就绪（对话应走 InferenceService/Stream）"
    if patch.installed:
        return "检测到部分 Sand 补丁；请关 IDE 后重新「启用 Sand Stream」补全"
    return "未启用；Bot 对话需 Sand Stream 补丁才会走 InferenceService/Stream"


def status() -> dict[str, Any]:
    running = is_cursor_running()
    try:
        layout = build_layout()
    except Exception as exc:
        return {
            "ok": False,
            "installed": False,
            "streamMode": False,
            "running": running,
            "error": str(exc),
        }
    patch = inspect_status(layout)
    return {
        "ok": True,
        "installed": patch.installed,
        "streamMode": patch.stream_mode_installed,
        "running": running,
        "version": layout.version,
        "appRoot": str(layout.app_root),
        "files": list(patch.patched_files),
        "hits": _stats_dict(patch),
        "canApply": not running,
        "canRestore": not running and patch.installed,
        "externalMarkers": patch.external_marker_count,
        "message": _message(patch),
        "endpoint": "aiserver.v1.InferenceService/Stream",
    }


def apply() -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再启用 Sand Stream", "running": True}
    try:
        layout = build_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    before = inspect_status(layout)
    if before.external_marker_count and not before.launcher_markers:
        return {
            "ok": False,
            "error": "检测到其他 Sand 补丁工具留下的标记；请先用原工具卸载，或由启动器「还原 Sand Stream」后再试",
        }

    if before.stream_mode_installed and not before.launcher_markers:
        # 已由 sand_stream_installer 等打过完整补丁，只补 launcher 标记
        pass

    pending, stats, originals = _build_install_plan(layout)
    if not pending:
        if before.stream_mode_installed:
            desktop = layout.app_root / "out/vs/workbench/workbench.desktop.main.js"
            if desktop.is_file() and LAUNCHER_SAND_MARKER not in desktop.read_text(
                encoding="utf-8", errors="ignore"
            ):
                orig = desktop.read_bytes()
                originals[desktop] = orig
                pending[desktop] = (LAUNCHER_SAND_MARKER + orig.decode("utf-8")).encode(
                    "utf-8"
                )
            else:
                st = status()
                st["ok"] = True
                st["skipped"] = True
                st["message"] = "Sand Stream 已完整安装，无需重复操作"
                return st
        else:
            return {
                "ok": False,
                "error": "当前 Cursor 版本未匹配到 Sand Stream 规则（可能需升级 Cursor 或更新启动器）",
                "hits": _stats_dict(before),
            }

    try:
        result = _commit_plan(layout, pending, operation="apply", originals=originals)
    except SandStreamError as exc:
        return {"ok": False, "error": str(exc)}
    except WorkbenchWriteError as exc:
        return {"ok": False, "error": str(exc)}

    after = inspect_status(layout)
    if not after.stream_mode_installed:
        return {
            "ok": False,
            "error": (
                "补丁已写入但未完整匹配 Sand Stream 规则："
                f"route={after.managed_local_route_markers}, "
                f"runtimeLoad={after.local_runtime_load_markers}, "
                f"identity={after.agent_host_identity_markers}, "
                f"directStream={after.direct_stream_markers}, "
                f"agentHost={after.agent_host_enablement_markers}"
            ),
            "partial": True,
            **result,
        }

    st = status()
    st.update(result)
    st["stats"] = {
        k: getattr(stats, k)
        for k in PatchStats.__dataclass_fields__
        if k != "total"
    }
    return st


def restore() -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再还原 Sand Stream", "running": True}
    try:
        layout = build_layout()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    before = inspect_status(layout)
    if not before.installed:
        st = status()
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "当前未安装 Sand Stream，无需还原"
        return st

    pending, _stats, originals = _build_uninstall_plan(layout)
    if not pending:
        st = status()
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "未发现可还原的 Sand Stream 改动"
        return st

    try:
        result = _commit_plan(layout, pending, operation="restore", originals=originals)
    except SandStreamError as exc:
        return {"ok": False, "error": str(exc)}
    except WorkbenchWriteError as exc:
        return {"ok": False, "error": str(exc)}

    st = status()
    st.update(result)
    st["message"] = "已还原 Sand Stream 补丁（client-type 恢复 ide）"
    return st
