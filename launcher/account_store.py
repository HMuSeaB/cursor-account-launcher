"""扩展账号存储：用量快照、邮箱密码、标签分组。"""

from __future__ import annotations

import base64
import json
import os
import threading
import time

from .accounts import (
    AccountStore as _BaseStore,
    SessionGuardStore,
    _accounts_path,
    _app_dir,
    _dpapi,
    tokens_from_json_text,
    tokens_from_text,
)
from .token_utils import parse_token


def _has_ws_token(token: str | None) -> bool:
    text = str(token or "")
    return "::" in text or "%3a%3a" in text.lower()

_USAGE_FIELDS = (
    "email",
    "membershipType",
    "usageLine",
    "costUsd",
    "costMaxUsd",
    "usagePct",
    "apiPercentUsed",
    "autoPercentUsed",
    "includedTotalPct",
    "includedApiPct",
    "proExpiryMs",
    "botPercent",
    "botResetMs",
    "periodCostUsd",
    "requestCount30d",
    "onDemandUsd",
    "giftUsd",
    "lastRefreshed",
    "err",
    "autoModelMessage",
    "namedModelMessage",
    "billingCycleStartMs",
    "billingCycleEndMs",
)


class AccountStore(_BaseStore):
    def _normalize_item(self, it: dict) -> dict:
        uid = it.get("id")
        token = it.get("token")
        if not uid or not token:
            return {}
        item = {
            "id": uid,
            "label": it.get("label") or uid,
            "token": token,
            "_prio": it.get("_prio", 5),
            "email": it.get("email") or "",
            "passwordEnc": it.get("passwordEnc") or "",
            "refreshTokenEnc": it.get("refreshTokenEnc") or "",
            "group": it.get("group") or "未分组",
            "tags": list(it.get("tags") or []),
            "remark": it.get("remark") or "",
            "createdAt": int(it.get("createdAt") or time.time() * 1000),
            "deviceIds": dict(it.get("deviceIds") or {}) if isinstance(it.get("deviceIds"), dict) else {},
        }
        for key in _USAGE_FIELDS:
            if key in it:
                item[key] = it[key]
        return item

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
            normalized = self._normalize_item(it)
            if normalized:
                self._items[normalized["id"]] = normalized

    def _add_token(self, token: str, priority: int = 5):
        user_id, _jwt, claims = parse_token(token)
        existing = self._items.get(user_id)
        email = claims.get("email") or ""
        if existing is None:
            self._items[user_id] = {
                "id": user_id,
                "label": email or user_id,
                "token": token.strip(),
                "_prio": priority,
                "email": email,
                "passwordEnc": "",
                "group": "未分组",
                "tags": [],
                "remark": "",
                "createdAt": int(time.time() * 1000),
                "deviceIds": {},
                "refreshTokenEnc": "",
            }
        elif priority >= existing.get("_prio", 0):
            existing["token"] = token.strip()
            existing["_prio"] = priority
            if email and not existing.get("email"):
                existing["email"] = email
                existing["label"] = email
        return self._items[user_id]

    def _public_view(self, item: dict, *, include_token: bool = False) -> dict:
        out = {
            "id": item["id"],
            "label": item.get("label") or item["id"],
            "email": item.get("email") or item.get("label") or "",
            "group": item.get("group") or "未分组",
            "tags": list(item.get("tags") or []),
            "remark": item.get("remark") or "",
            "hasPassword": bool(item.get("passwordEnc")),
            "createdAt": item.get("createdAt") or 0,
        }
        for key in _USAGE_FIELDS:
            if key in item:
                out[key] = item[key]
        out["hasWsToken"] = _has_ws_token(item.get("token"))
        out["hasDeviceIds"] = bool((item.get("deviceIds") or {}).get("machineId") or (item.get("deviceIds") or {}).get("serviceMachineId"))
        out["hasRefreshToken"] = bool(item.get("refreshTokenEnc"))
        if include_token:
            out["token"] = item.get("token") or ""
            out["deviceIds"] = dict(item.get("deviceIds") or {})
        return out

    def list(self) -> list[dict]:
        return [self._public_view(v) for v in self._items.values()]

    def get_detail(self, account_id: str) -> dict | None:
        item = self._items.get(account_id)
        if not item:
            return None
        detail = self._public_view(item, include_token=True)
        detail["password"] = self.get_password(account_id)
        return detail

    def set_password(self, account_id: str, password: str) -> None:
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return
            if not password:
                item["passwordEnc"] = ""
            else:
                enc = _dpapi(password.encode("utf-8"), protect=True)
                item["passwordEnc"] = base64.b64encode(enc).decode("ascii") if enc else password
            self._save()

    def get_password(self, account_id: str) -> str:
        item = self._items.get(account_id)
        if not item or not item.get("passwordEnc"):
            return ""
        raw = item["passwordEnc"]
        try:
            dec = _dpapi(base64.b64decode(raw), protect=False)
            return dec.decode("utf-8") if dec else raw
        except Exception:
            return raw

    def update_meta(
        self,
        account_id: str,
        *,
        email: str | None = None,
        password: str | None = None,
        group: str | None = None,
        tags: list | None = None,
        remark: str | None = None,
    ) -> dict | None:
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return None
            if email is not None:
                item["email"] = email.strip()
                if email.strip():
                    item["label"] = email.strip()
            if group is not None:
                item["group"] = group.strip() or "未分组"
            if tags is not None:
                item["tags"] = [str(t).strip() for t in tags if str(t).strip()]
            if remark is not None:
                item["remark"] = remark.strip()
            self._save()
        if password is not None:
            self.set_password(account_id, password)
        return self._public_view(self._items[account_id])

    def set_refresh_token(self, account_id: str, refresh_token: str) -> None:
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return
            text = (refresh_token or "").strip()
            if not text:
                item["refreshTokenEnc"] = ""
            else:
                enc = _dpapi(text.encode("utf-8"), protect=True)
                item["refreshTokenEnc"] = base64.b64encode(enc).decode("ascii") if enc else text
            self._save()

    def get_refresh_token(self, account_id: str) -> str:
        item = self._items.get(account_id)
        if not item or not item.get("refreshTokenEnc"):
            return ""
        raw = item["refreshTokenEnc"]
        try:
            dec = _dpapi(base64.b64decode(raw), protect=False)
            return dec.decode("utf-8") if dec else raw
        except Exception:
            return raw

    def set_device_ids(self, account_id: str, device_ids: dict) -> dict | None:
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return None
            cleaned = {}
            for key in (
                "machineId",
                "telemetryMachineId",
                "macMachineId",
                "devDeviceId",
                "sqmId",
                "serviceMachineId",
                "machineGuid",
            ):
                val = device_ids.get(key) if device_ids else None
                if val:
                    cleaned[key] = str(val)
            item["deviceIds"] = cleaned
            self._save()
            return self._public_view(item)

    def get_device_ids(self, account_id: str) -> dict:
        item = self._items.get(account_id)
        if not item:
            return {}
        return dict(item.get("deviceIds") or {})

    def update_token(self, account_id: str, token: str) -> dict | None:
        text = (token or "").strip()
        if not text:
            return None
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return None
            item["token"] = text
            self._save()
            return self._public_view(item, include_token=True)

    def update_usage_snapshot(self, account_id: str, snapshot: dict) -> dict | None:
        with self._lock:
            item = self._items.get(account_id)
            if not item:
                return None
            err = snapshot.get("err") or snapshot.get("error")
            if err and not snapshot.get("ok", True):
                item["err"] = str(err)
                item["lastRefreshed"] = int(time.time() * 1000)
            else:
                item.pop("err", None)
                for key in _USAGE_FIELDS:
                    if key in snapshot:
                        item[key] = snapshot[key]
                if snapshot.get("email"):
                    item["email"] = snapshot["email"]
                    item["label"] = snapshot["email"]
                elif not item.get("email"):
                    try:
                        from .token_utils import email_from_claims, parse_token

                        _, _, claims = parse_token(item["token"])
                        claim_email = email_from_claims(claims)
                        if claim_email:
                            item["email"] = claim_email
                            item["label"] = claim_email
                    except Exception:
                        pass
                item["lastRefreshed"] = snapshot.get("lastRefreshed") or int(time.time() * 1000)
            self._save()
            return self._public_view(item)

    def list_groups(self) -> list[str]:
        groups = {v.get("group") or "未分组" for v in self._items.values()}
        return sorted(groups)

    def list_tags(self) -> list[str]:
        tags: set[str] = set()
        for v in self._items.values():
            tags.update(v.get("tags") or [])
        return sorted(tags)
