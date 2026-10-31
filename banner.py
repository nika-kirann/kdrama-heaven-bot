"""Branded banner card (Pillow) for dramas without a poster: dark navy→purple gradient, starfield,
title, status/genre pills, meta line and a 'Browse & Download' CTA. Pure typography, no photos/faces."""
from __future__ import annotations

import io
import os
import random
import textwrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
TOP, BOTTOM = (10, 14, 40), (58, 20, 92)       # navy -> deep purple
ACCENT, SOFT, WHITE = (190, 150, 255), (170, 180, 215), (245, 245, 255)


def _font(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONTS, name), size)
    except OSError:
        return ImageFont.load_default(size)


def _bg(seed: int) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        px.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([W * 0.55, -H * 0.3, W * 1.3, H * 0.7], fill=(90, 60, 170))
    g.ellipse([-W * 0.2, H * 0.6, W * 0.4, H * 1.4], fill=(40, 30, 110))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(160)), 0.45)
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    for _ in range(140):
        x, y, r = rnd.randrange(W), rnd.randrange(H), rnd.choice([1, 1, 1, 2])
        c = rnd.randrange(150, 255)
        d.ellipse([x, y, x + r, y + r], fill=(c, c, 255))
    return img


def _pill(d, x, y, text, font, fill=None, outline=ACCENT, color=WHITE, pad=(18, 8)):
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    w, h = r - l + pad[0] * 2, b - t + pad[1] * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=fill, outline=outline, width=2)
    d.text((x + pad[0] - l, y + pad[1] - t), text, font=font, fill=color)
    return x + w


def render_banner(title: str, status: str = "Ongoing", genres=(), year=None, episodes: int = 0,
                  total=None, qualities=(), brand: str = "@kdrama_heaven", seed=None) -> bytes:
    img = _bg(seed if seed is not None else sum(map(ord, title)))
    d = ImageDraw.Draw(img)
    x0 = 90
    small, mid = _font("DejaVuSans-Bold.ttf", 24), _font("DejaVuSans.ttf", 28)
    d.text((x0, 80), f"K-DRAMA{'  ·  ' + str(year) if year else ''}".upper(), font=small, fill=ACCENT,
           spacing=4)
    # title: shrink to fit in at most 3 lines
    for size in (96, 84, 72, 62, 54, 46):
        f = _font("DejaVuSerif-Bold.ttf", size)
        lines = textwrap.wrap(title.upper(), width=max(8, int(1050 / (size * 0.62))))
        if len(lines) <= 3:
            break
    lines = lines[:3]
    y = 125
    for ln in lines:
        d.text((x0, y), ln, font=f, fill=WHITE)
        y += int(size * 1.08)
    y += 22
    done = status == "Completed"
    x = _pill(d, x0, y, "✓ COMPLETED" if done else "● ONGOING", small,
              fill=(40, 150, 100) if done else (200, 70, 120), outline=None)
    for g in list(genres)[:3]:
        x = _pill(d, x + 14, y, g.upper(), small)
    y += 70
    meta = [f"{episodes}{'/' + str(total) if total else ''} Episodes"] + (["  ·  ".join(qualities)] if qualities else [])
    d.text((x0, y), "   |   ".join(meta), font=mid, fill=SOFT)
    y = H - 150
    cta = _font("DejaVuSans-Bold.ttf", 30)
    _pill(d, x0, y, "▶  BROWSE & DOWNLOAD", cta, fill=(120, 80, 230), outline=(200, 180, 255), pad=(30, 16))
    d.line([(x0, H - 55), (W - 90, H - 55)], fill=(110, 90, 170), width=1)
    d.text((x0, H - 45), f"✦ {brand}", font=small, fill=SOFT)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
