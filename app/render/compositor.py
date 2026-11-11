"""Frame-accurate export from the ORIGINAL media: GPU layers + shared shaders + Pillow text + numpy audio."""
from __future__ import annotations

import json
import math
import re
import time
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image

from .. import media
from ..colors import rgb_to_yuv709, to_rgb, x264_options
from ..paths import ROOT
from . import audio as audio_mod
from .gl import GL, layer_quad, text_quad
from .text import render_text
from .timeline import brand_clip, brand_motion, clip_end, crop_at, fade_mult, motion_at, src_time, text_pos_at, visual_items

QUALITY = {"draft": ("veryfast", 26), "high": ("medium", 18), "max": ("slow", 15)}


class VideoReader:
    """Serves the frame showing at a requested source time. Forward requests decode sequentially; backward
    requests (reversed clips) decode a ~1 s window once and serve it from a small cache."""

    def __init__(self, path: str, meta: dict):
        self.c = av.open(path)
        self.s = self.c.streams.video[0]
        self.s.thread_type = "AUTO"
        self.start = meta.get("start", 0.0)
        self.rot = meta.get("rotation", 0)
        self.fps = meta.get("fps", 30.0) or 30.0
        self.gen = None
        self.cur = self.cur_t = self.nxt = None
        self.arr = None
        self.cache: OrderedDict[float, np.ndarray] = OrderedDict()     # frame time → rgb (for reverse playback)

    def _next(self):
        try:
            f = next(self.gen)
            return f, float(f.time) - self.start
        except StopIteration:
            return None, None

    def _seek(self, t):
        self.c.seek(int(max(0.0, t + self.start) / self.s.time_base), stream=self.s, backward=True)
        self.gen = self.c.decode(self.s)

    def frame_at(self, t: float) -> np.ndarray:
        eps = 0.25 / self.fps
        if self.cur is not None and t < self.cur_t - 1e-3:              # going backwards
            hit = [k for k in self.cache if k <= t + eps]
            if hit and max(hit) > t - 1.5 / self.fps:
                return self.cache[max(hit)]
            self._fill_window(t)
            hit = [k for k in self.cache if k <= t + eps]
            if hit:
                return self.cache[max(hit)]
        if self.cur is None or t > self.cur_t + 1.5:
            self._seek(t - 0.05)
            self.cur, self.cur_t = self._next()
            self.nxt = self._next()
            self.arr = None
        while self.nxt[0] is not None and self.nxt[1] <= t + eps:
            self.cur, self.cur_t = self.nxt
            self.nxt = self._next()
            self.arr = None
        if self.arr is None:
            if self.cur is None:
                return np.zeros((16, 16, 3), np.uint8)
            self.arr = media.upright(to_rgb(self.cur), self.rot)
        return self.arr

    def _fill_window(self, t, span=1.0):
        """Decode [t - span, t] into the cache (used when playing a clip in reverse)."""
        self._seek(t - span)
        self.cur = None
        for f in self.c.decode(self.s):
            ft = float(f.time) - self.start
            if ft > t + 0.5 / self.fps:
                break
            if ft >= t - span - 1 / self.fps:
                self.cache[ft] = media.upright(to_rgb(f), self.rot)
                while len(self.cache) > int(self.fps * 2.5):
                    self.cache.popitem(last=False)

    def close(self):
        self.c.close()


