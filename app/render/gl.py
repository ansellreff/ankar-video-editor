"""Headless OpenGL (moderngl) running the SAME shader files as the browser preview (web/js/gfx.js).

Conventions shared with gfx.js — keep them identical:
- textures are uploaded bottom-row-first (np.flipud), so uv (0,0) is the bottom-left like WebGL with FLIP_Y
- layers are premultiplied RGBA, blended with ONE, ONE_MINUS_SRC_ALPHA
- `px` = one reference pixel (frame scaled to 1920 px tall) in uv units; `ratio` = output w/h; `srcRatio` = layer w/h
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import moderngl
import numpy as np

from ..paths import EFFECTS

HEADER = """
uniform vec2 resolution;
uniform vec2 px;
uniform float ratio;
uniform float srcRatio;
uniform float time;
uniform float progress;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float rand(vec2 co) { return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453); }
"""

VS = """#version 330
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { v_uv = in_uv; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

COMPOSITE_FS = """#version 330
uniform sampler2D u_tex; uniform float opacity; in vec2 v_uv; out vec4 fragColor;
void main() { fragColor = texture(u_tex, v_uv) * opacity; }
"""


def load_presets() -> dict:
    return json.loads((EFFECTS / "presets.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def shader_body(rel: str) -> str:
    return (EFFECTS / "shaders" / rel).read_text(encoding="utf-8")


def build_filter_fs(body: str, params: list[str]) -> str:
    decl = "".join(f"uniform float {p};\n" for p in params)
    return ("#version 330\n" + HEADER + decl +
            "uniform sampler2D u_tex;\nin vec2 v_uv; out vec4 fragColor;\n"
            "vec4 getColor(vec2 uv) { return texture(u_tex, uv); }\n" + body +
            "\nvoid main() { fragColor = effect(v_uv); }\n")


def build_transition_fs(body: str, params: list[str]) -> str:
    decl = "".join(f"uniform float {p};\n" for p in params)
    return ("#version 330\n" + HEADER + decl +
            "uniform sampler2D u_from; uniform sampler2D u_to;\nin vec2 v_uv; out vec4 fragColor;\n"
            "vec4 getFromColor(vec2 uv) { return texture(u_from, uv); }\n"
            "vec4 getToColor(vec2 uv) { return texture(u_to, uv); }\n" + body +
            "\nvoid main() { fragColor = transition(v_uv); }\n")


def px_for(w: int, h: int) -> tuple[float, float]:
    """One reference pixel in uv for a w x h image (reference = scaled to 1920 tall)."""
    ref_h = 1920.0
    ref_w = ref_h * w / h
    return (1.0 / ref_w, 1.0 / ref_h)


def layer_quad(W, H, sw, sh, motion: dict, crop: dict) -> np.ndarray:
    """4 vertices (TL, TR, BL, BR) of a placed layer: x, y in clip space, u, v in texture space."""
    fit = motion.get("fit", "fit")
    base = min(W / sw, H / sh) if fit == "fit" else max(W / sw, H / sh) if fit == "fill" else 1.0
    s = base * float(motion.get("scale", 1.0))
    dw, dh = sw * s, sh * s
    cx, cy = W / 2 + float(motion.get("x", 0)), H / 2 + float(motion.get("y", 0))
    th = math.radians(float(motion.get("rot", 0)))
    co, si = math.cos(th), math.sin(th)
    l, t, r, b = (float(crop.get(k, 0)) for k in ("l", "t", "r", "b"))
    out = []
    for u, v in ((l, t), (1 - r, t), (l, 1 - b), (1 - r, 1 - b)):
        ox, oy = (u - 0.5) * dw, (v - 0.5) * dh
        X = cx + ox * co - oy * si
        Y = cy + ox * si + oy * co
        out.append((X / W * 2 - 1, 1 - Y / H * 2, u, 1 - v))
    return np.array(out, dtype="f4")


def text_quad(W, H, pivot, motion: dict) -> np.ndarray:
    """Full-frame text image scaled/rotated about its anchor (pivot, frame px). Mirror of textQuad in gfx.js."""
    px_, py_ = pivot
    s = float(motion.get("scale", 1.0))
    th = math.radians(float(motion.get("rot", 0)))
    co, si = math.cos(th), math.sin(th)
    out = []
    for u, v in ((0, 0), (1, 0), (0, 1), (1, 1)):
        dx, dy = u * W - px_, v * H - py_
        X = px_ + (dx * co - dy * si) * s
        Y = py_ + (dx * si + dy * co) * s
        out.append((X / W * 2 - 1, 1 - Y / H * 2, u, 1 - v))
    return np.array(out, dtype="f4")


FULL_QUAD = np.array([(-1, 1, 0, 1), (1, 1, 1, 1), (-1, -1, 0, 0), (1, -1, 1, 0)], dtype="f4")


class GL:
    def __init__(self):
        self.ctx = moderngl.create_standalone_context(require=330)
        self.presets = load_presets()
        self.progs: dict = {}
        self.fbos: dict = {}
        self.vbo = self.ctx.buffer(reserve=4 * 4 * 4, dynamic=True)
        self.composite = self.ctx.program(vertex_shader=VS, fragment_shader=COMPOSITE_FS)
        self.cvao = self.ctx.vertex_array(self.composite, [(self.vbo, "2f 2f", "in_pos", "in_uv")])
        self.renderer = self.ctx.info["GL_RENDERER"]

    # ------------------------------------------------------------- resources
    def _prog(self, kind, shader, params):
        key = (kind, shader, tuple(params))
        if key not in self.progs:
            body = shader_body(shader)
            fs = build_filter_fs(body, params) if kind == "filter" else build_transition_fs(body, params)
            prog = self.ctx.program(vertex_shader=VS, fragment_shader=fs)
            vao = self.ctx.vertex_array(prog, [(self.vbo, "2f 2f", "in_pos", "in_uv")])
            self.progs[key] = (prog, vao)
        return self.progs[key]

    def fbo(self, w, h, slot):
        key = (w, h, slot)
        if key not in self.fbos:
            tex = self.ctx.texture((w, h), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self.fbos[key] = (self.ctx.framebuffer(color_attachments=[tex]), tex)
        return self.fbos[key]

    def upload(self, arr: np.ndarray, slot="src"):
        """RGB/RGBA uint8 array (top row first) → texture (reused per size/slot)."""
        h, w = arr.shape[:2]
        comps = arr.shape[2] if arr.ndim == 3 else 1
        key = ("tex", w, h, comps, slot)
        tex = self.fbos.get(key)
        if tex is None:
            tex = self.ctx.texture((w, h), comps)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            self.fbos[key] = tex
        tex.write(np.ascontiguousarray(np.flipud(arr)).tobytes())
        return tex

    @staticmethod
    def _set(prog, name, value):
        if name in prog:
            prog[name].value = value

    # ------------------------------------------------------------- passes
    def lut_texture(self, file: str):
        """3D texture for a .cube file (cached per file + mtime). Half floats, trilinear — same as gfx.js."""
        from .. import luts
        n, data = luts.load(file)
        key = ("lut", file, id(data))
        tex = self.fbos.get(key)
        if tex is None:
            tex = self.ctx.texture3d((n, n, n), 3, np.ascontiguousarray(data.astype(np.float16)).tobytes(), dtype="f2")
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = tex.repeat_z = False
            self.fbos[key] = tex
        return tex, n

    def filter_pass(self, src, w, h, shader, values: dict, time_s, slot, lut=None):
        names = sorted(values)
        prog, vao = self._prog("filter", shader, names)
        fbo, tex = self.fbo(w, h, slot)
        fbo.use()
        self.ctx.disable(moderngl.BLEND)
        src.use(0)
        self._set(prog, "u_tex", 0)
        if lut:
            lt, n = self.lut_texture(lut)
            lt.use(1)
            self._set(prog, "u_lut", 1)
            self._set(prog, "lutSize", float(n))
        for k in names:
            self._set(prog, k, float(values[k]))
        self._set(prog, "resolution", (float(w), float(h)))
        self._set(prog, "px", px_for(w, h))
        self._set(prog, "srcRatio", w / h)
        self._set(prog, "time", float(time_s))
        self.vbo.write(FULL_QUAD.tobytes())
        vao.render(moderngl.TRIANGLE_STRIP)
        return tex

    def transition_pass(self, from_tex, to_tex, W, H, shader, values: dict, progress, time_s, slot="trans"):
        names = sorted(values)
        prog, vao = self._prog("transition", shader, names)
        fbo, tex = self.fbo(W, H, slot)
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        self.ctx.disable(moderngl.BLEND)
        from_tex.use(0)
        to_tex.use(1)
        self._set(prog, "u_from", 0)
        self._set(prog, "u_to", 1)
        for k in names:
            self._set(prog, k, float(values[k]))
        self._set(prog, "progress", float(progress))
        self._set(prog, "ratio", W / H)
        self._set(prog, "resolution", (float(W), float(H)))
        self._set(prog, "px", px_for(W, H))
        self._set(prog, "time", float(time_s))
        self.vbo.write(FULL_QUAD.tobytes())
        vao.render(moderngl.TRIANGLE_STRIP)
        return tex

    def draw(self, tex, target_fbo, quad=FULL_QUAD, opacity=1.0, clear=None):
        target_fbo.use()
        if clear is not None:
            target_fbo.clear(*clear)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
        tex.use(0)
        self.composite["u_tex"].value = 0
        self.composite["opacity"].value = float(opacity)
        self.vbo.write(np.ascontiguousarray(quad, dtype="f4").tobytes())
        self.cvao.render(moderngl.TRIANGLE_STRIP)

    def read_rgb(self, fbo, w, h) -> np.ndarray:
        data = fbo.read(components=3, alignment=1)
        return np.flipud(np.frombuffer(data, np.uint8).reshape(h, w, 3))
