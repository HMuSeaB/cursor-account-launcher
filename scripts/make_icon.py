"""Render the launcher app icon (PNG + multi-size ICO)."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
WEB_DIR = ROOT / "web"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 夜色：暖黑底 + 暮粉光晕 + 新月，不是播放键
NIGHT_TOP = (42, 32, 40, 255)
NIGHT_BOT = (12, 10, 14, 255)
BLOOM = (196, 150, 168, 255)
CRESCENT = (246, 236, 232, 255)
ORB = (255, 248, 242, 255)
SATELLITE = (214, 176, 188, 255)
SAT_DIM = (120, 88, 102, 255)


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


def _vertical_fill(size: int, top: tuple[int, ...], bottom: tuple[int, ...]) -> Image.Image:
    img = Image.new("RGBA", (size, size), bottom)
    px = img.load()
    for y in range(size):
        t = (y / max(1, size - 1)) ** 1.15
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4))
        for x in range(size):
            px[x, y] = color
    return img


def _rounded_mask(size: int, inset: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [inset, inset, size - inset - 1, size - inset - 1],
        radius=radius,
        fill=255,
    )
    return mask


def _glow(size: int, cx: float, cy: float, radius: float, color: tuple[int, int, int], alpha: int) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x, y, r = _u(size, cx), _u(size, cy), max(2, _u(size, radius))
    draw.ellipse([x - r, y - r, x + r, y + r], fill=(*color, alpha))
    blur = max(2, int(size * 0.075))
    return layer.filter(ImageFilter.GaussianBlur(radius=blur))


def _crescent_mask(size: int) -> Image.Image:
    """开口朝右的新月，像 C，也像一圈账号围着一颗亮的。"""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    ox, oy, orad = _u(size, 448), _u(size, 520), _u(size, 268)
    draw.ellipse([ox - orad, oy - orad, ox + orad, oy + orad], fill=255)
    hx, hy, hrad = _u(size, 548), _u(size, 500), _u(size, 222)
    draw.ellipse([hx - hrad, hy - hrad, hx + hrad, hy + hrad], fill=0)
    return mask


def _orb(draw: ImageDraw.ImageDraw, size: int, cx: float, cy: float, r: float, fill: tuple[int, ...], highlight: bool) -> None:
    x, y, rad = _u(size, cx), _u(size, cy), max(1, _u(size, r))
    draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=fill)
    if highlight and rad >= 4:
        hx = x - max(1, rad // 3)
        hy = y - max(1, rad // 3)
        hr = max(1, rad // 4)
        draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255, 200))


def render_master(size: int = 1024) -> Image.Image:
    inset = _u(size, 36)
    radius = max(3, _u(size, 228))
    field = _vertical_fill(size, NIGHT_TOP, NIGHT_BOT)
    clip = _rounded_mask(size, inset, radius)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(field, mask=clip)

    # 两层光晕：大的暮粉氛围 + 月牙开口处的暖光
    bloom = _glow(size, 520, 500, 340, BLOOM[:3], 95)
    warm = _glow(size, 700, 500, 160, (255, 220, 200), 70)
    tile = Image.alpha_composite(tile, bloom)
    tile = Image.alpha_composite(tile, warm)
    tile.putalpha(clip)

    moon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    moon.paste(Image.new("RGBA", (size, size), CRESCENT), mask=_crescent_mask(size))
    # 新月外沿再铺一层很淡的光，不像剪纸
    moon_glow = moon.filter(ImageFilter.GaussianBlur(radius=max(1, size // 90)))
    tile = Image.alpha_composite(tile, moon_glow)
    tile = Image.alpha_composite(tile, moon)
    tile.putalpha(clip)

    draw = ImageDraw.Draw(tile)
    # 开口里那颗是「当前号」；旁边两颗暗一点，是号池
    _orb(draw, size, 708, 512, 78, ORB, highlight=True)
    if size >= 48:
        _orb(draw, size, 300, 368, 22, SATELLITE, highlight=False)
        _orb(draw, size, 268, 620, 14, SAT_DIM, highlight=False)
        _orb(draw, size, 390, 740, 10, SAT_DIM, highlight=False)
    return tile


def render_icon(size: int) -> Image.Image:
    if size >= 512:
        return render_master(size)
    src = render_master(max(1024, size * 8))
    out = src.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 24:
        out = out.filter(ImageFilter.UnsharpMask(radius=0.55, percent=120, threshold=2))
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    images = {size: render_icon(size) for size in SIZES}
    images[512].save(OUT_DIR / "icon.png", format="PNG")
    images[128].save(WEB_DIR / "icon.png", format="PNG")
    save_ico(OUT_DIR / "icon.ico", [images[s] for s in ICO_SIZES])
    print("wrote", OUT_DIR / "icon.ico")
    print("wrote", OUT_DIR / "icon.png")
    print("wrote", WEB_DIR / "icon.png")


if __name__ == "__main__":
    main()