class FrameRenderer:
    """Renders any timeline time t to an RGB frame (export, snapshots, tests)."""

    def __init__(self, project: dict, assets: dict, W: int, H: int):
        self.p, self.W, self.H = project, W, H
        self.gl = GL()
        self.out_fbo, _ = self.gl.fbo(W, H, "out")
        self.assets = {}
        for aid, a in assets.items():
            if not a:
                continue
            meta = a.get("meta") or {}
            self.assets[aid] = {"abs": str(ROOT / a["path"]), "start": meta.get("start", 0.0), "has_audio": meta.get("has_audio"),
                                "kind": a.get("kind"), **meta}
        self.readers: dict[str, VideoReader] = {}
        self.stills: dict[str, np.ndarray] = {}
        self.text_cache: dict = {}
        pres = self.gl.presets
        self.tr_by_id = {t["id"]: t for t in pres["transitions"]}
        self.fl_by_id = {f["id"]: f for f in pres["filters"]}
        self.color_def = pres["color"]

    # -------------------------------------------------------------- sources
    def media_frame(self, c, t):
        a = self.assets.get(c["asset"])
        if a is None:
            return np.zeros((16, 9, 3), np.uint8)
        if a.get("kind") == "image" or c.get("still"):
            if c["asset"] not in self.stills:
                im = Image.open(a["abs"])
                if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                    x = np.asarray(im.convert("RGBA")).astype(np.float32)          # transparent PNG (logo, sticker):
                    x[..., :3] *= x[..., 3:4] / 255.0                              # premultiplied like every layer
                    self.stills[c["asset"]] = np.round(x).astype(np.uint8)
                else:
                    self.stills[c["asset"]] = np.asarray(im.convert("RGB"))
            return self.stills[c["asset"]]
        r = self.readers.get(c["id"])
        if r is None:
            r = self.readers[c["id"]] = VideoReader(a["abs"], a)
        sf = a.get("fps") or 30.0
        st = src_time(c, t, sf)
        if c.get("blend") and c.get("hold") is None and c.get("speed", 1.0) < 1.0:
            f = st * sf                                         # slow-motion frame blending between neighbours
            f0 = math.floor(f + 1e-6)
            w = f - f0
            a0 = r.frame_at(f0 / sf)
            if w < 0.02:
                return a0
            a0 = a0.astype(np.float32)
            a1 = r.frame_at(min((f0 + 1) / sf, c["out"] - 0.5 / sf)).astype(np.float32)
            return (a0 * (1 - w) + a1 * w).astype(np.uint8)
        return r.frame_at(st)

    # -------------------------------------------------------------- layers
    def draw_layer(self, c, t, target):
        gl, W, H = self.gl, self.W, self.H
        m = motion_at(c, t)
        op = float(m.get("opacity", 1.0)) * fade_mult(c, t)
        if c["type"] == "text":
            tx, ty = text_pos_at(c, t)
            cc = {**c, "text": {**c["text"], "x": tx, "y": ty}}
            animated = c["text"]["anim"].get("in") != "none" or c["text"]["anim"].get("out") != "none"
            key = (c["id"], round(tx, 5), round(ty, 5)) + ((round(t, 3),) if animated else ())
            if c["text"].get("caption"):                     # per-word looks change with time → part of the key
                from .caption import state_key
                key += (state_key(cc, t),)
            if key not in self.text_cache:
                if len(self.text_cache) > 64:
                    self.text_cache.clear()
                self.text_cache[key] = render_text(cc, t, W, H, opacity=1.0)   # animation alpha is baked in
            arr = self.text_cache[key]
            if arr is None:
                return False
            gl.draw(gl.upload(arr, slot="text"), target, quad=text_quad(W, H, (tx * W, ty * H), m), opacity=op)
            return True
        if c["type"] != "media":
            return False
        arr = self.media_frame(c, t)
        sh, sw = arr.shape[:2]
        tex = gl.upload(arr, slot="src")
        passes = []
        col = {k: c.get("color", {}).get(k, v["default"]) for k, v in self.color_def["params"].items()}
        if any(abs(col[k] - self.color_def["params"][k]["default"]) > 1e-6 for k in col):
            passes.append((self.color_def["shader"], col))
        for f in c.get("filters", []):
            if f.get("enabled", True) is False or f.get("type") not in self.fl_by_id:
                continue
            fd = self.fl_by_id[f["type"]]
            if fd.get("lut") and not (f.get("file") and (ROOT / f["file"]).exists()):
                continue                                         # LUT filter without a (present) .cube file
            passes.append((fd["shader"], {k: f.get(k, v["default"]) for k, v in fd["params"].items()}, f.get("file") if fd.get("lut") else None))
        for i, p in enumerate(passes):
            shader, vals, lut = p if len(p) == 3 else (*p, None)
            tex = gl.filter_pass(tex, sw, sh, shader, vals, t, slot=f"f{i % 2}", lut=lut)
        gl.draw(tex, target, quad=layer_quad(W, H, sw, sh, m, crop_at(c, t)), opacity=op)
        return True

    def frame(self, t: float) -> np.ndarray:
        gl, W, H = self.gl, self.W, self.H
        self.out_fbo.use()
        self.out_fbo.clear(0, 0, 0, 1)
        for it in visual_items(self.p, t):
            if it["kind"] == "clip":
                self.draw_layer(it["clip"], t, self.out_fbo)
                continue
            x, a, b = it["x"], it["a"], it["b"]
            fa, ta = gl.fbo(W, H, "la")
            fb, tb = gl.fbo(W, H, "lb")
            fa.use(); fa.clear(0, 0, 0, 0)
            fb.use(); fb.clear(0, 0, 0, 0)
            if a:
                self.draw_layer(a, t, fa)
            if b:
                self.draw_layer(b, t, fb)
            td = self.tr_by_id.get(x["type"]) or self.tr_by_id["cross_dissolve"]
            vals = {**td["params"], **{k: v for k, v in (x.get("params") or {}).items() if k in td["params"]}}
            gl.draw(gl.transition_pass(ta, tb, W, H, td["shader"], vals, it["progress"], t), self.out_fbo)
        bc = brand_clip(self.p)                                  # watermark / logo over everything
        if bc and bc["asset"] in self.assets:
            arr = self.media_frame(bc, t)
            bc["motion"] = brand_motion(W, H, arr.shape[1], arr.shape[0], self.p["settings"]["brand"])
            self.draw_layer(bc, t, self.out_fbo)
        return gl.read_rgb(self.out_fbo, W, H)

    def close(self):
        for r in self.readers.values():
            r.close()


