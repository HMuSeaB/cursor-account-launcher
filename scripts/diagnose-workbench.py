#!/usr/bin/env python3
"""命令行 workbench 全栈诊断。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher.workbench.diagnostic import run_full_diagnostic


def main() -> int:
    report = run_full_diagnostic()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("ok"):
        return 1
    if not report.get("healthy"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
