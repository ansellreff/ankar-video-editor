"""Real thumbnails for the Effects / Color / Transitions tabs: the actual shaders run on a frame of the user's footage.
Cached in cache/previews/ (key = source poster + item definition), served via /files/cache/previews/…
filters / luts / looks → one 320×128 JPG each; transitions → a 6-frame sprite strip (hover animates it)."""
from __future__ import annotations

import hashlib
import json

import numpy as np
from PIL import Image

from .paths import CACHE, ROOT, rel

OUT = CACHE / "previews"
TW, TH = 320, 128
FRAMES = 6


def _band(poster, w=TW, h=TH) -> np.ndarray:
    """Center band of a poster image, w×h (cover)."""
    im = Image.open(poster).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, int((im.height - h) * 0.42)
    return np.asarray(im.crop((x, y, x + w, y + h)))


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _passes(pres, color: dict, filters: list):
    fl = {f["id"]: f for f in pres["filters"]}
    cd = pres["color"]
    out = []
    col = {k: color.get(k, v["default"]) for k, v in cd["params"].items()}
    if any(abs(col[k] - cd["params"][k]["default"]) > 1e-6 for k in col):
        out.append((cd["shader"], col, None))
    for f in filters:
        fd = fl.get(f.get("type"))
        if not fd or f.get("enabled") is False:
            continue
        if fd.get("lut") and not (f.get("file") and (ROOT / f["file"]).exists()):
            continue
        out.append((fd["shader"], {k: f.get(k, v["default"]) for k, v in fd["params"].items()}, f.get("file") if fd.get("lut") else None))
    return out


def _grade(gl, img: np.ndarray, passes, t=1.0) -> np.ndarray:
    h, w = img.shape[:2]
    tex = gl.upload(np.dstack([img, np.full((h, w), 255, np.uint8)]), slot="pv_src")
    slot = None
    for i, (shader, vals, lut) in enumerate(passes):
        slot = f"pv{i % 2}"
        tex = gl.filter_pass(tex, w, h, shader, vals, t, slot, lut=lut)
    if slot is None:
        return img
    fbo, _ = gl.fbo(w, h, slot)
    return gl.read_rgb(fbo, w, h)


def render(kind: str, posters: list, pres: dict, items: list) -> dict:
    """kind: filters | luts | looks | transitions. items: definitions (see server). Returns {id: url}."""
    from .render.gl import GL
    OUT.mkdir(parents=True, exist_ok=True)
    src_key = [(str(p), p.stat().st_mtime) for p in posters]
    todo, urls = [], {}
    for it in items:
        k = _key(kind, src_key, it)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(it["id"]))[-40:]
        f = OUT / f"{kind}_{safe}_{k}.jpg"
        urls[it["id"]] = "/files/" + rel(f)
        if not f.exists():
            todo.append((it, f))
    if not todo:
        return urls
    gl = GL()
    a = _band(posters[0])
    b = _band(posters[1] if len(posters) > 1 else posters[0])
    if len(posters) < 2:                                      # one clip only: make B visibly different
        b = np.ascontiguousarray(b[:, ::-1])
    for it, f in todo:
        try:
            if kind == "transitions":
                fw, fh = TW // 2, TH // 2
                aa, bb = (np.asarray(Image.fromarray(x).resize((fw, fh), Image.LANCZOS)) for x in (a, b))
                ta = gl.upload(np.dstack([aa, np.full((fh, fw), 255, np.uint8)]), slot="pv_a")
                tb = gl.upload(np.dstack([bb, np.full((fh, fw), 255, np.uint8)]), slot="pv_b")
                strip = []
                for n in range(FRAMES):
                    p = (n + 0.5) / FRAMES
                    gl.transition_pass(ta, tb, fw, fh, it["shader"], it.get("params", {}), p, p, slot="pv_tr")
                    fbo, _ = gl.fbo(fw, fh, "pv_tr")
                    strip.append(gl.read_rgb(fbo, fw, fh))
                Image.fromarray(np.hstack(strip)).save(f, quality=84)
            else:
                if kind == "luts":
                    passes = _passes(pres, {}, [{"type": "lut", "file": it["file"], "amount": 1.0}])
                elif kind == "looks":
                    passes = _passes(pres, it.get("color", {}), it.get("filters", []))
                else:
                    fd = it
                    passes = _passes(pres, {}, [{"type": fd["id"], **{k: v["default"] for k, v in fd["params"].items()}}])
                Image.fromarray(_grade(gl, a, passes)).save(f, quality=84)
        except Exception as e:  # noqa: BLE001 - one broken preview shouldn't stop the rest
            urls.pop(it["id"], None)
            print("preview failed", kind, it.get("id"), e)
    return urls
