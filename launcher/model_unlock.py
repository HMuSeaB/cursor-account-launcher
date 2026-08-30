"""模型选择器解锁（不依赖 Sand 身份）。

只解除「免费号只能选 Auto」等客户端锁：
  - FREE 模型锁短路
  - membershipType 读取短路（若命中）
  - Max mode 绑卡守卫短路（若命中）
  - workbench fetch 侧：AvailableModels 设 defaultOn、会员字段伪装

**不会**把 client-type 改成 sand，也不动 Sand 资格函数。
可独立还原；与 sand_patch / 网关互补但不绑定。
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

from launcher.cursor_process import is_cursor_running, resolve_install

MARKER_MODEL = "/*MODEL_UNLOCK_V1*/"
MARKER_MEM = "/*MODEL_MEM_PRO_V1*/"
MARKER_MAX = "/*MODEL_MAXMODE_V1*/"
MARKER_FETCH = "/*MODEL_MEMBERSHIP_SPOOF_V1*/"

WORKBENCH_REL = (
    Path("out") / "vs" / "workbench" / "workbench.desktop.main.js",
    Path("out") / "vs" / "workbench" / "workbench.glass.main.js",
)

# 与 Cusor-bot-sand 同源逻辑，但 marker 独立，且不含 sand client-type
FETCH_SNIPPET = (
    MARKER_FETCH
    + '(function(){try{var G=(typeof globalThis!=="undefined")?globalThis:(typeof self!=="undefined"?self:this);'
    + 'if(!G||G.__modelUnlockFetch)return;G.__modelUnlockFetch=1;'
    + 'var MEM={membershipType:"pro",membership_type:"pro",subscriptionStatus:"active",subscription_status:"active"};'
    + 'function dm(a,b){if(a===null||typeof a!=="object")return a;for(var k in b){var v=b[k];'
    + 'if(v&&typeof v==="object"&&!Array.isArray(v)){a[k]=dm(typeof a[k]==="object"&&a[k]?a[k]:{},v);}else{a[k]=v;}}return a;}'
    + 'function isMem(u){try{return /membership|usage-summary|dashboard\\/get-me|auth\\/(me|full_stripe|stripe_profile)|GetUserInfo|getUserPrivilege|hard-limit/i.test(u);}catch(e){return false;}}'
    + 'function isModels(u){try{return /AvailableModels|available-models/i.test(u);}catch(e){return false;}}'
    + 'function pmod(b){try{var arr=(b&&b.models)||(b&&b.data&&b.data.models);if(Array.isArray(arr)){'
    + 'for(var i=0;i<arr.length;i++){var m=arr[i];if(m&&typeof m==="object"){m.defaultOn=true;m.default_on=true;}}}}catch(e){}return b;}'
    + 'function patchBody(b,mem,mod){if(mem){if(Array.isArray(b)){for(var i=0;i<b.length;i++){if(b[i]&&typeof b[i]==="object"){dm(b[i],MEM);}}}else if(b&&typeof b==="object"){dm(b,MEM);}}if(mod){b=pmod(b);}return b;}'
    + 'var OF=G.fetch;if(typeof OF==="function"){G.fetch=function(){var a=arguments;'
    + 'return OF.apply(this,a).then(function(r){try{var u=(a[0]&&a[0].url)?a[0].url:a[0];'
    + 'var mem=isMem(u),mod=isModels(u);if(!mem&&!mod){return r;}'
    + 'return r.clone().text().then(function(txt){var b;try{b=JSON.parse(txt);}catch(e){return r;}'
    + 'try{b=patchBody(b,mem,mod);}catch(e){}'
    + 'try{return new Response(JSON.stringify(b),{status:r.status,statusText:r.statusText,headers:r.headers});}catch(e){return r;}},'
    + 'function(){return r;});}catch(e){return r;}});};}}catch(e){}})();'
)

FETCH_SNIPPET_RE = re.compile(re.escape(MARKER_FETCH) + r"[\s\S]*?\}\)\(\);")

MODEL_LOCK_RE = re.compile(
    r"(hasResolvedTeamMembership:\w+,teamId:\w+\}\)\{)(return \w+===\w+\.FREE&&\w+&&\w+===void 0\})"
)
MEM_PRO_RE = re.compile(r"(_membershipType=\(\)=>)(this\.storageService\.get\()")
MAXMODE_RE = re.compile(r"(hasValidPaymentMethod=async\(\)=>\{)(?!return!0;)")


class ModelUnlockError(RuntimeError):
    pass


@dataclass
class UnlockStats:
    model_lock: int = 0
    mem_pro: int = 0
    maxmode: int = 0
    fetch: int = 0

    @property
    def total(self) -> int:
        return self.model_lock + self.mem_pro + self.maxmode + self.fetch


@dataclass
class UnlockStatus:
    ok: bool
    installed: bool
    running: bool
    version: str = ""
    app_root: str = ""
    files: list[str] = field(default_factory=list)
    hits: dict[str, int] = field(default_factory=dict)
    can_apply: bool = False
    can_restore: bool = False
    error: str = ""
    message: str = ""


def _state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "CursorLauncher" / "model-unlock"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _backup_dir() -> Path:
    path = _state_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _product_checksum(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def _workbench_files(app_root: Path) -> list[Path]:
    return [app_root / rel for rel in WORKBENCH_REL if (app_root / rel).is_file()]


def apply_to_content(content: str) -> tuple[str, UnlockStats]:
    stats = UnlockStats()
    next_content = content

    def unlock_model(match: re.Match[str]) -> str:
        stats.model_lock += 1
        return match.group(1) + "return!1;" + MARKER_MODEL + match.group(2)

    next_content = MODEL_LOCK_RE.sub(unlock_model, next_content)

    def inject_mem(match: re.Match[str]) -> str:
        stats.mem_pro += 1
        return match.group(1) + '"pro"||' + MARKER_MEM + match.group(2)

    next_content = MEM_PRO_RE.sub(inject_mem, next_content)

    def inject_max(match: re.Match[str]) -> str:
        stats.maxmode += 1
        return match.group(1) + "return!0;" + MARKER_MAX

    next_content = MAXMODE_RE.sub(inject_max, next_content)

    if MARKER_FETCH not in next_content:
        # 插到文件开头，renderer 尽早挂钩 fetch
        next_content = FETCH_SNIPPET + next_content
        stats.fetch = 1
    else:
        # 刷新片段
        next_content, replaced = FETCH_SNIPPET_RE.subn(FETCH_SNIPPET, next_content, count=1)
        if replaced:
            stats.fetch = 1

    return next_content, stats


def remove_from_content(content: str) -> tuple[str, UnlockStats]:
    stats = UnlockStats()
    next_content = content

    # FREE 锁：去掉 return!1;MARKER
    pat_lock = re.compile(r"return!1;" + re.escape(MARKER_MODEL))
    next_content, n = pat_lock.subn("", next_content)
    stats.model_lock = n

    pat_mem = re.compile(r'"pro"\|\|' + re.escape(MARKER_MEM))
    next_content, n = pat_mem.subn("", next_content)
    stats.mem_pro = n

    pat_max = re.compile(r"return!0;" + re.escape(MARKER_MAX))
    next_content, n = pat_max.subn("", next_content)
    stats.maxmode = n

    next_content, n = FETCH_SNIPPET_RE.subn("", next_content)
    stats.fetch = n

    return next_content, stats


def _count_markers(content: str) -> dict[str, int]:
    return {
        "modelLock": content.count(MARKER_MODEL),
        "memPro": content.count(MARKER_MEM),
        "maxMode": content.count(MARKER_MAX),
        "fetchSpoof": content.count(MARKER_FETCH),
    }


def _sync_product_checksums(app_root: Path, changed: dict[Path, bytes]) -> bytes | None:
    product = app_root / "product.json"
    if not product.is_file():
        return None
    raw = product.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise ModelUnlockError(f"无法解析 product.json：{exc}") from exc
    checksums = data.get("checksums") if isinstance(data, dict) else None
    if not isinstance(checksums, dict):
        return None
    out_root = (app_root / "out").resolve()
    dirty = False
    for key in list(checksums.keys()):
        if not isinstance(key, str):
            continue
        parts = [p for p in re.split(r"[\\/]", key) if p]
        target = out_root.joinpath(*parts).resolve()
        if target in changed:
            digest = _product_checksum(changed[target])
            if checksums.get(key) != digest:
                checksums[key] = digest
                dirty = True
    if not dirty:
        return None
    text = json.dumps(data, ensure_ascii=False, indent="\t")
    out = text.encode("utf-8")
    if has_bom:
        out = b"\xef\xbb\xbf" + out
    return out


def _snapshot(files: list[Path]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = _backup_dir() / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, dest / path.name)
    product = files[0].parents[3] / "product.json" if files else None
    # app_root/out/vs/workbench/file → parents[3]=app_root
    try:
        app_root = files[0].resolve().parents[3]
        pj = app_root / "product.json"
        if pj.is_file():
            shutil.copy2(pj, dest / "product.json")
    except Exception:
        pass
    (dest / "manifest.json").write_text(
        json.dumps(
            {
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "files": [p.name for p in files],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dest


def status() -> dict[str, Any]:
    running = is_cursor_running()
    try:
        layout = resolve_install()
    except Exception as exc:
        return UnlockStatus(
            ok=False, installed=False, running=running, error=str(exc)
        ).__dict__
    app_root = Path(layout.install_root) / "resources" / "app"
    files = _workbench_files(app_root)
    if not files:
        return UnlockStatus(
            ok=False,
            installed=False,
            running=running,
            version=layout.version,
            app_root=str(app_root),
            error="找不到 workbench 文件",
        ).__dict__
    hits: dict[str, int] = {"modelLock": 0, "memPro": 0, "maxMode": 0, "fetchSpoof": 0}
    touched: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        c = _count_markers(text)
        for k, v in c.items():
            hits[k] = hits.get(k, 0) + v
        if sum(c.values()):
            touched.append(path.name)
    installed = hits.get("modelLock", 0) > 0 or hits.get("fetchSpoof", 0) > 0
    st = UnlockStatus(
        ok=True,
        installed=installed,
        running=running,
        version=layout.version,
        app_root=str(app_root),
        files=touched,
        hits=hits,
        can_apply=not running and bool(files),
        can_restore=not running and installed,
        message=(
            "已解锁模型选择器（未改 Sand 身份）"
            if installed
            else "未解锁；免费号可能只能选 Auto"
        ),
    )
    return st.__dict__


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".mu-{os.getpid()}-{time.time_ns()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def apply() -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再启用模型解锁", "running": True}
    try:
        layout = resolve_install()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    app_root = Path(layout.install_root) / "resources" / "app"
    files = _workbench_files(app_root)
    if not files:
        return {"ok": False, "error": "找不到 workbench 文件"}

    bak = _snapshot(files)
    changed: dict[Path, bytes] = {}
    total = UnlockStats()
    for path in files:
        original = path.read_text(encoding="utf-8")
        next_text, stats = apply_to_content(original)
        total.model_lock += stats.model_lock
        total.mem_pro += stats.mem_pro
        total.maxmode += stats.maxmode
        total.fetch += stats.fetch
        if next_text != original:
            changed[path] = next_text.encode("utf-8")

    if total.model_lock == 0 and total.fetch == 0:
        return {
            "ok": False,
            "error": "当前 Cursor 版本未匹配到模型锁规则（可能已解锁或结构变了）",
            "backup": str(bak),
            "stats": total.__dict__,
        }

    product_next = _sync_product_checksums(app_root, changed)
    product_path = app_root / "product.json"
    if product_next is not None and product_path.is_file():
        changed[product_path] = product_next

    try:
        for path, data in changed.items():
            _write_atomic(path, data)
    except PermissionError:
        return {"ok": False, "error": "没有写入权限，请用管理员运行启动器", "backup": str(bak)}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "backup": str(bak)}

    st = status()
    st["ok"] = True
    st["backup"] = str(bak)
    st["stats"] = total.__dict__
    st["message"] = (
        f"已解锁：FREE锁×{total.model_lock} · 会员短路×{total.mem_pro} · "
        f"Max×{total.maxmode} · fetch×{total.fetch}。请用启动器重启 IDE。"
    )
    return st


def restore() -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再还原模型解锁", "running": True}
    try:
        layout = resolve_install()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    app_root = Path(layout.install_root) / "resources" / "app"
    files = _workbench_files(app_root)
    if not files:
        return {"ok": False, "error": "找不到 workbench 文件"}

    bak = _snapshot(files)
    changed: dict[Path, bytes] = {}
    total = UnlockStats()
    for path in files:
        original = path.read_text(encoding="utf-8")
        next_text, stats = remove_from_content(original)
        total.model_lock += stats.model_lock
        total.mem_pro += stats.mem_pro
        total.maxmode += stats.maxmode
        total.fetch += stats.fetch
        if next_text != original:
            changed[path] = next_text.encode("utf-8")

    if not changed:
        return {
            "ok": True,
            "skipped": True,
            "message": "未发现本启动器的模型解锁标记，无需还原",
            "backup": str(bak),
        }

    product_next = _sync_product_checksums(app_root, changed)
    product_path = app_root / "product.json"
    if product_next is not None and product_path.is_file():
        changed[product_path] = product_next

    try:
        for path, data in changed.items():
            _write_atomic(path, data)
    except PermissionError:
        return {"ok": False, "error": "没有写入权限", "backup": str(bak)}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "backup": str(bak)}

    st = status()
    st["ok"] = True
    st["backup"] = str(bak)
    st["stats"] = total.__dict__
    st["message"] = "已还原模型解锁。请用启动器重启 IDE。"
    return st
