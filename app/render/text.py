"""Text layers with Pillow. Layout MIRRORED in web/js/textlayer.js — keep both in sync.

Rules: size is px at a 1080-px short side (scaled by min(W,H)/1080). Each line is drawn letter by letter at
prefix-measured positions (+ letter spacing), so typewriter reveals never shift the layout. Lines are
size*line_height apart; the block is centered on (x, y) vertically and aligned on x per `align`.
No kerning (Pillow here has no raqm; the browser turns kerning off to match).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..paths import EFFECTS, ROOT


@lru_cache(maxsize=None)
def _font_table():
    pres = json.loads((EFFECTS / "presets.json").read_text(encoding="utf-8"))
    return {(f["family"], int(f["weight"])): ROOT / f["file"] for f in pres["fonts"]}


@lru_cache(maxsize=256)
def font(family: str, weight: int, px: int) -> ImageFont.FreeTypeFont:
    table = _font_table()
    cands = [k for k in table if k[0] == family] or list(table)
    best = min(cands, key=lambda k: abs(k[1] - weight))
    return ImageFont.truetype(str(table[best]), max(1, px), layout_engine=ImageFont.Layout.BASIC)


def rgba(hexstr: str):
    h = hexstr.lstrip("#")
    if len(h) == 6:
        h += "FF"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))


def ease_out_cubic(x):
    return 1 - (1 - x) ** 3


def ease_out_back(x):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def anim_state(c: dict, t: float) -> dict:
    """alpha / scale / dy (fraction of H) / visible char count for a text clip at timeline time t."""
    tx = c["text"]
    an = tx["anim"]
    rel = t - c["start"]
    dur = c["dur"]
    content = tx["content"]
    n_all = len(content)
    st = {"alpha": 1.0, "scale": 1.0, "dy": 0.0, "chars": n_all}
    ind, outd = max(an.get("in_dur", 0), 1e-6), max(an.get("out_dur", 0), 1e-6)
    pi = min(1.0, max(0.0, rel / ind))
    po = min(1.0, max(0.0, (dur - rel) / outd))
    kind = an.get("in", "none")
    if kind == "fade":
        st["alpha"] *= pi
    elif kind == "pop":
        st["scale"] = 0.85 + 0.15 * ease_out_back(pi)
        st["alpha"] *= min(1.0, pi * 2)
    elif kind == "slide_up":
        st["dy"] = (1 - ease_out_cubic(pi)) * 0.04
        st["alpha"] *= pi
    elif kind == "typewriter":
        times = tx.get("times")
        if times:
            st["chars"] = sum(1 for x in times if x <= rel + 1e-6)
        else:
            st["chars"] = int(math.floor(pi * n_all + 1e-6))
    if an.get("out", "none") != "none" and an.get("out_dur", 0) > 0:
        st["alpha"] *= po
    return st


def layout(c: dict, W: int, H: int, st: dict):
    """Returns (font, lines[(text, x0, baseline, [char x offsets])], box rect or None, k)."""
    tx = c["text"]
    s = tx["style"]
    k = min(W, H) / 1080.0
    size = max(1, int(round(s["size"] * k * st["scale"])))
    f = font(s["font"], int(s["weight"]), size)
    asc, desc = f.getmetrics()
    sp = s.get("spacing", 0) * k * st["scale"]
    lh = size * s.get("line_height", 1.2)
    lines = tx["content"].split("\n")
    widths, offs = [], []
    for ln in lines:
        o = [f.getlength(ln[:i]) + i * sp for i in range(len(ln) + 1)]
        offs.append(o)
        widths.append((o[-1] - sp) if ln else 0.0)
    block_w = max(widths) if widths else 0
    block_h = lh * len(lines)
    ax, ay = tx["x"] * W, tx["y"] * H + st["dy"] * H
    top = ay - block_h / 2
    out = []
    for i, ln in enumerate(lines):
        if s["align"] == "left":
            x0 = ax
        elif s["align"] == "right":
            x0 = ax - widths[i]
        else:
            x0 = ax - widths[i] / 2
        base = top + i * lh + (lh - (asc + desc)) / 2 + asc
        out.append((ln, x0, base, offs[i]))
    if s["align"] == "left":
        bx0 = ax
    elif s["align"] == "right":
        bx0 = ax - block_w
    else:
        bx0 = ax - block_w / 2
    pad_x, pad_y = 0.35 * size, 0.2 * size
    box = (bx0 - pad_x, top - pad_y, bx0 + block_w + pad_x, top + block_h + pad_y) if s.get("box") else None
    return f, out, box, k, size


def render_text(c: dict, t: float, W: int, H: int, opacity: float = 1.0):
    """Full-frame premultiplied RGBA uint8 array, or None when invisible."""
    if c["text"].get("caption"):
        from .caption import render_caption
        return render_caption(c, t, W, H, opacity)
    st = anim_state(c, t)
    alpha = st["alpha"] * opacity
    if alpha <= 0.001 or st["chars"] <= 0 and c["text"]["anim"].get("in") == "typewriter":
        return None
    s = c["text"]["style"]
    f, lines, box, k, size = layout(c, W, H, st)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if box:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, radius=0.15 * size, fill=rgba(s.get("box_color", "#000000B3")))
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(txt)
    outline = int(round(s.get("outline", 0) * k))
    fill = rgba(s.get("color", "#FFFFFF"))
    stroke = rgba(s.get("outline_color", "#000000"))
    budget = st["chars"]
    for ln, x0, base, offs in lines:
        for i, ch in enumerate(ln):
            if budget <= 0:
                break
            budget -= 1
            if ch == " ":
                continue
            d.text((x0 + offs[i], base), ch, font=f, fill=fill, anchor="ls",
                   stroke_width=outline, stroke_fill=stroke if outline else None)
        budget -= 1          # the newline counts as a character for typewriter timing
    if s.get("shadow", 0) > 0:
        sh = txt.split()[3].filter(ImageFilter.GaussianBlur(s["shadow"] * k * 0.5))
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow.putalpha(sh.point(lambda v: int(v * 0.6)))
        off = int(round(s["shadow"] * k * 0.5))
        img.alpha_composite(shadow, (0, off))
    img.alpha_composite(txt)
    a = np.asarray(img).astype(np.float32)
    a[..., 3] *= alpha
    a[..., :3] *= a[..., 3:4] / 255.0           # premultiply
    return a.astype(np.uint8)
