"""写入 workbench 前的预检（含粗语法平衡检查）。"""

from __future__ import annotations

from launcher.workbench.layers import LayerScan, scan_content
from launcher.workbench.markers import MARKER_SHOW_MAX, MAX_MEM_INJECT


class PreflightError(RuntimeError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


def _balance_score(text: str) -> dict[str, int]:
    """忽略字符串/正则字面量的粗括号计数（minified bundle 够用）。"""
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = {v: k for k, v in pairs.items()}
    stack: list[str] = []
    i = 0
    n = len(text)
    in_str = False
    quote = ""
    escape = False
    while i < n:
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = True
            quote = ch
            i += 1
            continue
        if ch in pairs:
            stack.append(ch)
        elif ch in closing:
            if not stack or stack[-1] != closing[ch]:
                return {"ok": 0, "depth": len(stack), "mismatch": 1}
            stack.pop()
        i += 1
    return {"ok": 1 if not stack and not in_str else 0, "depth": len(stack), "mismatch": 0}


def validate_content(
    text: str,
    *,
    mem_limit: int = MAX_MEM_INJECT,
    original: str | None = None,
) -> list[str]:
    issues: list[str] = []
    scan = scan_content(text)

    if scan.broken_show_max > 0:
        issues.append(
            f"检测到 {scan.broken_show_max} 处 hideMaxToggle:!1; 语法错误（会导致黑屏）"
        )
    if scan.mem_pro > mem_limit:
        issues.append(
            f"会员短路补丁命中 {scan.mem_pro} 处（上限 {mem_limit}），疑似正则误伤"
        )
    if "hideMaxToggle:!1;" in text and MARKER_SHOW_MAX not in text:
        issues.append("存在裸 hideMaxToggle:!1; 且无修复标记")

    if len(text) < 1024:
        issues.append("workbench 内容过短，可能已被截断")

    bal = _balance_score(text)
    if not bal["ok"]:
        issues.append(
            f"括号/字符串可能不平衡（depth={bal['depth']} mismatch={bal['mismatch']}）"
        )

    if original is not None and original:
        # 补丁不应把文件砍短超过 5%，也不该暴涨超过 2MB（误注入）
        if len(text) < int(len(original) * 0.95):
            issues.append(
                f"补丁后长度异常缩短（{len(original)} → {len(text)}），疑似截断"
            )
        if len(text) > len(original) + 2_000_000:
            issues.append("补丁后长度暴涨，疑似误注入")

        orig_bal = _balance_score(original)
        if orig_bal["ok"] and not bal["ok"]:
            issues.append("原文件括号平衡，补丁后失衡 — 拒绝写入")

    return issues


def assert_safe(
    text: str,
    *,
    mem_limit: int = MAX_MEM_INJECT,
    original: str | None = None,
) -> LayerScan:
    issues = validate_content(text, mem_limit=mem_limit, original=original)
    if issues:
        raise PreflightError(issues)
    return scan_content(text)
