"""Word-by-word animated captions (karaoke, pop, bounce, pill, glow, gradient ...).
MIRRORED in web/js/captionlayer.js — keep both in sync.

A caption is a text clip with text.caption = {template, style, words:[{w, t0, t1, emph?, conf?}]}; word times are
relative to the clip start. `style` is the full resolved template (copied from effects/presets.json caption_templates
when applied, then edited per clip), so a clip renders the same even if the template list changes later.

Layout (both sides): size px at a 1080-px short side, words measured without kerning, greedy wrap at style.width*W
(or one word per line for layout "stack"), lines centered on text.x, block centered on text.y. Lines are size*line_height
apart. Each word gets a state at time t (future / active / past) that sets its color, scale (about the word's center),
y offset, opacity, visible chars and an optional pill behind it. Draw order: line boxes + pills, then
glow, shadow, text (outline pass for all words, then fill pass).
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .text import anim_state, ease_out_back, ease_out_cubic, font, rgba

STYLE_DEFAULTS = {
    "font": "Poppins", "weight": 800, "size": 64, "case": "none", "line_height": 1.15, "width": 0.86,
    "color": "#FFFFFF", "outline": 5, "outline_color": "#000000", "shadow": 4,
    "glow": None, "gradient": None, "box": None, "line_colors": None, "stagger": 0,
    "mode": "karaoke", "layout": "flow",
    "active": {"color": "#FFD84D", "scale": 1.08, "box": None}, "past": {}, "future": {},
    "emph_color": None, "emph_scale": 1.0,
}
POP_T, BOUNCE_T, FADE_T = 0.18, 0.28, 0.12


def resolve(style: dict | None) -> dict:
    s = {**STYLE_DEFAULTS, **(style or {})}
    s["active"] = {**STYLE_DEFAULTS["active"], **(s.get("active") or {})}
    s["past"] = s.get("past") or {}
    s["future"] = s.get("future") or {}
    return s


def disp(w: str, s: dict) -> str:
    return w.upper() if s.get("case") == "upper" else w


def _clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def word_states(c: dict, t: float, s: dict):
    """Per-word look at time t: list of {color, scale, dy (×size), alpha, chars (None = all), pill, grad}."""
    words = c["text"]["caption"]["words"]
    rel = t - c["start"]
    n = len(words)
    out = []
    for i, w in enumerate(words):
        t0 = w["t0"]
        end = words[i + 1]["t0"] if i + 1 < n else math.inf
        state = "future" if rel < t0 else "active" if rel < end else "past"
        p = _clamp((rel - t0) / POP_T)
        o = {"color": s["color"], "scale": 1.0, "dy": 0.0, "alpha": 1.0, "chars": None, "pill": False, "grad": bool(s.get("gradient")),
             "state": state}
        if w.get("emph") and s.get("emph_color"):
            o["color"], o["grad"] = s["emph_color"], False
            o["scale"] *= s.get("emph_scale", 1.0)
        mode = s["mode"]
        act = s["active"]
        if mode in ("karaoke", "karaoke_box", "pop", "bounce") and state == "active" and act.get("color"):
            o["color"], o["grad"] = act["color"], False
        if mode in ("karaoke", "karaoke_box", "bounce"):
            if state == "future" and s["future"].get("color"):
                o["color"], o["grad"] = s["future"]["color"], False
            if state == "past" and s["past"].get("color"):
                o["color"], o["grad"] = s["past"]["color"], False
        if mode in ("karaoke", "karaoke_box") and state == "active":
            o["scale"] *= 1 + (act.get("scale", 1.0) - 1) * ease_out_cubic(p)
        if mode == "karaoke_box" and state == "active" and act.get("box"):
            o["pill"] = True
        if mode == "reveal":
            o["alpha"] = 0.0 if state == "future" else _clamp((rel - t0) / FADE_T)
        elif mode == "pop":
            if state == "future":
                o["alpha"] = 0.0
            else:
                o["scale"] *= 0.6 + 0.4 * ease_out_back(p)
                o["alpha"] = _clamp(p * 2)
        elif mode == "bounce" and state == "active":
            o["dy"] = -math.sin(math.pi * _clamp((rel - t0) / BOUNCE_T)) * 0.22
        elif mode == "typewriter":
            ln = len(w["w"])
            if state == "future":
                o["alpha"] = 0.0
            elif state == "active":
                span = max(0.05, w["t1"] - t0)
                o["chars"] = int(_clamp(math.ceil((rel - t0) / span * ln), 1, ln))
        if s.get("stagger"):
            o["dy"] += (s["stagger"] / 100.0) * (1 if i % 2 else -1)
        out.append(o)
    return out


def measure(s: dict, txt: str, px: float) -> float:
    """Text width at px, measured at 1000 px and scaled: FreeType rounds (hints) advances at small sizes, the browser
    doesn't — measuring big makes both sides agree."""
    return font(s["font"], int(s["weight"]), 1000).getlength(txt) * px / 1000.0


