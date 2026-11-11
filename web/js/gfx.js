// WebGL2 renderer for the Program Monitor. MIRROR of app/render/gl.py + compositor.py (same shader files).
// Conventions: textures uploaded with FLIP_Y (uv 0,0 = bottom-left), premultiplied alpha, ONE/ONE_MINUS_SRC_ALPHA.

const HEADER = `
uniform vec2 resolution;
uniform vec2 px;
uniform float ratio;
uniform float srcRatio;
uniform float time;
uniform float progress;
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float rand(vec2 co) { return fract(sin(dot(co, vec2(12.9898, 78.233))) * 43758.5453); }
`;
const VS = `#version 300 es
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { v_uv = in_uv; gl_Position = vec4(in_pos, 0.0, 1.0); }`;
const COMPOSITE_FS = `#version 300 es
precision highp float;
uniform sampler2D u_tex; uniform float opacity; in vec2 v_uv; out vec4 fragColor;
void main() { fragColor = texture(u_tex, v_uv) * opacity; }`;

const decl = params => params.map(p => `uniform float ${p};\n`).join('');
const filterFS = (body, params) => `#version 300 es\nprecision highp float;\n${HEADER}${decl(params)}
uniform sampler2D u_tex;\nin vec2 v_uv; out vec4 fragColor;
vec4 getColor(vec2 uv) { return texture(u_tex, uv); }\n${body}\nvoid main() { fragColor = effect(v_uv); }\n`;
const transitionFS = (body, params) => `#version 300 es\nprecision highp float;\n${HEADER}${decl(params)}
uniform sampler2D u_from; uniform sampler2D u_to;\nin vec2 v_uv; out vec4 fragColor;
vec4 getFromColor(vec2 uv) { return texture(u_from, uv); }
vec4 getToColor(vec2 uv) { return texture(u_to, uv); }\n${body}\nvoid main() { fragColor = transition(v_uv); }\n`;

/** .cube text → {n, data: Float32Array (r fastest, then g, then b)} in 0..1 (DOMAIN_MIN/MAX applied). Mirror of luts.parse_cube. */
export function parseCube(txt) {
  let n = 0, dmin = [0, 0, 0], dmax = [1, 1, 1];
  const vals = [];
  for (const raw of txt.split(/\r?\n/)) {
    const s = raw.trim();
    if (!s || s[0] === '#') continue;
    const up = s.toUpperCase();
    if (up.startsWith('LUT_3D_SIZE')) n = parseInt(s.split(/\s+/)[1], 10);
    else if (up.startsWith('DOMAIN_MIN')) dmin = s.split(/\s+/).slice(1, 4).map(Number);
    else if (up.startsWith('DOMAIN_MAX')) dmax = s.split(/\s+/).slice(1, 4).map(Number);
    else if ('-.0123456789'.includes(s[0])) { const p = s.split(/\s+/); if (p.length >= 3) vals.push(+p[0], +p[1], +p[2]); }
  }
  if (!n || vals.length !== n ** 3 * 3) throw new Error(`not a valid 3D .cube (${vals.length / 3} rows for size ${n})`);
  const data = new Float32Array(vals.length);
  for (let i = 0; i < vals.length; i++) { const k = i % 3; data[i] = Math.min(1, Math.max(0, (vals[i] - dmin[k]) / Math.max(dmax[k] - dmin[k], 1e-6))); }
  return { n, data };
}

export function pxFor(w, h) { const refH = 1920, refW = refH * w / h; return [1 / refW, 1 / refH]; }

