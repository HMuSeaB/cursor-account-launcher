"""写入 workbench 前的预检。"""

from __future__ import annotations

from launcher.workbench.markers import MARKER_MEM, MARKER_SHOW_MAX, MAX_MEM_INJECT
from launcher.workbench.layers import LayerScan, scan_content


class PreflightError(RuntimeError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


def validate_content(text: str, *, mem_limit: int = MAX_MEM_INJECT) -> list[str]:
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

    # 粗检：补丁后文件不应比原文件短得离谱（截断迹象）
    if len(text) < 1024:
        issues.append("workbench 内容过短，可能已被截断")

    return issues


def assert_safe(text: str, *, mem_limit: int = MAX_MEM_INJECT) -> LayerScan:
    issues = validate_content(text, mem_limit=mem_limit)
    if issues:
        raise PreflightError(issues)
    return scan_content(text)
