"""模型选择器解锁（不依赖 Sand 身份）。

解除「只能选 Auto」/「没有 MAX Mode」等客户端门闩：
  - FREE 模型锁短路
  - 全量 picker 守卫 / 实验 treatment 短路
  - 命名视图门闩（不再强求 name===grok-4.5）
  - 模型目录 hydrate：补 defaultOn + namedModelSectionIndex
  - **显示 MAX Mode**：关掉 hideMaxToggle（token 计价用户被藏开关的主因）
  - membershipType 读取短路（可配置 pro / ultra / enterprise 等）
  - Max 绑卡守卫短路（若命中；对「开关被藏」没用）
  - workbench fetch 侧：会员字段伪装 + AvailableModels defaultOn
  - 可选同步 state.vscdb 侧边栏套餐显示（默认 Pro，不再写死 Team）

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

from launcher.local_cursor import state_db_path, wait_state_db_ready
from launcher.cursor_process import _load_config, is_cursor_running, resolve_install, update_config

MARKER_MODEL = "/*MODEL_UNLOCK_V1*/"
MARKER_MEM = "/*MODEL_MEM_PRO_V1*/"
MARKER_MAX = "/*MODEL_MAXMODE_V1*/"
MARKER_FETCH = "/*MODEL_MEMBERSHIP_SPOOF_V1*/"
MARKER_FULL = "/*MODEL_FULL_PICKER_V1*/"
MARKER_TREAT = "/*MODEL_NO_TREATMENT_V1*/"
MARKER_NAMED = "/*MODEL_NAMED_VIEW_V1*/"
MARKER_CATALOG = "/*MODEL_CATALOG_V1*/"
MARKER_SHOW_MAX = "/*MODEL_SHOW_MAX_V1*/"

WORKBENCH_REL = (
    Path("out") / "vs" / "workbench" / "workbench.desktop.main.js",
    Path("out") / "vs" / "workbench" / "workbench.glass.main.js",
)

# Cursor 侧边栏：enterprise → Team Plan；ultra → Ultra Plan；pro → Pro Plan
MEMBERSHIP_LEVELS: dict[str, dict[str, str]] = {
    "pro": {"value": "pro", "label": "Pro Plan"},
    "ultra": {"value": "ultra", "label": "Ultra Plan"},
    "enterprise": {"value": "enterprise", "label": "Team Plan"},
    "pro_plus": {"value": "pro_plus", "label": "Pro+ Plan"},
    "free": {"value": "free", "label": "Free Plan"},
}
CONFIG_MEMBERSHIP_KEY = "modelUnlockMembership"
DEFAULT_MEMBERSHIP = "pro"
_MEM_VALUES = tuple(v["value"] for v in MEMBERSHIP_LEVELS.values())


def normalize_membership(level: str | None) -> str:
    key = (level or DEFAULT_MEMBERSHIP).strip().lower()
    if key in MEMBERSHIP_LEVELS:
        return key
    for k, meta in MEMBERSHIP_LEVELS.items():
        if meta["value"] == key:
            return k
    return DEFAULT_MEMBERSHIP


def membership_meta(level: str | None = None) -> dict[str, str]:
    key = normalize_membership(level)
    return {"key": key, **MEMBERSHIP_LEVELS[key]}


def get_membership_setting() -> dict[str, str]:
    cfg = _load_config()
    return membership_meta(cfg.get(CONFIG_MEMBERSHIP_KEY))


def set_membership_setting(level: str) -> dict[str, str]:
    meta = membership_meta(level)
    update_config(**{CONFIG_MEMBERSHIP_KEY: meta["key"]})
    return meta


def build_fetch_snippet(level: str | None = None) -> str:
    val = membership_meta(level)["value"]
    return (
        MARKER_FETCH
        + '(function(){try{var G=(typeof globalThis!=="undefined")?globalThis:(typeof self!=="undefined"?self:this);'
        + 'if(!G||G.__modelUnlockFetch)return;G.__modelUnlockFetch=1;'
        + f'var MEM={{membershipType:"{val}",membership_type:"{val}",subscriptionStatus:"active",subscription_status:"active"}};'
        + 'function dm(a,b){if(a===null||typeof a!=="object")return a;for(var k in b){var v=b[k];'
        + 'if(v&&typeof v==="object"&&!Array.isArray(v)){a[k]=dm(typeof a[k]==="object"&&a[k]?a[k]:{},v);}else{a[k]=v;}}return a;}'
        + 'function isMem(u){try{return /membership|usage-summary|dashboard\\/get-me|auth\\/(me|full_stripe|stripe_profile)|GetUserInfo|getUserPrivilege|hard-limit/i.test(u);}catch(e){return false;}}'
        + 'function isModels(u){try{return /AvailableModels|available-models/i.test(u);}catch(e){return false;}}'
        + 'function pmod(b){try{var arr=(b&&b.models)||(b&&b.data&&b.data.models);if(Array.isArray(arr)){'
        + 'for(var i=0;i<arr.length;i++){var m=arr[i];if(m&&typeof m==="object"){m.defaultOn=true;m.default_on=true;'
        + 'if(m.namedModelSectionIndex===void 0)m.namedModelSectionIndex=0;}}}}catch(e){}return b;}'
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
    r"(hasResolvedTeamMembership:\w+,teamId:\w+\}\)\{)(?!return!1;)"
    r"(return \w+===\w+\.FREE&&\w+&&\w+===void 0\})"
)
FULL_PICKER_RE = re.compile(
    r"(function \w+\(\{isAuthSettling:\w+,isPotentiallyFreeUserModelPickerLocked:\w+,"
    r"isFreeUserMembershipConfirmedToAllowFullPicker:\w+,isRestrictedModelPicker:\w+\}\)\{)"
    r"(?!return!0;)"
    r"(return!\w+&&!\w+&&\(!\w+\|\|\w+\))"
)
TREATMENT_RE = re.compile(
    r"(function \w+\(\{group:\w+,isConfirmedFreeUser:\w+,isStatsigIdentityReady:\w+\}\)\{)"
    r"(?!return!1;)"
    r"(return \w+&&\w+&&\w+===\"treatment\")"
)
NAMED_VIEW_RE = re.compile(
    r"(function \w+\(\w+,\w+\)\{)"
    r"(?!return!0;)"
    r"(return \w+\.some\(\w+=>\w+\(\w+\)&&\w+\.defaultOn!==!1&&\w+\.namedModelSectionIndex!==void 0&&\(\w+===void 0\|\|\w+\(\w+\)\)\))"
)
# availableDefaultModels2 map  hydrate：补 defaultOn / namedModelSectionIndex
CATALOG_RE = re.compile(
    r"(function \w+\((\w+)\)\{const (\w+)=\w+\(\2\);return \3\.variants=\3\.variants\?\?\[\],"
    r"\3\.parameterDefinitions=\3\.parameterDefinitions\?\?\[\],)(\3)(\})"
)
CATALOG_INJECT = (
    "(function(m){try{if(m&&typeof m===\"object\"&&m.name&&m.name!==\"default\"){"
    "if(m.defaultOn===void 0)m.defaultOn=!0;"
    "if(m.namedModelSectionIndex===void 0)m.namedModelSectionIndex=0}}"
    f"catch(_e){{}}return m}})({{VAR}}){MARKER_CATALOG}"
)
_MEM_QUOTED = r'"(?:' + "|".join(_MEM_VALUES) + r')"'
MEM_PRO_RE = re.compile(
    r"(_membershipType=\(\)=>)(?!" + _MEM_QUOTED + r"\|\|" + re.escape(MARKER_MEM) + r")"
    r"(?:" + _MEM_QUOTED + r"\|\|)?"
    r"(this\.storageService\.get\()"
)
MEM_INJECTED_RE = re.compile(_MEM_QUOTED + r"\|\|" + re.escape(MARKER_MEM))
MAX_MEM_INJECT = 4

APPLICATION_USER_DB_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser"
)
STRIPE_MEMBERSHIP_DB_KEY = "cursorAuth/stripeMembershipType"
MAXMODE_RE = re.compile(r"(hasValidPaymentMethod=async\(\)=>\{)(?!return!0;)")
# 3.12/3.15：token 计价用户 hideMaxToggle:C()||E() / S()||k() / Ee||j —— 开关直接不渲染
HIDE_MAX_TOGGLE_RE = re.compile(
    r"(hideMaxToggle:)(?!!1" + re.escape(MARKER_SHOW_MAX) + r")"
    r"((?:\w+\(\)\|\|\w+\(\))|(?:\w+\|\|\w+))(?=[,}])"
)
# 对象字面量里不能写 hideMaxToggle:!1; —— 分号会截断属性，workbench 整包解析失败黑屏
BROKEN_SHOW_MAX_RE = re.compile(
    r"hideMaxToggle:!1;" + re.escape(MARKER_SHOW_MAX) + r"(/\*ORIG:[^*]+\*/)?"
)


class ModelUnlockError(RuntimeError):
    pass


@dataclass
class UnlockStats:
    model_lock: int = 0
    mem_pro: int = 0
    maxmode: int = 0
    show_max: int = 0
    fetch: int = 0
    full_picker: int = 0
    treatment: int = 0
    named_view: int = 0
    catalog: int = 0

    @property
    def total(self) -> int:
        return (
            self.model_lock
            + self.mem_pro
            + self.maxmode
            + self.show_max
            + self.fetch
            + self.full_picker
            + self.treatment
            + self.named_view
            + self.catalog
        )


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


def apply_show_max_to_content(content: str) -> tuple[str, UnlockStats]:
    """只打 hideMaxToggle 补丁，用于显示 MAX 开关（改动最小，不易黑屏）。"""
    stats = UnlockStats()
    next_content = content

    def inject_show_max(match: re.Match[str]) -> str:
        stats.show_max += 1
        orig = match.group(2)
        return f"{match.group(1)}!1{MARKER_SHOW_MAX}/*ORIG:{orig}*/"

    next_content = HIDE_MAX_TOGGLE_RE.sub(inject_show_max, next_content)

    def fix_broken_show_max(match: re.Match[str]) -> str:
        orig = match.group(1) or ""
        return "hideMaxToggle:!1" + MARKER_SHOW_MAX + orig

    next_content, n_fix = BROKEN_SHOW_MAX_RE.subn(fix_broken_show_max, next_content)
    if n_fix and stats.show_max == 0:
        stats.show_max = n_fix

    return next_content, stats


def apply_to_content(
    content: str, membership_level: str | None = None, *, max_only: bool = False
) -> tuple[str, UnlockStats]:
    if max_only:
        return apply_show_max_to_content(content)

    stats = UnlockStats()
    next_content = content
    mem_val = membership_meta(membership_level)["value"]
    fetch_snippet = build_fetch_snippet(membership_level)

    def unlock_model(match: re.Match[str]) -> str:
        stats.model_lock += 1
        return match.group(1) + "return!1;" + MARKER_MODEL + match.group(2)

    next_content = MODEL_LOCK_RE.sub(unlock_model, next_content)

    def inject_full(match: re.Match[str]) -> str:
        stats.full_picker += 1
        return match.group(1) + "return!0;" + MARKER_FULL + match.group(2)

    next_content = FULL_PICKER_RE.sub(inject_full, next_content)

    def inject_treat(match: re.Match[str]) -> str:
        stats.treatment += 1
        return match.group(1) + "return!1;" + MARKER_TREAT + match.group(2)

    next_content = TREATMENT_RE.sub(inject_treat, next_content)

    def inject_named(match: re.Match[str]) -> str:
        stats.named_view += 1
        return match.group(1) + "return!0;" + MARKER_NAMED + match.group(2)

    next_content = NAMED_VIEW_RE.sub(inject_named, next_content)

    def inject_catalog(match: re.Match[str]) -> str:
        if MARKER_CATALOG in match.group(0):
            return match.group(0)
        stats.catalog += 1
        var = match.group(3)
        return match.group(1) + CATALOG_INJECT.replace("{VAR}", var) + match.group(5)

    next_content = CATALOG_RE.sub(inject_catalog, next_content)

    def inject_mem(match: re.Match[str]) -> str:
        stats.mem_pro += 1
        return match.group(1) + f'"{mem_val}"||' + MARKER_MEM + match.group(2)

    if MARKER_MEM in next_content and MEM_INJECTED_RE.search(next_content):
        next_content, n_mem = MEM_INJECTED_RE.subn(f'"{mem_val}"||{MARKER_MEM}', next_content)
        if n_mem:
            stats.mem_pro = n_mem
    else:
        next_content = MEM_PRO_RE.sub(inject_mem, next_content)

    if stats.mem_pro > MAX_MEM_INJECT:
        raise ModelUnlockError(
            f"会员短路补丁命中 {stats.mem_pro} 处（上限 {MAX_MEM_INJECT}），"
            "为避免黑屏已中止。请先用「还原」或重装 Cursor。"
        )

    def inject_max(match: re.Match[str]) -> str:
        stats.maxmode += 1
        return match.group(1) + "return!0;" + MARKER_MAX

    next_content = MAXMODE_RE.sub(inject_max, next_content)

    def inject_show_max(match: re.Match[str]) -> str:
        stats.show_max += 1
        orig = match.group(2)
        return f"{match.group(1)}!1{MARKER_SHOW_MAX}/*ORIG:{orig}*/"

    next_content = HIDE_MAX_TOGGLE_RE.sub(inject_show_max, next_content)

    def fix_broken_show_max(match: re.Match[str]) -> str:
        orig = match.group(1) or ""
        return "hideMaxToggle:!1" + MARKER_SHOW_MAX + orig

    next_content, n_fix = BROKEN_SHOW_MAX_RE.subn(fix_broken_show_max, next_content)
    if n_fix and stats.show_max == 0:
        stats.show_max = n_fix

    if MARKER_FETCH not in next_content:
        next_content = fetch_snippet + next_content
        stats.fetch = 1
    else:
        next_content, replaced = FETCH_SNIPPET_RE.subn(fetch_snippet, next_content, count=1)
        if replaced:
            stats.fetch = 1

    return next_content, stats


def remove_from_content(content: str) -> tuple[str, UnlockStats]:
    stats = UnlockStats()
    next_content = content

    for marker, attr, prefix in (
        (MARKER_MODEL, "model_lock", "return!1;"),
        (MARKER_FULL, "full_picker", "return!0;"),
        (MARKER_TREAT, "treatment", "return!1;"),
        (MARKER_NAMED, "named_view", "return!0;"),
        (MARKER_MAX, "maxmode", "return!0;"),
    ):
        pat = re.compile(re.escape(prefix + marker))
        next_content, n = pat.subn("", next_content)
        setattr(stats, attr, n)

    def restore_show_max(match: re.Match[str]) -> str:
        stats.show_max += 1
        return "hideMaxToggle:" + match.group(1)

    show_max_pat = re.compile(
        r"hideMaxToggle:!1;?" + re.escape(MARKER_SHOW_MAX) + r"/\*ORIG:([^*]+)\*/"
    )
    next_content = show_max_pat.sub(restore_show_max, next_content)

    # catalog：把 inject(t)MARKER 还原为 t
    catalog_pat = re.compile(
        r"\(function\(m\)\{try\{if\(m&&typeof m===\"object\"&&m\.name&&m\.name!==\"default\"\)\{"
        r"if\(m\.defaultOn===void 0\)m\.defaultOn=!0;"
        r"if\(m\.namedModelSectionIndex===void 0\)m\.namedModelSectionIndex=0\}\}"
        r"catch\(_e\)\{\}return m\}\)\((\w+)\)" + re.escape(MARKER_CATALOG)
    )
    next_content, n = catalog_pat.subn(r"\1", next_content)
    stats.catalog = n

    pat_mem = re.compile(_MEM_QUOTED + r"\|\|" + re.escape(MARKER_MEM))
    next_content, n = pat_mem.subn("", next_content)
    stats.mem_pro = n

    next_content, n = FETCH_SNIPPET_RE.subn("", next_content)
    stats.fetch = n

    return next_content, stats


def _decode_db_value(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    text = str(raw).strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            parsed = json.loads(text)
            return str(parsed)
        except Exception:
            pass
    return text


def read_storage_membership() -> dict[str, Any]:
    path = state_db_path()
    if not os.path.isfile(path):
        return {"ok": False, "error": "未找到 state.vscdb"}
    try:
        import sqlite3

        conn = sqlite3.connect(path, timeout=8)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        stripe = ""
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key=?", (STRIPE_MEMBERSHIP_DB_KEY,)
        ).fetchone()
        if row and row[0]:
            stripe = _decode_db_value(row[0])
        app_user = ""
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key=?", (APPLICATION_USER_DB_KEY,)
        ).fetchone()
        if row and row[0]:
            raw = row[0]
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "replace")
            data = json.loads(str(raw))
            if isinstance(data, dict):
                app_user = str(data.get("membershipType") or "")
        return {
            "ok": True,
            "stripeMembershipType": stripe,
            "applicationUserMembershipType": app_user,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def sync_storage_membership(level: str | None = None) -> dict[str, Any]:
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再修正侧边栏显示", "running": True}
    meta = membership_meta(level)
    val = meta["value"]
    if not os.path.isfile(state_db_path()):
        return {"ok": False, "error": "未找到 state.vscdb"}
    try:
        wait_state_db_ready()
        import sqlite3

        conn = sqlite3.connect(state_db_path(), timeout=15)
        conn.execute("PRAGMA busy_timeout=15000")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    try:
        before = read_storage_membership()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            (STRIPE_MEMBERSHIP_DB_KEY, json.dumps(val)),
        )
        row = cur.execute(
            "SELECT value FROM ItemTable WHERE key=?", (APPLICATION_USER_DB_KEY,)
        ).fetchone()
        if row and row[0]:
            raw = row[0]
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "replace")
            data = json.loads(str(raw))
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
        data["membershipType"] = val
        if val != "free":
            data["subscriptionStatus"] = "active"
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            (
                APPLICATION_USER_DB_KEY,
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "membership": meta,
            "before": before,
            "after": read_storage_membership(),
            "message": f"已将侧边栏套餐写入为 {meta['label']}（{val}）。请用启动器重启 IDE。",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def _membership_status_fields() -> dict[str, Any]:
    setting = get_membership_setting()
    storage = read_storage_membership()
    levels = [
        {"key": key, "value": meta["value"], "label": meta["label"]}
        for key, meta in MEMBERSHIP_LEVELS.items()
    ]
    return {
        "membershipLevel": setting["key"],
        "membershipLabel": setting["label"],
        "membershipValue": setting["value"],
        "membershipLevels": levels,
        "storageMembership": storage,
    }


def _count_markers(content: str) -> dict[str, int]:
    return {
        "modelLock": content.count(MARKER_MODEL),
        "fullPicker": content.count(MARKER_FULL),
        "treatment": content.count(MARKER_TREAT),
        "namedView": content.count(MARKER_NAMED),
        "catalog": content.count(MARKER_CATALOG),
        "memPro": content.count(MARKER_MEM),
        "maxMode": content.count(MARKER_MAX),
        "showMax": content.count(MARKER_SHOW_MAX),
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
    hits: dict[str, int] = {
        "modelLock": 0,
        "fullPicker": 0,
        "treatment": 0,
        "namedView": 0,
        "catalog": 0,
        "memPro": 0,
        "maxMode": 0,
        "showMax": 0,
        "fetchSpoof": 0,
    }
    touched: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        c = _count_markers(text)
        for k, v in c.items():
            hits[k] = hits.get(k, 0) + v
        if sum(c.values()):
            touched.append(path.name)
    installed = (
        hits.get("modelLock", 0) > 0
        or hits.get("namedView", 0) > 0
        or hits.get("catalog", 0) > 0
        or hits.get("showMax", 0) > 0
        or hits.get("fetchSpoof", 0) > 0
    )
    complete = (
        hits.get("showMax", 0) > 0
        or (hits.get("namedView", 0) > 0 and hits.get("catalog", 0) > 0)
    )
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
            "已解锁 MAX 开关"
            if hits.get("showMax", 0) > 0 and hits.get("fetchSpoof", 0) == 0
            else (
                "已解锁（含显示 MAX Mode；未改 Sand）"
                if hits.get("showMax", 0) > 0
                else (
                    "已打部分解锁；请再点「启用解锁」补 MAX 开关（须先关 IDE）"
                    if installed
                    else "未解锁；无 MAX 开关（token 计价账号会被 hideMaxToggle 藏掉）"
                )
            )
        ),
    )
    out = st.__dict__
    out.update(_membership_status_fields())
    out["canSyncStorage"] = not running
    out["corrupted"] = hits.get("memPro", 0) > MAX_MEM_INJECT
    out["canRepair"] = not running and (
        out["corrupted"]
        or hits.get("fetchSpoof", 0) > 0
        or hits.get("showMax", 0) > 0
    )
    return out


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".mu-{os.getpid()}-{time.time_ns()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _accumulate(total: UnlockStats, stats: UnlockStats) -> None:
    for field_name in UnlockStats.__dataclass_fields__:
        if field_name == "total":
            continue
        setattr(total, field_name, getattr(total, field_name) + getattr(stats, field_name))


def _find_clean_backup() -> Path | None:
    root = _backup_dir()
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        desktop = entry / "workbench.desktop.main.js"
        if not desktop.is_file():
            continue
        head = desktop.read_text(encoding="utf-8", errors="ignore")[:80]
        if MARKER_MEM in head or desktop.read_text(encoding="utf-8", errors="ignore").count(MARKER_MEM) > MAX_MEM_INJECT:
            continue
        if head.lstrip().startswith("/*!") or head.lstrip().startswith("(function"):
            return entry
    return None


def repair_corrupted() -> dict[str, Any]:
    """从备份还原被错误会员补丁打坏的 workbench（黑屏修复）。"""
    if is_cursor_running():
        return {"ok": False, "error": "请先关闭 IDE，再修复黑屏", "running": True}
    try:
        layout = resolve_install()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    app_root = Path(layout.install_root) / "resources" / "app"
    files = _workbench_files(app_root)
    if not files:
        return {"ok": False, "error": "找不到 workbench 文件"}

    hits = sum(_count_markers(p.read_text(encoding="utf-8", errors="ignore")).get("memPro", 0) for p in files)
    if hits <= MAX_MEM_INJECT and not any(MARKER_FETCH in p.read_text(encoding="utf-8", errors="ignore") for p in files):
        st = status()
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "workbench 未见异常补丁，无需修复。若仍黑屏请完全退出 Cursor 后重开。"
        return st

    backup = _find_clean_backup()
    if backup is None:
        return {
            "ok": False,
            "error": "找不到可用的干净备份。请重装 Cursor 或从官方安装包覆盖 resources/app/out/vs/workbench/*.js",
        }

    changed: dict[Path, bytes] = {}
    restored_names: list[str] = []
    for path in files:
        src = backup / path.name
        if not src.is_file():
            continue
        data = src.read_bytes()
        if path.read_bytes() != data:
            changed[path] = data
            restored_names.append(path.name)

    product_src = backup / "product.json"
    product_path = app_root / "product.json"
    if product_src.is_file() and product_path.is_file():
        changed[product_path] = product_src.read_bytes()

    if not changed:
        st = status()
        st["ok"] = True
        st["skipped"] = True
        st["message"] = "workbench 已与备份一致。"
        return st

    try:
        for path, data in changed.items():
            _write_atomic(path, data)
    except (PermissionError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    st = status()
    st["ok"] = True
    st["message"] = f"已从备份 {backup.name} 还原 {', '.join(restored_names)}。请用启动器重启 IDE。"
    st["backupUsed"] = str(backup)
    return st


def apply(membership_level: str | None = None, *, max_only: bool = False) -> dict[str, Any]:
    if is_cursor_running():
        action = "解锁 MAX" if max_only else "启用模型解锁"
        return {"ok": False, "error": f"请先关闭 IDE，再{action}", "running": True}
    if membership_level is not None and not max_only:
        set_membership_setting(membership_level)
    membership = get_membership_setting()
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
    try:
        for path in files:
            original = path.read_text(encoding="utf-8")
            next_text, stats = apply_to_content(
                original, membership["key"], max_only=max_only
            )
            _accumulate(total, stats)
            if next_text != original:
                changed[path] = next_text.encode("utf-8")
    except ModelUnlockError as exc:
        return {"ok": False, "error": str(exc), "backup": str(bak)}

    storage_sync: dict[str, Any] | None = None
    if not changed:
        st = status()
        st["ok"] = True
        st["skipped"] = True
        st["backup"] = str(bak)
        st["stats"] = total.__dict__
        st["message"] = (
            "MAX 开关补丁已是最新，无需重打。请确认已用启动器重启 IDE。"
            if max_only
            else "解锁规则已是最新，无需重打。请确认已用启动器重启 IDE。"
        )
        if not max_only:
            storage_sync = sync_storage_membership(membership["key"])
            st["storageSync"] = storage_sync
            if storage_sync.get("ok"):
                st["message"] += f" 已同步侧边栏为 {membership['label']}。"
        return st

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
    storage_sync = sync_storage_membership(membership["key"]) if not max_only else None
    st["storageSync"] = storage_sync
    if max_only:
        st["message"] = (
            f"已解锁 MAX 开关：显示MAX×{total.show_max}。"
            "请用启动器重启 IDE，并新开一轮对话。"
        )
    else:
        st["message"] = (
            f"已解锁：FREE×{total.model_lock} · 显示MAX×{total.show_max} · "
            f"命名视图×{total.named_view} · 目录×{total.catalog} · "
            f"绑卡短路×{total.maxmode} · 会员×{total.mem_pro} · fetch×{total.fetch} · "
            f"侧边栏={membership['label']}。"
            "请用启动器重启 IDE，并新开一轮对话。"
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
        _accumulate(total, stats)
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
    storage_sync = sync_storage_membership(DEFAULT_MEMBERSHIP)
    st["storageSync"] = storage_sync
    st["message"] = "已还原模型解锁，侧边栏已改回 Pro Plan。请用启动器重启 IDE。"
    return st