export function layerQuad(W, H, sw, sh, m, crop) {
  const fit = m.fit || 'fit';
  const base = fit === 'fit' ? Math.min(W / sw, H / sh) : fit === 'fill' ? Math.max(W / sw, H / sh) : 1;
  const s = base * (m.scale ?? 1), dw = sw * s, dh = sh * s;
  const cx = W / 2 + (m.x || 0), cy = H / 2 + (m.y || 0);
  const th = (m.rot || 0) * Math.PI / 180, co = Math.cos(th), si = Math.sin(th);
  const { l = 0, t = 0, r = 0, b = 0 } = crop || {};
  const out = [];
  for (const [u, v] of [[l, t], [1 - r, t], [l, 1 - b], [1 - r, 1 - b]]) {
    const ox = (u - 0.5) * dw, oy = (v - 0.5) * dh;
    const X = cx + ox * co - oy * si, Y = cy + ox * si + oy * co;
    out.push(X / W * 2 - 1, 1 - Y / H * 2, u, 1 - v);
  }
  return new Float32Array(out);
}
/** Full-frame text image scaled/rotated about its anchor (pivot in frame px). Mirror of text_quad in gl.py. */
export function textQuad(W, H, pivot, m) {
  const [px, py] = pivot, s = m.scale ?? 1, th = (m.rot || 0) * Math.PI / 180, co = Math.cos(th), si = Math.sin(th);
  const out = [];
  for (const [u, v] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
    const dx = u * W - px, dy = v * H - py;
    const X = px + (dx * co - dy * si) * s, Y = py + (dx * si + dy * co) * s;
    out.push(X / W * 2 - 1, 1 - Y / H * 2, u, 1 - v);
  }
  return new Float32Array(out);
}

/** Frame-pixel corners [TL, TR, BL, BR] of a placed media layer (for the gizmo / hit testing). */
export function layerCorners(W, H, sw, sh, m, crop) {
  const q = layerQuad(W, H, sw, sh, m, crop), pts = [];
  for (let i = 0; i < 4; i++) pts.push([(q[i * 4] + 1) / 2 * W, (1 - q[i * 4 + 1]) / 2 * H]);
  return pts;
}

const FULL_QUAD = new Float32Array([-1, 1, 0, 1, 1, 1, 1, 1, -1, -1, 0, 0, 1, -1, 1, 0]);

