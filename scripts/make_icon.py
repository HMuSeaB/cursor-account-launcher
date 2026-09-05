"""Render the launcher app icon (PNG + multi-size ICO)."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
WEB_DIR = ROOT / "web"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def save_ico(path: Path, images: list[Image.Image]) -> None:
    """Write a PNG-in-ICO file. Pillow's ICO saver often drops extra sizes."""
    blobs: list[bytes] = []
    offset = 6 + 16 * len(images)
    entries: list[tuple[int, int, int, int]] = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        blobs.append(data)
        w = 0 if im.width >= 256 else im.width
        h = 0 if im.height >= 256 else im.height
        entries.append((w, h, len(data), offset))
        offset += len(data)
    with path.open("wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(images)))
        for width, height, size, off in entries:
            fh.write(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, size, off))
        for data in blobs:
            fh.write(data)


def _u(size: int, x: float) -> int:
    return max(0, min(size - 1, round(x * size / 1024)))


def render_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    inset = _u(size, 48)
    radius = max(3, _u(size, 220))
    draw.rounded_rectangle(
        [inset, inset, size - inset - 1, size - inset - 1],
        radius=radius,
        fill=(28, 25, 23, 255),
    )

    bar_r = max(1, _u(size, 56))
    draw.rounded_rectangle(
        [_u(size, 214), _u(size, 200), _u(size, 348), _u(size, 824)],
        radius=bar_r,
        fill=(214, 211, 205, 255),
    )
    if size >= 32:
        card_r = max(3, _u(size, 40))
        draw.rounded_rectangle(
            [_u(size, 392), _u(size, 268), _u(size, 838), _u(size, 548)],
            radius=card_r,
            fill=(120, 113, 108, 255),
        )
        draw.rounded_rectangle(
            [_u(size, 428), _u(size, 428), _u(size, 868), _u(size, 812)],
            radius=card_r,
            fill=(250, 249, 247, 255),
        )
        play = [
            (_u(size, 548), _u(size, 524)),
            (_u(size, 548), _u(size, 724)),
            (_u(size, 722), _u(size, 624)),
        ]
        draw.polygon(play, fill=(28, 25, 23, 255))
    else:
        # 16/24px：资源管理器列表视图只用这一档；必须能看出播放键，不能只剩一根竖条
        play = [
            (_u(size, 430), _u(size, 300)),
            (_u(size, 430), _u(size, 724)),
            (_u(size, 780), _u(size, 512)),
        ]
        draw.polygon(play, fill=(250, 249, 247, 255))
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    images = {size: render_icon(size) for size in SIZES}
    images[512].save(OUT_DIR / "icon.png", format="PNG")
    images[64].save(WEB_DIR / "icon.png", format="PNG")
    save_ico(OUT_DIR / "icon.ico", [images[s] for s in ICO_SIZES])
    print("wrote", OUT_DIR / "icon.ico")
    print("wrote", OUT_DIR / "icon.png")
    print("wrote", WEB_DIR / "icon.png")


if __name__ == "__main__":
    main()