def metrics(px):
    """Synthetic ascent/descent (em fractions): browsers and FreeType disagree on a font's own metrics, which shifted
    the baseline by a few px between preview and export. Fixed fractions keep both identical."""
    return 0.80 * px, 0.25 * px


def reserve(s: dict) -> float:
    """Slot width factor so a scaled-up active / emphasis word never runs into its neighbours."""
    g = 1.0
    if s["mode"] in ("karaoke", "karaoke_box"):
        g = max(g, s["active"].get("scale", 1.0))
    if s.get("emph_color"):
        g = max(g, s.get("emph_scale", 1.0))
    return g


def state_key(c: dict, t: float) -> str:
    if not c["text"]["caption"].get("words"):
        return ""
    s = resolve(c["text"]["caption"].get("style"))
    return "|".join(f"{o['color']}{o['scale']:.3f}{o['dy']:.3f}{o['alpha']:.2f}{o['chars']}" for o in word_states(c, t, s))


def layout(c: dict, W: int, H: int, st: dict, s: dict):
    """Lines of words with base-size positions. Returns (font, size, lines, metrics)."""
    k = min(W, H) / 1080.0
    size = max(1, int(round(s["size"] * k * st["scale"])))
    f = font(s["font"], int(s["weight"]), size)
    asc, desc = metrics(size)
    space = measure(s, " ", size)
    maxw = s.get("width", 0.86) * W
    words = c["text"]["caption"]["words"]
    grow = reserve(s)
    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(words):
        nw = measure(s, disp(w["w"], s), size)
        ww = nw * (grow if (s["mode"] in ("karaoke", "karaoke_box") or w.get("emph")) else 1.0)
        if cur and (s["layout"] == "stack" or cur_w + space + ww > maxw):
            lines.append(cur)
            cur, cur_w = [], 0.0
        cur_w += (space if cur else 0.0) + ww
        cur.append((i, ww, nw))
    if cur:
        lines.append(cur)
    lh = size * s.get("line_height", 1.15)
    tx = c["text"]
    ax, ay = tx["x"] * W, tx["y"] * H + st["dy"] * H
    top = ay - lh * len(lines) / 2
    out = []
    for li, ln in enumerate(lines):
        line_w = sum(ww for _, ww, _ in ln) + space * (len(ln) - 1)
        x = ax - line_w / 2
        base = top + li * lh + (lh - (asc + desc)) / 2 + asc
        items = []
        for i, ww, nw in ln:
            items.append({"i": i, "x": x, "w": ww, "nw": nw})
            x += ww + space
        out.append({"items": items, "x0": ax - line_w / 2, "w": line_w, "base": base, "top": top + li * lh})
    return f, size, out, (asc, desc, lh, k, top)


def caption_rect(c: dict, t: float, W: int, H: int):
    st = anim_state(c, t)
    s = resolve(c["text"]["caption"].get("style"))
    if not c["text"]["caption"]["words"]:
        return None
    f, size, lines, (asc, desc, lh, k, top) = layout(c, W, H, st, s)
    x0 = min(ln["x0"] for ln in lines)
    x1 = max(ln["x0"] + ln["w"] for ln in lines)
    pad = 0.2 * size
    return (x0 - pad, top - pad * 0.5, x1 + pad, top + lh * len(lines) + pad * 0.5)


def _gradient_rows(H, lines, asc, desc, lh, top, c1, c2):
    """(H, 3) row colors: each line gets c1→c2 from its glyph top (base-asc) to bottom (base+desc), clamped."""
    a, b = np.array(rgba(c1)[:3], np.float32), np.array(rgba(c2)[:3], np.float32)
    y = np.arange(H, dtype=np.float32) + 0.5
    li = np.clip(np.floor((y - top) / lh), 0, len(lines) - 1).astype(int)
    bases = np.array([ln["base"] for ln in lines], np.float32)[li]
    u = np.clip((y - (bases - asc)) / max(1.0, asc + desc), 0, 1)[:, None]
    return a * (1 - u) + b * u


