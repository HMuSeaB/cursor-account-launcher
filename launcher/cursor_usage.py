"""Cursor 账号用量 / 套餐额度查询（移植自 BajieAsk cursor-dashboard-api）。"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests

from .token_utils import UA, email_from_claims, parse_token

TIMEOUT = 30
USAGE_API2 = "https://api2.cursor.sh/auth/usage-summary"
AUTH_ME = "https://cursor.com/api/auth/me"
DASH_TEAMS = "https://cursor.com/api/dashboard/teams"
DASH_TEAM = "https://cursor.com/api/dashboard/team"
SAND_USAGE = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus"
AGG_USAGE = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetAggregatedUsageEvents"
MONTHLY_INVOICE = "https://cursor.com/api/dashboard/get-monthly-invoice"
AGG_USAGE_DASH = "https://cursor.com/api/dashboard/get-aggregated-usage-events"


def _session_token(raw: str) -> str:
    user_id, jwt, _ = parse_token(raw)
    return f"{user_id}::{jwt}"


def _bearer_headers(jwt: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }


def _to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)) and value > 0:
        return int(value if value > 1e12 else value * 1000)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            num = float(text)
            if num > 0:
                return int(num if num > 1e12 else num * 1000)
        except ValueError:
            pass
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            return 0
    return 0


def _to_usd(value: Any) -> float:
    if value is None or not isinstance(value, (int, float)):
        return 0.0
    if isinstance(value, int):
        return value / 100.0
    return float(value)


def _parse_included_pcts(merged: dict) -> tuple[float, float]:
    total_pct, api_pct = -1.0, -1.0
    texts = []
    for key in ("autoModelSelectedDisplayMessage", "namedModelSelectedDisplayMessage"):
        val = merged.get(key)
        if isinstance(val, str) and val.strip():
            texts.append(val.strip())
    re_total = re.compile(r"You['\u2019]ve used\s+(\d+(?:\.\d+)?)%\s+of your included total usage", re.I)
    re_api = re.compile(r"You['\u2019]ve used\s+(\d+(?:\.\d+)?)%\s+of your included API usage", re.I)
    for text in texts:
        m = re_total.search(text)
        if m:
            total_pct = min(100.0, float(m.group(1)))
        m = re_api.search(text)
        if m:
            api_pct = min(100.0, float(m.group(1)))
    return total_pct, api_pct


def summarize_usage(merged: dict, extras: dict | None = None) -> dict:
    extras = extras or {}
    iu = merged.get("individualUsage") if isinstance(merged.get("individualUsage"), dict) else {}
    plan = iu.get("plan") if isinstance(iu.get("plan"), dict) else {}
    breakdown = plan.get("breakdown") if isinstance(plan.get("breakdown"), dict) else {}
    on_demand = iu.get("onDemand") if isinstance(iu.get("onDemand"), dict) else {}

    cost_usd = 0.0
    cost_max = 0.0
    used = plan.get("used")
    limit = plan.get("limit")
    if isinstance(breakdown.get("included"), (int, float)) or isinstance(breakdown.get("bonus"), (int, float)):
        cost_max = _to_usd(breakdown.get("included") or 0) + _to_usd(breakdown.get("bonus") or 0)
        cost_usd = _to_usd(used or 0)
    else:
        for key in ("standard", "giftCredits", "overdue"):
            part = breakdown.get(key)
            if isinstance(part, dict):
                if isinstance(part.get("cents"), (int, float)):
                    cost_usd += part["cents"] / 100.0
                if isinstance(part.get("maxCents"), (int, float)):
                    cost_max += part["maxCents"] / 100.0
    if on_demand.get("enabled") and isinstance(on_demand.get("used"), (int, float)):
        cost_usd += _to_usd(on_demand["used"])

    email = ""
    for key in ("usageSummaryEmail", "email"):
        val = merged.get(key)
        if isinstance(val, str) and val.strip():
            email = val.strip()
            break

    included_total, included_api = _parse_included_pcts(merged)
    api_pct = plan.get("apiPercentUsed")
    auto_pct = plan.get("autoPercentUsed")
    usage_pct = plan.get("totalPercentUsed")
    pro_expiry = _to_ms(merged.get("billingCycleEnd"))

    usage_line = ""
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)):
        usage_line = f"{used}/{limit}"
    elif isinstance(used, (int, float)):
        usage_line = f"{used}/—"

    gift_usd = 0.0
    gift = breakdown.get("giftCredits")
    if isinstance(gift, dict) and isinstance(gift.get("maxCents"), (int, float)):
        gift_usd = gift["maxCents"] / 100.0

    return {
        "email": email,
        "membershipType": str(merged.get("membershipType") or ""),
        "usageLine": usage_line,
        "costUsd": round(cost_usd, 2),
        "costMaxUsd": round(cost_max, 2),
        "usagePct": float(usage_pct) if isinstance(usage_pct, (int, float)) else -1,
        "apiPercentUsed": float(api_pct) if isinstance(api_pct, (int, float)) else included_api,
        "autoPercentUsed": float(auto_pct) if isinstance(auto_pct, (int, float)) else included_total,
        "includedTotalPct": included_total,
        "includedApiPct": included_api,
        "proExpiryMs": pro_expiry,
        "onDemandUsd": round(_to_usd(on_demand.get("used")), 2) if on_demand.get("enabled") else 0,
        "onDemandLimit": on_demand.get("limit"),
        "giftUsd": round(gift_usd, 2),
        "isUnlimited": bool(merged.get("isUnlimited")),
        "botPercent": extras.get("botPercent", -1),
        "botResetMs": extras.get("botResetMs", 0),
        "periodCostUsd": extras.get("periodCostUsd", 0),
        "requestCount30d": extras.get("requestCount30d", 0),
        "autoModelMessage": merged.get("autoModelSelectedDisplayMessage") or "",
        "namedModelMessage": merged.get("namedModelSelectedDisplayMessage") or "",
        "billingCycleStartMs": _to_ms(merged.get("billingCycleStart")),
        "billingCycleEndMs": pro_expiry,
    }


def _cookie_headers(session_token: str) -> dict[str, str]:
    parts = session_token.split("::", 1)
    user_id = parts[0] if len(parts) > 1 else ""
    access = parts[1] if len(parts) > 1 else session_token
    cookies = [f"WorkosCursorSessionToken={quote(session_token, safe='')}"]
    if user_id:
        cookies.append(f"cursor-web-target-synced-user={user_id}")
    return {
        "Cookie": "; ".join(cookies),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Authorization": f"Bearer {access}",
        "Referer": "https://cursor.com/dashboard",
    }


def _dashboard_post_headers(session_token: str, referer: str = "https://cursor.com/dashboard/billing") -> dict[str, str]:
    headers = _cookie_headers(session_token)
    headers.update(
        {
            "Accept": "*/*",
            "Origin": "https://cursor.com",
            "Referer": referer,
        }
    )
    return headers


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return 0
    return 0


def _model_group(model: str) -> str:
    name = (model or "").lower()
    if name == "auto" or name.startswith(("cursor-", "composer-")):
        return "cursor"
    return "other"


def _parse_model_aggregations(aggregations: list[Any]) -> dict[str, Any]:
    """把 get-aggregated-usage-events 的 aggregations 整理成 billing 页同款结构。"""
    included_cursor: list[dict] = []
    included_other: list[dict] = []
    on_demand: list[dict] = []
    included_tokens = 0
    on_demand_usd = 0.0

    for item in aggregations:
        if not isinstance(item, dict):
            continue
        model = str(item.get("modelIntent") or item.get("model") or "").strip()
        if not model:
            continue
        tokens = (
            _as_int(item.get("inputTokens"))
            + _as_int(item.get("outputTokens"))
            + _as_int(item.get("cacheReadTokens"))
            + _as_int(item.get("cacheWriteTokens"))
        )
        cents = float(item.get("totalCents") or 0)
        tier = item.get("tier")
        if tier in (2, "2"):
            is_on_demand = False
        elif tier is not None:
            is_on_demand = True
        else:
            is_on_demand = cents > 0 and tokens == 0
        if not is_on_demand and cents <= 0 and tokens <= 0:
            continue

        row = {
            "model": model,
            "tokens": tokens,
            "costUsd": round(cents / 100.0, 2),
            "group": _model_group(model),
        }
        if is_on_demand:
            on_demand.append(row)
            on_demand_usd += cents / 100.0
        else:
            if row["group"] == "cursor":
                included_cursor.append(row)
            else:
                included_other.append(row)
            included_tokens += tokens

    for bucket in (included_cursor, included_other, on_demand):
        bucket.sort(key=lambda x: x.get("tokens") or x.get("costUsd") or 0, reverse=True)

    total_included = included_tokens or 1
    for bucket in (included_cursor, included_other):
        for row in bucket:
            row["tokenPct"] = round((row["tokens"] / total_included) * 100, 1)

    on_total_tokens = sum(r["tokens"] for r in on_demand) or sum(
        1 for r in on_demand if r.get("costUsd")
    )
    on_base = on_total_tokens if on_total_tokens else len(on_demand) or 1
    for row in on_demand:
        if row["tokens"] > 0:
            row["tokenPct"] = round((row["tokens"] / on_base) * 100, 1)
        elif on_demand_usd > 0:
            row["tokenPct"] = round((row["costUsd"] / on_demand_usd) * 100, 1)

    return {
        "included": {
            "cursorModels": included_cursor,
            "otherModels": included_other,
            "totalTokens": included_tokens,
        },
        "onDemand": {
            "models": on_demand,
            "totalUsd": round(on_demand_usd, 2),
        },
    }


def fetch_model_usage(token: str, proxies: dict | None = None) -> dict[str, Any]:
    """拉取当前计费周期的按模型 token / 费用明细（对齐 cursor.com/dashboard/billing）。"""
    session = _session_token(token)
    headers = _dashboard_post_headers(session)

    period_start_ms = 0
    period_end_ms = int(time.time() * 1000)
    try:
        inv_resp = requests.post(
            MONTHLY_INVOICE,
            headers=headers,
            json={"useCurrentCycle": True},
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if inv_resp.ok:
            inv = inv_resp.json()
            if isinstance(inv, dict):
                period_start_ms = _as_int(inv.get("periodStartMs"))
                end_ms = _as_int(inv.get("periodEndMs"))
                if end_ms > 0:
                    period_end_ms = end_ms
    except Exception:
        pass

    if period_start_ms <= 0:
        merged = fetch_usage_summary(token, proxies=proxies)
        period_start_ms = _to_ms(merged.get("billingCycleStart"))
        end_ms = _to_ms(merged.get("billingCycleEnd"))
        if end_ms > 0:
            period_end_ms = end_ms
    if period_start_ms <= 0:
        period_start_ms = period_end_ms - 30 * 86400000

    aggregations: list[Any] = []
    try:
        agg_resp = requests.post(
            AGG_USAGE_DASH,
            headers=headers,
            json={"teamId": -1, "startDate": period_start_ms},
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if agg_resp.ok:
            body = agg_resp.json()
            if isinstance(body, dict) and isinstance(body.get("aggregations"), list):
                aggregations = body["aggregations"]
    except Exception:
        pass

    if not aggregations:
        _, jwt, _ = parse_token(token)
        try:
            api2_resp = requests.post(
                AGG_USAGE,
                headers={**_bearer_headers(jwt), "connect-protocol-version": "1"},
                json={"startDate": str(period_start_ms), "endDate": str(period_end_ms)},
                timeout=TIMEOUT,
                proxies=proxies or {},
            )
            if api2_resp.ok:
                body = api2_resp.json()
                if isinstance(body, dict) and isinstance(body.get("aggregations"), list):
                    aggregations = body["aggregations"]
        except Exception:
            pass

    if not aggregations:
        return {
            "ok": False,
            "error": "暂无模型用量数据",
            "periodStartMs": period_start_ms,
            "periodEndMs": period_end_ms,
        }

    breakdown = _parse_model_aggregations(aggregations)
    return {
        "ok": True,
        "periodStartMs": period_start_ms,
        "periodEndMs": period_end_ms,
        **breakdown,
    }


def _pick_email(data: dict | None) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("email", "usageSummaryEmail", "name"):
        val = data.get(key)
        if isinstance(val, str) and "@" in val:
            return val.strip()
    return ""


def fetch_auth_me_email(token: str, proxies: dict | None = None) -> str:
    session = _session_token(token)
    try:
        resp = requests.get(
            AUTH_ME,
            headers=_cookie_headers(session),
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if resp.ok:
            return _pick_email(resp.json())
    except Exception:
        pass
    return ""


def fetch_team_email(token: str, proxies: dict | None = None) -> str:
    session = _session_token(token)
    headers = _dashboard_post_headers(session)
    try:
        teams_resp = requests.post(
            DASH_TEAMS,
            headers=headers,
            json={},
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if not teams_resp.ok:
            return ""
        teams = teams_resp.json().get("teams") if isinstance(teams_resp.json(), dict) else []
        if not isinstance(teams, list) or not teams:
            return ""
        team_id = teams[0].get("id")
        if team_id is None:
            return ""
        team_resp = requests.post(
            DASH_TEAM,
            headers=headers,
            json={"teamId": team_id},
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if team_resp.ok:
            return _pick_email(team_resp.json())
    except Exception:
        pass
    return ""


def resolve_account_email(token: str, merged: dict | None = None, proxies: dict | None = None) -> str:
    merged = merged or {}
    email = _pick_email(merged)
    if email:
        return email
    try:
        _, _, claims = parse_token(token)
        email = email_from_claims(claims)
        if email:
            return email
    except Exception:
        pass
    email = fetch_auth_me_email(token, proxies=proxies)
    if email:
        return email
    return fetch_team_email(token, proxies=proxies)


def fetch_usage_summary(token: str, proxies: dict | None = None) -> dict:
    session = _session_token(token)
    parts = session.split("::", 1)
    access = parts[1] if len(parts) > 1 else session
    if not access:
        return {"_error": "no_credentials"}

    resp = requests.get(
        USAGE_API2,
        headers=_bearer_headers(access),
        timeout=TIMEOUT,
        proxies=proxies or {},
    )
    if resp.status_code in (401, 403):
        return {"_error": "auth_failed", "status": resp.status_code}
    if not resp.ok:
        return {"_error": "http_error", "status": resp.status_code, "raw": resp.text[:200]}
    try:
        data = resp.json()
    except Exception:
        return {"_error": "parse_error"}
    if not isinstance(data, dict):
        return {"_error": "parse_error"}
    if isinstance(data.get("email"), str):
        data["usageSummaryEmail"] = data["email"].strip()
    email = resolve_account_email(token, data, proxies=proxies)
    if email:
        data["usageSummaryEmail"] = email
        data["email"] = email
    return data


def fetch_sand_usage(token: str, proxies: dict | None = None) -> dict:
    _, jwt, _ = parse_token(token)
    try:
        resp = requests.post(
            SAND_USAGE,
            headers={**_bearer_headers(jwt), "connect-protocol-version": "1"},
            data="{}",
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if not resp.ok:
            return {}
        body = resp.json()
        if not isinstance(body, dict):
            return {}
        return {
            "botPercent": body.get("usagePercent"),
            "botResetMs": _to_ms(body.get("nextResetTimestampUtc")),
            "botPlan": body.get("grokPlanLabel") or "",
        }
    except Exception:
        return {}


def fetch_period_stats(token: str, days: int = 30, proxies: dict | None = None) -> dict:
    _, jwt, _ = parse_token(token)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86400000
    try:
        resp = requests.post(
            AGG_USAGE,
            headers={**_bearer_headers(jwt), "connect-protocol-version": "1"},
            json={"startDate": str(start_ms), "endDate": str(end_ms)},
            timeout=TIMEOUT,
            proxies=proxies or {},
        )
        if not resp.ok:
            return {"periodCostUsd": 0, "requestCount30d": 0}
        body = resp.json()
        aggs = body.get("aggregations") if isinstance(body, dict) else []
        if not isinstance(aggs, list):
            return {"periodCostUsd": 0, "requestCount30d": 0}
        total_cents = 0.0
        total_requests = 0
        for item in aggs:
            if not isinstance(item, dict):
                continue
            total_cents += float(item.get("totalCents") or 0)
            total_requests += int(item.get("numRequests") or item.get("count") or 0)
        return {
            "periodCostUsd": round(total_cents / 100.0, 2),
            "requestCount30d": total_requests,
        }
    except Exception:
        return {"periodCostUsd": 0, "requestCount30d": 0}


def refresh_account_usage(token: str, proxies: dict | None = None) -> dict:
    merged = fetch_usage_summary(token, proxies=proxies)
    if merged.get("_error"):
        err = merged["_error"]
        msg = {"auth_failed": "登录失效", "http_error": f"HTTP {merged.get('status')}", "parse_error": "响应解析失败"}.get(err, err)
        return {"ok": False, "error": msg}

    extras = {}
    extras.update(fetch_sand_usage(token, proxies=proxies))
    extras.update(fetch_period_stats(token, proxies=proxies))

    snapshot = summarize_usage(merged, extras)
    email = snapshot.get("email") or resolve_account_email(token, merged, proxies=proxies)
    if email:
        snapshot["email"] = email
    snapshot["lastRefreshed"] = int(time.time() * 1000)
    snapshot["ok"] = True
    return snapshot
