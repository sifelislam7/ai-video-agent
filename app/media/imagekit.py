"""Offline image generation + TikTok-style overlays, built on Pillow.

Two jobs:
1. ``generate_background`` — a decent looking abstract visual derived
   deterministically from a prompt. Used by the ``local`` image provider so the
   whole pipeline works with zero API keys.
2. ``compose_scene`` / ``compose_photo_card`` — burn hooks, captions, index
   badges and a watermark onto any image (local *or* AI generated).
"""

from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from . import textkit

# Palettes: (background A, background B, accent)
_PALETTES: dict[str, list[tuple[str, str, str]]] = {
    "cinematic": [
        ("#0b1026", "#1b2a5e", "#ffb86b"), ("#160f1f", "#4a1942", "#ff6b9d"),
        ("#06131f", "#0d4f5c", "#7ef2d1"), ("#1a0d05", "#6b2d0e", "#ffd166"),
    ],
    "anime": [
        ("#1a1030", "#6d3bd1", "#ffd6e0"), ("#07263d", "#1b9aaa", "#ffe066"),
        ("#2b0b3f", "#e05780", "#ffe9f3"),
    ],
    "photoreal": [
        ("#101418", "#2e3a45", "#e8e4d9"), ("#1d1a16", "#574c3c", "#f0c987"),
        ("#0f1a15", "#29513f", "#cfe8d5"),
    ],
    "minimal": [
        ("#f5f3ef", "#dcd6cc", "#1a1a1a"), ("#0f0f0f", "#242424", "#f2f2f2"),
        ("#eef2f7", "#c9d6e3", "#123a63"),
    ],
    "3d": [
        ("#14083a", "#3d1bd6", "#4df0ff"), ("#06182b", "#0f5f9e", "#ff8f3f"),
        ("#2a0536", "#8a1bb5", "#ffe14d"),
    ],
    "retro": [
        ("#2b1055", "#7597de", "#ff2e97"), ("#1f1206", "#8c5a2b", "#f7d08a"),
        ("#06231f", "#1f7a63", "#f2e14c"),
    ],
}

_WATERMARK_DEFAULT = "@ai.video.agent"


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _seed_from(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def _linear_gradient(size: tuple[int, int], top: tuple[int, int, int],
                     bottom: tuple[int, int, int], angle: float = 90.0) -> Image.Image:
    w, h = 64, 112
    grad = Image.new("RGB", (w, h))
    px = grad.load()
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    norm = abs(dx) * w + abs(dy) * h
    for y in range(h):
        for x in range(w):
            t = ((x * dx + y * dy) + (w if dx < 0 else 0) + (h if dy < 0 else 0)) / norm
            t = min(max(t, 0.0), 1.0)
            px[x, y] = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            )
    return grad.resize(size, Image.Resampling.BICUBIC)