def render_caption(c: dict, t: float, W: int, H: int, opacity: float = 1.0):
    """Full-frame premultiplied RGBA uint8, or None when invisible."""
    cap = c["text"]["caption"]
    if not cap.get("words"):
        return None
    st = anim_state(c, t)
    alpha = st["alpha"] * opacity
    if alpha <= 0.001:
        return None
    s = resolve(cap.get("style"))
    f, size, lines, (asc, desc, lh, k, top) = layout(c, W, H, st, s)
    words = cap["words"]
    looks = word_states(c, t, s)
    if all(o["alpha"] <= 0.001 for o in looks):
        return None
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(img)
    outline = int(round((s.get("outline") or 0) * k))
    stroke = rgba(s.get("outline_color") or "#000000")

    # placed words: (text, x, baseline, font, look, line index)
    placed = []
    for li, ln in enumerate(lines):
        if s.get("box"):
            bx = s["box"]
            h = size * 1.3
            vc = ln["base"] - (asc - desc) / 2
            bd.rounded_rectangle((ln["x0"] - 0.3 * size, vc - h / 2, ln["x0"] + ln["w"] + 0.3 * size, vc + h / 2),
                                 radius=(bx.get("radius", 0.22)) * size, fill=rgba(bx.get("color", "#000000B3")))
        for it in ln["items"]:
            o = looks[it["i"]]
            if o["alpha"] <= 0.001:
                continue
            txt = disp(words[it["i"]]["w"], s)
            if s.get("line_colors") and o["color"] == s["color"] and not (o["state"] == "active" and s["mode"] != "none"):
                o["color"] = s["line_colors"][li % len(s["line_colors"])]
                o["grad"] = False
            vc = ln["base"] - (asc - desc) / 2 + o["dy"] * size
            if o["chars"] is not None:                       # typewriter: left-aligned in the word's slot, base size
                txt = txt[: o["chars"]]
                placed.append((txt, it["x"] + (it["w"] - it["nw"]) / 2, ln["base"] + o["dy"] * size, f, o, li))
                continue
            fs = f if abs(o["scale"] - 1) < 1e-4 else font(s["font"], int(s["weight"]), max(1, int(round(size * o["scale"]))))
            cx = it["x"] + it["w"] / 2
            if fs is f:
                ws, base = it["nw"], ln["base"] + o["dy"] * size
            else:
                a2, d2 = metrics(fs.size)
                ws, base = measure(s, txt, fs.size), vc + (a2 - d2) / 2
            x = cx - ws / 2
            if o["pill"]:
                ph = size * o["scale"] * 1.18
                pw = ws + 0.36 * size
                bd.rounded_rectangle((cx - pw / 2, vc - ph / 2, cx + pw / 2, vc + ph / 2), radius=min(ph / 2, 0.3 * size),
                                     fill=rgba(s["active"]["box"]))
            placed.append((txt, x, base, fs, o, li))

    txt_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad_mask = Image.new("L", (W, H), 0) if s.get("gradient") else None
    td = ImageDraw.Draw(txt_layer)
    gd = ImageDraw.Draw(grad_mask) if grad_mask is not None else None
    solid = [p for p in placed if p[4]["alpha"] >= 0.999]
    faded = [p for p in placed if p[4]["alpha"] < 0.999]
    if outline:
        for txt, x, base, fs, o, li in solid:
            td.text((x, base), txt, font=fs, fill=stroke, anchor="ls", stroke_width=outline, stroke_fill=stroke)
    for txt, x, base, fs, o, li in solid:
        if o["grad"] and gd is not None:
            gd.text((x, base), txt, font=fs, fill=255, anchor="ls")
        else:
            td.text((x, base), txt, font=fs, fill=rgba(o["color"]), anchor="ls")
    if grad_mask is not None and solid:
        rows = _gradient_rows(H, lines, asc, desc, lh, top, *s["gradient"])
        g = np.empty((H, W, 4), np.uint8)
        g[..., :3] = rows[:, None, :].astype(np.uint8)
        g[..., 3] = np.asarray(grad_mask)
        txt_layer.alpha_composite(Image.fromarray(g, "RGBA"))
    for txt, x, base, fs, o, li in faded:                    # fading words: own layer, then scaled alpha
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        if outline:
            ld.text((x, base), txt, font=fs, fill=stroke, anchor="ls", stroke_width=outline, stroke_fill=stroke)
        col = rgba(s["gradient"][0]) if o["grad"] else rgba(o["color"])
        ld.text((x, base), txt, font=fs, fill=col, anchor="ls")
        arr = np.asarray(lay).copy()
        arr[..., 3] = (arr[..., 3].astype(np.float32) * o["alpha"]).astype(np.uint8)
        txt_layer.alpha_composite(Image.fromarray(arr, "RGBA"))

    mask = txt_layer.split()[3]
    if s.get("glow"):
        gl = s["glow"]
        blur = mask.filter(ImageFilter.GaussianBlur(gl.get("r", 16) * k * 0.5))
        col = rgba(gl.get("color", "#00E5FF"))
        layer = Image.new("RGBA", (W, H), col[:3] + (0,))
        layer.putalpha(blur.point(lambda v: int(v * col[3] / 255)))
        for _ in range(int(gl.get("strength", 1))):
            img.alpha_composite(layer)
    if (s.get("shadow") or 0) > 0:
        sh = mask.filter(ImageFilter.GaussianBlur(s["shadow"] * k * 0.5))
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow.putalpha(sh.point(lambda v: int(v * 0.6)))
        img.alpha_composite(shadow, (0, int(round(s["shadow"] * k * 0.5))))
    img.alpha_composite(txt_layer)
    a = np.asarray(img).astype(np.float32)
    a[..., 3] *= alpha
    a[..., :3] *= a[..., 3:4] / 255.0
    return a.astype(np.uint8)