def render(project: dict, assets: dict, out_path: Path, preset: str = "high", fmt: tuple | None = None,
           t_range: tuple | None = None, progress=None, cancel=None) -> dict:
    """assets: {asset_id: library entry}. Returns a report dict."""
    t_start = time.time()
    W, H = fmt or (project["format"]["w"], project["format"]["h"])
    fps = Fraction(project["format"]["fps"])
    total = max([clip_end(c) for c in project["clips"]] + [0.0])
    t0, t1 = t_range or (0.0, total)
    nframes = max(1, int(math.ceil((t1 - t0) * fps - 1e-6)))
    speed_preset, crf = QUALITY.get(preset, QUALITY["high"])
    fr = FrameRenderer(project, assets, W, H)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = av.open(str(out_path), "w", options={"movflags": "+faststart"})
    vs = out.add_stream("libx264", rate=fps, options=x264_options(crf=str(crf), preset=speed_preset))
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    as_ = out.add_stream("aac", rate=audio_mod.SR, layout="stereo")      # both streams before the header is written
    as_.bit_rate = 192000
    try:
        for i in range(nframes):
            if cancel and cancel():
                raise RuntimeError("cancelled")
            frame = rgb_to_yuv709(fr.frame(t0 + float(i / fps)))
            frame.pts = i
            for p in vs.encode(frame):
                out.mux(p)
            if progress and (i % 5 == 0 or i == nframes - 1):
                progress("video", (i + 1) / nframes)
        for p in vs.encode():
            out.mux(p)
        mixed, report = audio_mod.mix(project, fr.assets, t0, t0 + nframes / float(fps),
                                      progress=(lambda x: progress("audio", x)) if progress else None)
        CH = 1024
        for s in range(0, mixed.shape[1], CH):
            af = av.AudioFrame.from_ndarray(np.ascontiguousarray(mixed[:, s:s + CH]), format="fltp", layout="stereo")
            af.sample_rate, af.pts = audio_mod.SR, s
            for p in as_.encode(af):
                out.mux(p)
        for p in as_.encode():
            out.mux(p)
    finally:
        out.close()
        fr.close()
    return {"file": out_path.name, "frames": nframes, "w": W, "h": H, "seconds": round(time.time() - t_start, 1),
            "fps_render": round(nframes / max(time.time() - t_start, 1e-6), 1), "gpu": fr.gl.renderer, **report}


def next_version(folder: Path) -> int:
    """Numbering continues across exports/ and exports/draft/ (drafts are moved there when a final is made)."""
    files = list(folder.glob("v*.mp4")) + list((folder / "draft").glob("v*.mp4"))
    nums = [int(m.group(1)) for p in files if (m := re.match(r"v(\d+)", p.stem))]
    return max(nums + [0]) + 1


def file_drafts(folder: Path) -> list[str]:
    """User rule (2026-11-07): only the final versions stay in exports/; every draft vNN.mp4 (+ its .project.json)
    goes to exports/draft/. Returns the moved names."""
    d = folder / "draft"
    moved = []
    for p in sorted(folder.glob("v*.mp4")):
        d.mkdir(parents=True, exist_ok=True)
        for f in (p, folder / f"{p.stem}.project.json"):
            if f.exists():
                f.replace(d / f.name)
                moved.append(f.name)
    return moved


def export_version(project: dict, assets: dict, folder: Path, **kw) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    v = next_version(folder)
    out = folder / f"v{v:02d}.mp4"
    rep = render(project, assets, out, **kw)
    (folder / f"v{v:02d}.project.json").write_text(json.dumps(project, indent=1, ensure_ascii=False), encoding="utf-8")
    rep["version"] = v
    return rep


def snapshot(project: dict, assets: dict, t: float, out_png: Path) -> Path:
    fr = FrameRenderer(project, assets, project["format"]["w"], project["format"]["h"])
    try:
        Image.fromarray(fr.frame(t)).save(out_png)
    finally:
        fr.close()
    return out_png
