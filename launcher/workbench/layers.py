"""扫描 workbench 上各补丁层的状态。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from launcher.workbench.markers import (
    MARKER_CATALOG,
    MARKER_FETCH,
    MARKER_FULL,
    MARKER_MAX,
    MARKER_MEM,
    MARKER_MODEL,
    MARKER_NAMED,
    MARKER_SHOW_MAX,
    MARKER_TREAT,
    MAX_MEM_INJECT,
)

BAJIE_PREFIX = "https://127.0.0.1:43111/__bajie/"
BAJIE_RE = re.compile(re.escape(BAJIE_PREFIX) + r"([^\"']+)")


@dataclass
class LayerScan:
    gateway_hits: int = 0
    model_lock: int = 0
    full_picker: int = 0
    treatment: int = 0
    named_view: int = 0
    catalog: int = 0
    mem_pro: int = 0
    max_mode: int = 0
    show_max: int = 0
    fetch_spoof: int = 0
    broken_show_max: int = 0

    @property
    def launcher_installed(self) -> bool:
        return (
            self.model_lock > 0
            or self.named_view > 0
            or self.catalog > 0
            or self.show_max > 0
            or self.fetch_spoof > 0
        )

    @property
    def corrupted(self) -> bool:
        return self.mem_pro > MAX_MEM_INJECT or self.broken_show_max > 0

    @property
    def max_only(self) -> bool:
        return self.show_max > 0 and not self.fetch_spoof and self.model_lock == 0

    def as_hits(self) -> dict[str, int]:
        return {
            "gateway": self.gateway_hits,
            "modelLock": self.model_lock,
            "fullPicker": self.full_picker,
            "treatment": self.treatment,
            "namedView": self.named_view,
            "catalog": self.catalog,
            "memPro": self.mem_pro,
            "maxMode": self.max_mode,
            "showMax": self.show_max,
            "fetchSpoof": self.fetch_spoof,
            "brokenShowMax": self.broken_show_max,
        }


def scan_content(text: str) -> LayerScan:
    broken = text.count("hideMaxToggle:!1;" + MARKER_SHOW_MAX)
    gateway = len(BAJIE_RE.findall(text))
    return LayerScan(
        gateway_hits=gateway,
        model_lock=text.count(MARKER_MODEL),
        full_picker=text.count(MARKER_FULL),
        treatment=text.count(MARKER_TREAT),
        named_view=text.count(MARKER_NAMED),
        catalog=text.count(MARKER_CATALOG),
        mem_pro=text.count(MARKER_MEM),
        max_mode=text.count(MARKER_MAX),
        show_max=text.count(MARKER_SHOW_MAX),
        fetch_spoof=text.count(MARKER_FETCH),
        broken_show_max=broken,
    )


def scan_files(files: list[Path]) -> LayerScan:
    total = LayerScan()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        layer = scan_content(text)
        total.gateway_hits += layer.gateway_hits
        total.model_lock += layer.model_lock
        total.full_picker += layer.full_picker
        total.treatment += layer.treatment
        total.named_view += layer.named_view
        total.catalog += layer.catalog
        total.mem_pro += layer.mem_pro
        total.max_mode += layer.max_mode
        total.show_max += layer.show_max
        total.fetch_spoof += layer.fetch_spoof
        total.broken_show_max += layer.broken_show_max
    return total


def strip_gateway_urls(text: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "https://" + match.group(1)

    return BAJIE_RE.sub(repl, text), count