def _blobs(size: tuple[int, int], rng: random.Random, accent: tuple[int, int, int],
           count: int = 4) -> Image.Image:
    w, h = size
    small = Image.new("RGB", (w // 8, h // 8), (0, 0, 0))
    draw = ImageDraw.Draw(small)
    sw, sh = small.size
    for _ in range(count):
        radius = rng.randint(int(sw * 0.25), int(sw * 0.75))
        cx = rng.randint(-radius // 2, sw + radius // 2)
        cy = rng.randint(-radius // 2, sh + radius // 2)
        tint = tuple(
            min(255, int(c * rng.uniform(0.55, 1.15))) for c in accent
        )
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=tint)
    small = small.filter(ImageFilter.GaussianBlur(radius=sw // 10))
    return small.resize(size, Image.Resampling.BICUBIC)


def _vignette(size: tuple[int, int], strength: float = 0.55) -> Image.Image:
    """Mask that keeps the centre bright and darkens the corners."""
    # radial_gradient is black in the middle and white at the edges — invert it.
    mask = Image.radial_gradient("L").resize(size, Image.Resampling.BICUBIC)
    return mask.point(lambda v: int(255 - v * strength))


def generate_background(
    prompt: str,
    size: tuple[int, int] = (1080, 1920),
    style: str = "cinematic",
    *,
    grain: bool = True,
) -> Image.Image:
    """Deterministic abstract artwork for a prompt (no network, no model)."""
    rng = random.Random(_seed_from(f"{style}:{prompt}"))
    palette = _PALETTES.get(style, _PALETTES["cinematic"])
    top_hex, bottom_hex, accent_hex = palette[rng.randrange(len(palette))]
    top, bottom, accent = _hex(top_hex), _hex(bottom_hex), _hex(accent_hex)

    base = _linear_gradient(size, top, bottom, angle=rng.choice([60.0, 90.0, 120.0]))
    glow = _blobs(size, rng, accent, count=rng.randint(3, 5))
    img = Image.blend(base, ImageChops.screen(base, glow), 0.85)

    # Geometric accent: soft arcs / rays that read well behind text.
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = size
    mode = rng.choice(["rays", "rings", "waves", "none"])
    if mode == "rays":
        for i in range(rng.randint(6, 12)):
            x = rng.randint(-w, w * 2)
            draw.polygon(
                [(x, 0), (x + rng.randint(30, 120), 0), (x + rng.randint(-400, 400), h), (x, h)],
                fill=(*accent, rng.randint(8, 26)),
            )
    elif mode == "rings":
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        for i in range(rng.randint(4, 8)):
            r = int(w * 0.18 * (i + 1))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         outline=(*accent, rng.randint(14, 40)), width=rng.randint(2, 8))
    elif mode == "waves":
        for i in range(rng.randint(4, 9)):
            y0 = rng.randint(0, h)
            pts = [(x, y0 + int(math.sin(x / rng.uniform(120, 320)) * rng.randint(20, 90)))
                   for x in range(0, w + 1, 20)]
            draw.line(pts, fill=(*accent, rng.randint(18, 48)), width=rng.randint(2, 7))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    img = Image.composite(img, Image.new("RGB", size, (0, 0, 0)), _vignette(size, 0.5))
    if grain:
        noise = Image.effect_noise(size, 14).convert("RGB")
        img = Image.blend(img, noise, 0.04)
    img = ImageEnhance.Brightness(img).enhance(1.12)
    return ImageEnhance.Contrast(img).enhance(1.06)


def fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Center-crop any image to the target aspect ratio (9:16 by default)."""
    target_w, target_h = size
    src_ratio = image.width / image.height
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        new_w = int(image.height * dst_ratio)
        box = ((image.width - new_w) // 2, 0, (image.width + new_w) // 2, image.height)
    else:
        new_h = int(image.width / dst_ratio)
        box = (0, (image.height - new_h) // 2, image.width, (image.height + new_h) // 2)
    return image.crop(box).resize(size, Image.Resampling.LANCZOS)


def _scrim(size: tuple[int, int], top_alpha: int = 0, bottom_alpha: int = 175) -> Image.Image:
    """Vertical dark gradient so captions stay readable over any artwork."""
    w, h = size
    grad = Image.new("L", (1, h))
    px = grad.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        eased = t ** 2.2
        px[0, y] = int(top_alpha + (bottom_alpha - top_alpha) * eased)
    alpha = grad.resize(size, Image.Resampling.BILINEAR)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.putalpha(alpha)
    return layer


def compose_scene(
    base: Image.Image,
    *,
    size: tuple[int, int] = (1080, 1920),
    headline: str = "",
    caption: str = "",
    index: int = 0,
    total: int = 0,
    watermark: str = _WATERMARK_DEFAULT,
    accent: tuple[int, int, int] = (255, 211, 105),
) -> Image.Image:
    """Burn the hook (top) and the caption (bottom) onto a scene frame."""
    w, h = size
    img = fit_cover(base.convert("RGB"), size)
    img = Image.alpha_composite(img.convert("RGBA"), _scrim(size)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    margin = int(w * 0.085)
    inner_w = w - margin * 2

    if headline:
        block = textkit.layout(headline, inner_w, int(h * 0.22), start_size=int(w * 0.075),
                               min_size=int(w * 0.04))
        pad = int(w * 0.03)
        band_h = block.height + pad * 2
        band = Image.new("RGBA", (w, band_h), (0, 0, 0, 0))
        ImageDraw.Draw(band).rounded_rectangle(
            [margin - pad // 2, 0, w - margin + pad // 2, band_h],
            radius=int(w * 0.035), fill=(0, 0, 0, 120),
        )
        img.alpha_composite(band, (0, int(h * 0.085)))
        draw = ImageDraw.Draw(img)
        textkit.draw_block(draw, block, w // 2, int(h * 0.085) + pad,
                           fill=(255, 255, 255), stroke_fill=(0, 0, 0), stroke_width=0)

    if caption:
        block = textkit.layout(caption, inner_w, int(h * 0.3), start_size=int(w * 0.062),
                               min_size=int(w * 0.034))
        top_y = int(h * 0.80) - block.height
        textkit.draw_block(draw, block, w // 2, top_y, fill=(255, 255, 255),
                           stroke_fill=(0, 0, 0), stroke_width=max(2, int(w * 0.004)))

    if total > 1:
        bar_w = int(inner_w / total) - 8
        y = int(h * 0.055)
        for i in range(total):
            x0 = margin + i * (bar_w + 8)
            color = accent if i <= index else (255, 255, 255, 70)
            draw.rounded_rectangle([x0, y, x0 + bar_w, y + 8], radius=4,
                                   fill=(*color[:3], 255 if i <= index else 70))

    if watermark:
        font = textkit.load_font(int(w * 0.028), textkit.is_rtl(watermark))
        draw.text((w // 2, int(h * 0.945)), textkit.shape(watermark), font=font,
                  fill=(255, 255, 255, 170), anchor="ma")
    return img.convert("RGB")


def compose_photo_card(
    base: Image.Image,
    *,
    size: tuple[int, int] = (1080, 1350),
    title: str = "",
    body: str = "",
    index: int = 0,
    total: int = 0,
    watermark: str = _WATERMARK_DEFAULT,
) -> Image.Image:
    """Carousel card: big title, supporting body, page counter."""
    w, h = size
    img = fit_cover(base.convert("RGB"), size)
    img = Image.alpha_composite(img.convert("RGBA"), _scrim(size, 40, 200)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    margin = int(w * 0.09)
    inner_w = w - margin * 2

    cursor = int(h * 0.52)
    if title:
        block = textkit.layout(title, inner_w, int(h * 0.3), start_size=int(w * 0.095),
                               min_size=int(w * 0.05))
        cursor = int(h * 0.80) - block.height - (int(h * 0.02) if body else 0)
        if body:
            body_block = textkit.layout(body, inner_w, int(h * 0.26),
                                        start_size=int(w * 0.05), min_size=int(w * 0.032))
            cursor -= body_block.height
        textkit.draw_block(draw, block, w // 2, cursor, fill=(255, 255, 255),
                           stroke_fill=(0, 0, 0), stroke_width=max(2, int(w * 0.003)))
        cursor += block.height + int(h * 0.02)
    if body:
        body_block = textkit.layout(body, inner_w, int(h * 0.26), start_size=int(w * 0.05),
                                    min_size=int(w * 0.032))
        textkit.draw_block(draw, body_block, w // 2, cursor, fill=(240, 240, 240))

    if total > 1:
        font = textkit.load_font(int(w * 0.034), False)
        label = f"{index + 1}/{total}"
        draw.text((w - margin, int(h * 0.055)), label, font=font,
                  fill=(255, 255, 255, 220), anchor="ra")
    if watermark:
        font = textkit.load_font(int(w * 0.028), textkit.is_rtl(watermark))
        draw.text((margin, int(h * 0.93)), textkit.shape(watermark), font=font,
                  fill=(255, 255, 255, 170), anchor="la")
    return img.convert("RGB")


def save(image: Image.Image, path: str | Path, quality: int = 92) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image.convert("RGB").save(path, quality=quality, optimize=True)
    else:
        image.save(path)
    return path
