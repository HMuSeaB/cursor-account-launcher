"""账号存储 + 会话守卫配置。"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import threading
from ctypes import wintypes

from .token_utils import parse_token

WS_RE = re.compile(r"user_[A-Za-z0-9]+(?:::|%3A%3A)eyJ[A-Za-z0-9_.\-]+")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TOKEN_CONT_RE = re.compile(r"^[A-Za-z0-9_\-.=+/:%]+$")
_TOKEN_PRIORITY = {
    "access_token": 5,
    "accesstoken": 5,
    "ws_token": 5,
    "workoscursorsessiontoken": 5,
    "session_token": 4,
    "token": 3,
    "refresh_token": 1,
}


def _app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "CursorLauncher")


def _accounts_path() -> str:
    return os.path.join(_app_dir(), "accounts.json")


def _guard_path() -> str:
    return os.path.join(_app_dir(), "session_guard.json")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool):
    if os.name != "nt":
        return None
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _extract_from_obj(obj, out: list) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            prio = _TOKEN_PRIORITY.get(str(key).lower())
            if isinstance(value, str) and prio is not None:
                out.append((prio, value))
            else:
                _extract_from_obj(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _extract_from_obj(item, out)


def stitch_wrapped_tokens(text: str) -> str:
    """把聊天窗口折行的 JWT / WS Token 拼回一行，避免只收半截。"""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if out and stripped and _is_token_continuation(out[-1], stripped):
            out[-1] = out[-1].rstrip() + stripped
        else:
            out.append(line)
    return "\n".join(out)


def _is_token_continuation(prev: str, nxt: str) -> bool:
    prev_s = prev.strip()
    if not prev_s or not nxt:
        return False
    if "@" in nxt or re.search(r"[\u4e00-\u9fff]", nxt):
        return False
    if not _TOKEN_CONT_RE.fullmatch(nxt):
        return False
    if re.match(r"user_[A-Za-z0-9]+(?:::|%3A%3A)eyJ", nxt):
        return False
    if nxt.startswith("eyJ") and JWT_RE.match(nxt):
        return False
    if JWT_RE.search(prev_s):
        return False
    return bool(
        "eyJ" in prev_s
        or "::" in prev_s
        or "%3A%3A" in prev_s.upper()
        or re.search(r"user_[A-Za-z0-9]+$", prev_s)
    )


def _iter_token_matches(text: str) -> list[tuple[int, int, int, str]]:
    found: list[tuple[int, int, int, str]] = []
    covered: list[tuple[int, int]] = []
    for match in WS_RE.finditer(text):
        found.append((match.start(), match.end(), 5, match.group(0)))
        covered.append(match.span())
    for match in JWT_RE.finditer(text):
        start, end = match.span()
        # 同优先级下后收的会覆盖先收的：裸 JWT 若是某个 user_xxx::jwt 的一部分，
        # 收下它就会把 WS 前缀顶掉，设备管理和会话接口随后全部失效。
        if any(lo <= start and end <= hi for lo, hi in covered):
            continue
        found.append((start, end, 5, match.group(0)))
    found.sort(key=lambda row: row[0])
    return found


def tokens_from_text(text: str) -> list[tuple[int, str]]:
    return [(prio, token) for _, _, prio, token in _iter_token_matches(text or "")]


def parse_account_dump(text: str) -> list[tuple[int, str, str]]:
    """从杂乱粘贴中抽出 (priority, token, email)。邮箱取该 token 前方最近的一个。"""
    text = stitch_wrapped_tokens(text or "")
    emails = [(m.start(), m.end(), m.group(0)) for m in EMAIL_RE.finditer(text)]
    found = _iter_token_matches(text)
    out: list[tuple[int, str, str]] = []
    for i, (start, end, prio, token) in enumerate(found):
        prev_end = found[i - 1][1] if i else 0
        email = ""
        for es, _ee, ev in reversed(emails):
            if prev_end <= es < start:
                email = ev
                break
        out.append((prio, token, email))
    return out


def tokens_from_json_text(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    try:
        _extract_from_obj(json.loads(text), out)
    except Exception:
        pass
    return out


class AccountStore:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        path = _accounts_path()
        try:
            with open(path, "rb") as handle:
                envelope = json.loads(handle.read().decode("utf-8"))
        except Exception:
            return
        items = []
        if isinstance(envelope, dict) and envelope.get("enc") == "dpapi":
            blob = base64.b64decode(envelope.get("data", ""))
            dec = _dpapi(blob, protect=False)
            if dec:
                items = json.loads(dec.decode("utf-8"))
        elif isinstance(envelope, dict):
            items = envelope.get("items", [])
        for it in items:
            uid = it.get("id")
            token = it.get("token")
            if uid and token:
                self._items[uid] = {
                    "id": uid,
                    "label": it.get("label") or uid,
                    "token": token,
                    "_prio": it.get("_prio", 5),
                }

    def _save(self) -> None:
        os.makedirs(_app_dir(), exist_ok=True)
        payload = json.dumps(list(self._items.values()), ensure_ascii=False).encode("utf-8")
        enc = _dpapi(payload, protect=True)
        if enc is not None:
            envelope = {"v": 1, "enc": "dpapi", "data": base64.b64encode(enc).decode("ascii")}
        else:
            envelope = {"v": 1, "enc": "none", "items": list(self._items.values())}
        path = _accounts_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, ensure_ascii=False)
        os.replace(tmp, path)

    def _add_token(self, token: str, priority: int = 5, email: str = ""):
        user_id, _jwt, claims = parse_token(token)
        existing = self._items.get(user_id)
        pasted = (email or "").strip()
        claim = claims.get("email") if isinstance(claims.get("email"), str) else ""
        label_src = pasted or (claim.strip() if claim else "")
        if existing is None or priority >= existing.get("_prio", 0):
            label = label_src or (existing.get("label") if existing else None) or user_id
            self._items[user_id] = {
                "id": user_id,
                "label": label,
                "token": token.strip(),
                "_prio": priority,
            }
        return self._items[user_id]

    def _ingest(self, pairs: list[tuple]) -> list[dict]:
        touched: dict[str, dict] = {}
        with self._lock:
            for row in pairs:
                prio = int(row[0])
                token = row[1]
                extra = row[2] if len(row) > 2 else ""
                try:
                    item = self._add_token(token, prio, email=str(extra or ""))
                except Exception:
                    continue
                touched[item["id"]] = item
            if touched:
                self._save()
        return [{"id": v["id"], "label": v["label"]} for v in touched.values()]

    def add_text(self, text: str) -> list[dict]:
        stripped = (text or "").strip()
        if stripped[:1] in "{[":
            pairs = tokens_from_json_text(text) or parse_account_dump(text)
        else:
            pairs = parse_account_dump(text) or tokens_from_json_text(text)
        return self._ingest(pairs)

    def add_json_files(self, paths: list[str]) -> list[dict]:
        pairs: list[tuple[int, str]] = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    text = handle.read()
            except Exception:
                continue
            pairs.extend(tokens_from_json_text(text) or parse_account_dump(text))
        return self._ingest(pairs)

    def list(self) -> list[dict]:
        return [{"id": v["id"], "label": v["label"]} for v in self._items.values()]

    def get(self, account_id: str) -> dict | None:
        return self._items.get(account_id)

    def set_label(self, account_id: str, label: str) -> None:
        with self._lock:
            item = self._items.get(account_id)
            if item and label and item.get("label") != label:
                item["label"] = label
                self._save()

    def remove(self, account_id: str) -> None:
        with self._lock:
            if self._items.pop(account_id, None) is not None:
                self._save()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()


class SessionGuardStore:
    """每个账号的会话守卫：保留名单 + 定时巡检。"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        try:
            with open(_guard_path(), "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict):
                self._data = raw
        except Exception:
            self._data = {}

    def _save(self) -> None:
        os.makedirs(_app_dir(), exist_ok=True)
        path = _guard_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def get(self, account_id: str) -> dict:
        with self._lock:
            cfg = self._data.get(account_id) or {}
            return {
                "enabled": bool(cfg.get("enabled")),
                "mode": str(cfg.get("mode") or "whitelist"),
                "keepSessionIds": list(cfg.get("keepSessionIds") or []),
                "baselineSessionIds": list(cfg.get("baselineSessionIds") or []),
                "intervalSeconds": int(cfg.get("intervalSeconds") or 300),
            }

    def save(
        self,
        account_id: str,
        enabled: bool,
        keep_session_ids: list[str],
        interval_seconds: int = 300,
        mode: str = "whitelist",
        baseline_session_ids: list[str] | None = None,
    ) -> dict:
        with self._lock:
            prev = self._data.get(account_id) or {}
            self._data[account_id] = {
                "enabled": bool(enabled),
                "mode": mode if mode in {"whitelist", "auto_kick"} else "whitelist",
                "keepSessionIds": list(dict.fromkeys(keep_session_ids)),
                "baselineSessionIds": list(
                    dict.fromkeys(baseline_session_ids or prev.get("baselineSessionIds") or [])
                ),
                "intervalSeconds": max(60, int(interval_seconds or 300)),
            }
            self._save()
            return self.get(account_id)

    def set_baseline(self, account_id: str, session_ids: list[str]) -> None:
        with self._lock:
            cfg = self._data.setdefault(account_id, {})
            cfg["baselineSessionIds"] = list(dict.fromkeys(session_ids))
            self._save()

    def list_enabled(self) -> list[tuple[str, dict]]:
        with self._lock:
            return [(aid, cfg) for aid, cfg in self._data.items() if cfg.get("enabled")]
