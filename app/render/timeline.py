"""What is visible at time t. MIRRORED in web/js/evaluate.js — keep both in sync.

Transition windows (Premiere-style, centered on the cut):
  a + b      : [cut - d/2, cut + d/2]   (frames past a clip's edge are held)
  only b     : [b.start, b.start + d]   (from transparent)
  only a     : [a.end - d, a.end]       (to transparent)
"""
from __future__ import annotations


def has_dur(c):
    """Clips whose length is `dur` (text, stills, freeze frames, narration) rather than (out-in)/speed."""
    return c["type"] in ("text", "tts") or c.get("still") or c.get("hold") is not None


def clip_dur(c):
    if has_dur(c):
        return c["dur"]
    return (c["out"] - c["in"]) / c.get("speed", 1.0)


def clip_end(c):
    return c["start"] + clip_dur(c)


def src_time(c, t, src_fps=30.0):
    """Source media time for timeline time t (clamped into the clip's media, i.e. frame hold past edges)."""
    if c["type"] != "media" or c.get("still"):
        return 0.0
    if c.get("hold") is not None:                       # freeze frame
        return float(c["hold"])
    rel = (t - c["start"]) * c.get("speed", 1.0)
    st = c["out"] - rel if c.get("reverse") else c["in"] + rel
    return max(c["in"], min(st, c["out"] - 0.5 / src_fps))


def window(x, clips_by_id):
    a, b = clips_by_id.get(x.get("a")), clips_by_id.get(x.get("b"))
    d = x["dur"]
    if a and b:
        cut = b["start"]
        return cut - d / 2, cut + d / 2, a, b
    if b:
        return b["start"], b["start"] + d, None, b
    return clip_end(a) - d, clip_end(a), a, None


def fade_mult(c, t):
    m = 1.0
    if c.get("fade_in", 0) > 0:
        m *= min(1.0, max(0.0, (t - c["start"]) / c["fade_in"]))
    if c.get("fade_out", 0) > 0:
        m *= min(1.0, max(0.0, (clip_end(c) - t) / c["fade_out"]))
    return m


# ---------------------------------------------------------------- keyframes (MIRROR of evaluate.js prop/…At)
ANIMATABLE = ["motion.x", "motion.y", "motion.scale", "motion.rot", "motion.opacity",
              "crop.l", "crop.t", "crop.r", "crop.b", "text.x", "text.y", "volume_db"]


def get_path(o, path):
    for k in path.split("."):
        o = o.get(k) if isinstance(o, dict) else None
    return o


def prop(c, path, t):
    ks = (c.get("keys") or {}).get(path)
    if not ks:
        return get_path(c, path)
    rel = t - c["start"]
    if rel <= ks[0]["t"]:
        return ks[0]["v"]
    if rel >= ks[-1]["t"]:
        return ks[-1]["v"]
    i = 0
    while i < len(ks) - 2 and ks[i + 1]["t"] <= rel:
        i += 1
    a, b = ks[i], ks[i + 1]
    u = (rel - a["t"]) / max(b["t"] - a["t"], 1e-9)
    e = a.get("e", "linear")
    if e == "hold":
        return a["v"]
    if e == "ease":
        u = u * u * (3 - 2 * u)
    elif e == "ease_in":
        u = u * u
    elif e == "ease_out":
        u = 1 - (1 - u) * (1 - u)
    return a["v"] + (b["v"] - a["v"]) * u


_MOTION_DEF = {"x": 0.0, "y": 0.0, "scale": 1.0, "rot": 0.0, "opacity": 1.0}


def motion_at(c, t):
    m = dict(c.get("motion") or {})
    for k, d in _MOTION_DEF.items():
        v = prop(c, f"motion.{k}", t)
        m[k] = d if v is None else v
    return m


def crop_at(c, t):
    r = dict(c.get("crop") or {})
    for k in ("l", "t", "r", "b"):
        v = prop(c, f"crop.{k}", t)
        r[k] = 0.0 if v is None else v
    return r


def text_pos_at(c, t):
    return prop(c, "text.x", t), prop(c, "text.y", t)


def brand_clip(p: dict) -> dict | None:
    """The project-wide watermark/logo as a still 'clip' drawn over every frame (None when off). Mirror of brandClip."""
    br = (p.get("settings") or {}).get("brand") or {}
    if not br.get("enabled") or not br.get("asset"):
        return None
    return {"id": "_brand", "type": "media", "asset": br["asset"], "still": True, "start": 0.0, "dur": 1e9, "in": 0.0,
            "out": 0.0, "speed": 1.0, "crop": {}, "color": {}, "filters": [], "keys": {}, "fade_in": 0.0, "fade_out": 0.0,
            "motion": {"fit": "none"}}


def brand_motion(W, H, sw, sh, br: dict) -> dict:
    """Corner placement: logo width = size × frame width, margin = margin × the short side. Mirror of brandMotion."""
    s = br["size"] * W / max(sw, 1)
    dw, dh = sw * s, sh * s
    m = br["margin"] * min(W, H)
    pos = br.get("position", "tr")
    x = 0.0 if pos == "center" else (-(W / 2 - m - dw / 2) if pos in ("tl", "bl") else (W / 2 - m - dw / 2))
    y = 0.0 if pos == "center" else (-(H / 2 - m - dh / 2) if pos in ("tl", "tr") else (H / 2 - m - dh / 2))
    return {"x": x, "y": y, "scale": s, "rot": 0.0, "opacity": float(br.get("opacity", 1.0)), "fit": "none"}


def visual_items(p: dict, t: float) -> list[dict]:
    """Bottom-to-top draw list: {'kind':'clip', clip} or {'kind':'transition', x, a, b, progress}."""
    tracks = [tr for tr in p["tracks"] if tr["kind"] in ("video", "text") and not tr.get("hidden")]
    # draw order: V1 (bottom) … Vn, then T1 … Tn — p["tracks"] lists top-to-bottom
    vids = [tr for tr in reversed(tracks) if tr["kind"] == "video"]
    txts = [tr for tr in reversed(tracks) if tr["kind"] == "text"]
    by_id = {c["id"]: c for c in p["clips"]}
    items = []
    for tr in vids + txts:
        clips = [c for c in p["clips"] if c["track"] == tr["id"] and c.get("enabled", True)]
        ids = {c["id"] for c in clips}
        covered = set()
        hit = None
        for x in p["transitions"]:
            if not ({x.get("a"), x.get("b")} & ids):
                continue
            w0, w1, a, b = window(x, by_id)
            if w0 <= t < w1:
                hit = {"kind": "transition", "x": x, "a": a, "b": b, "progress": (t - w0) / max(x["dur"], 1e-6)}
                covered = {c["id"] for c in (a, b) if c}
                break
        if hit:
            items.append(hit)
            continue
        for c in clips:
            if c["id"] in covered:
                continue
            if c["start"] <= t < clip_end(c):
                items.append({"kind": "clip", "clip": c})
                break
    return items
