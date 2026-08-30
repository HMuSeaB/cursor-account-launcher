"""Extract small windows around known needles from workbench backups."""

from __future__ import annotations

import os
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "workbench_snippets.js"

NEEDLES = [
    "hideMaxToggle:",
    "_membershipType=()=>this.storageService.get(",
    "hasResolvedTeamMembership:",
    "isPotentiallyFreeUserModelPickerLocked:",
    "127.0.0.1:43111/__bajie/",
]


def candidates() -> list[Path]:
    base = Path(os.environ.get("LOCALAPPDATA") or "") / "CursorLauncher"
    out: list[Path] = []
    off = base / "workbench" / "official" / "workbench.desktop.main.js"
    if off.is_file():
        out.append(off)
    mu = base / "model-unlock" / "backups"
    if mu.is_dir():
        for entry in sorted(mu.iterdir(), reverse=True)[:5]:
            f = entry / "workbench.desktop.main.js"
            if f.is_file():
                out.append(f)
    return out


def window_around(text: str, idx: int, left: int = 40, right: int = 120) -> str:
    start = max(0, idx - left)
    end = min(len(text), idx + right)
    return text[start:end]


def main() -> None:
    chunks: list[str] = []
    seen: set[str] = set()
    for path in candidates():
        print("scan", path.name, path.parent.name)
        text = path.read_text(encoding="utf-8", errors="ignore")
        if text.count("MODEL_MEM_PRO_V1") > 4:
            print("  skip corrupted")
            continue
        for needle in NEEDLES:
            idx = 0
            found = 0
            while found < 3:
                pos = text.find(needle, idx)
                if pos < 0:
                    break
                chunk = window_around(text, pos)
                idx = pos + len(needle)
                found += 1
                if "MODEL_SHOW_MAX" in chunk and "hideMaxToggle:!1" in chunk:
                    continue
                if chunk in seen:
                    continue
                seen.add(chunk)
                chunks.append(chunk)
                print("  HIT", needle[:28], len(chunk))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n---\n".join(chunks) + "\n", encoding="utf-8")
    print("wrote", OUT, "parts", len(chunks))


if __name__ == "__main__":
    main()