export class Gfx {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = this.gl = canvas.getContext('webgl2', { alpha: false, premultipliedAlpha: true, antialias: false, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL2 is not available in this browser');
    this.src = new Map(); this.progs = new Map(); this.fbos = new Map(); this.texs = new Map(); this.failed = new Set();
    this.vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, 64, gl.DYNAMIC_DRAW);
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 16, 8);
    this.comp = this._link(COMPOSITE_FS);
  }

  async load(presets) {
    const files = new Set([presets.color.shader, ...presets.filters.map(f => f.shader), ...presets.transitions.map(t => t.shader)]);
    await Promise.all([...files].map(async f => this.src.set(f, await (await fetch(`/effects/shaders/${f}`)).text())));
  }

  _link(fs) {
    const gl = this.gl;
    const mk = (type, s) => { const sh = gl.createShader(type); gl.shaderSource(sh, s); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh)); return sh; };
    const p = gl.createProgram();
    gl.attachShader(p, mk(gl.VERTEX_SHADER, VS)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, 0, 'in_pos'); gl.bindAttribLocation(p, 1, 'in_uv');
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    const loc = new Map();
    return { p, u: n => { if (!loc.has(n)) loc.set(n, gl.getUniformLocation(p, n)); return loc.get(n); } };
  }

  prog(kind, shader, params) {
    const key = `${kind}|${shader}|${params.join(',')}`;
    if (!this.progs.has(key)) {
      const body = this.src.get(shader) || '';
      try { this.progs.set(key, this._link(kind === 'filter' ? filterFS(body, params) : transitionFS(body, params))); }
      catch (e) { if (!this.failed.has(key)) { console.error('shader', shader, e.message); this.failed.add(key); } return null; }
    }
    return this.progs.get(key);
  }

  fbo(w, h, slot) {
    const key = `${w}x${h}|${slot}`;
    if (!this.fbos.has(key)) {
      const gl = this.gl, tex = this._newTex();
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      this.fbos.set(key, { fb, tex, w, h });
    }
    return this.fbos.get(key);
  }

  _newTex() {
    const gl = this.gl, tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
  }

  /** Upload a video/image/canvas element as a texture (reused per key). */
  upload(key, el, premultiply = false) {
    const gl = this.gl;
    let tex = this.texs.get(key);
    if (!tex) { tex = this._newTex(); this.texs.set(key, tex); }
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, premultiply);
    try { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, el); } catch (e) { return null; }
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    return tex;
  }
  dropTexture(key) { const t = this.texs.get(key); if (t) { this.gl.deleteTexture(t); this.texs.delete(key); } }

  _target(t) {
    const gl = this.gl;
    if (t) { gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb); gl.viewport(0, 0, t.w, t.h); }
    else { gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, this.canvas.width, this.canvas.height); }
  }
  clear(t, r = 0, g = 0, b = 0, a = 0) { const gl = this.gl; this._target(t); gl.clearColor(r, g, b, a); gl.clear(gl.COLOR_BUFFER_BIT); }

  _quad(q) { const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo); gl.bufferSubData(gl.ARRAY_BUFFER, 0, q); gl.bindVertexArray(this.vao); }
  _setCommon(pr, w, h) {
    const gl = this.gl;
    gl.uniform2f(pr.u('resolution'), w, h);
    const [a, b] = pxFor(w, h); gl.uniform2f(pr.u('px'), a, b);
  }

  /** 3D texture for a .cube file, or null while it loads (onReady fires when it can be drawn). Mirror of gl.py lut_texture. */
  lutTexture(file, onReady) {
    this.luts ||= new Map();
    const e = this.luts.get(file);
    if (e) return e.tex ? e : null;
    this.luts.set(file, { tex: null });
    fetch('/files/' + file.split('/').map(encodeURIComponent).join('/')).then(r => { if (!r.ok) throw new Error(r.status); return r.text(); }).then(txt => {
      const { n, data } = parseCube(txt);
      const gl = this.gl, tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_3D, tex);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      for (const p of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(gl.TEXTURE_3D, p, gl.CLAMP_TO_EDGE);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.texImage3D(gl.TEXTURE_3D, 0, gl.RGB16F, n, n, n, 0, gl.RGB, gl.FLOAT, data);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
      this.luts.set(file, { tex, n });
      onReady?.();
    }).catch(err => { console.error('LUT', file, err); this.luts.set(file, { tex: null, failed: true }); });
    return null;
  }
  dropLut(file) { const e = this.luts?.get(file); if (e?.tex) this.gl.deleteTexture(e.tex); this.luts?.delete(file); }

  filterPass(src, w, h, shader, values, time, slot, lut = null) {
    const names = Object.keys(values).sort();
    const pr = this.prog('filter', shader, names);
    if (!pr) return src;
    const gl = this.gl, out = this.fbo(w, h, slot);
    this._target(out); gl.disable(gl.BLEND); gl.useProgram(pr.p);
    if (lut) {
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_3D, lut.tex);
      gl.uniform1i(pr.u('u_lut'), 1); gl.uniform1f(pr.u('lutSize'), lut.n);
    }
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, src); gl.uniform1i(pr.u('u_tex'), 0);
    for (const k of names) gl.uniform1f(pr.u(k), +values[k]);
    this._setCommon(pr, w, h);
    gl.uniform1f(pr.u('srcRatio'), w / h); gl.uniform1f(pr.u('time'), time);
    this._quad(FULL_QUAD); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return out.tex;
  }

  transitionPass(from, to, W, H, shader, values, progress, time) {
    const names = Object.keys(values).sort();
    const pr = this.prog('transition', shader, names) || this.prog('transition', 'transitions/cross_dissolve.glsl', []);
    const gl = this.gl, out = this.fbo(W, H, 'trans');
    this.clear(out); gl.disable(gl.BLEND); gl.useProgram(pr.p);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, from); gl.uniform1i(pr.u('u_from'), 0);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, to); gl.uniform1i(pr.u('u_to'), 1);
    for (const k of names) gl.uniform1f(pr.u(k), +values[k]);
    gl.uniform1f(pr.u('progress'), progress); gl.uniform1f(pr.u('ratio'), W / H); gl.uniform1f(pr.u('time'), time);
    this._setCommon(pr, W, H);
    this._quad(FULL_QUAD); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.activeTexture(gl.TEXTURE0);
    return out.tex;
  }

  draw(tex, target, quad = FULL_QUAD, opacity = 1) {
    const gl = this.gl;
    this._target(target);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.comp.p);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.uniform1i(this.comp.u('u_tex'), 0); gl.uniform1f(this.comp.u('opacity'), opacity);
    this._quad(quad); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}
