// Word-by-word animated captions on Canvas2D. MIRROR of app/render/caption.py — keep both in sync.
import { animState } from './textlayer.js';

const easeOutCubic = x => 1 - (1 - x) ** 3;
const easeOutBack = x => 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const POP_T = 0.18, BOUNCE_T = 0.28, FADE_T = 0.12, BIG = 20000;

export const STYLE_DEFAULTS = {
  font: 'Poppins', weight: 800, size: 64, case: 'none', line_height: 1.15, width: 0.86,
  color: '#FFFFFF', outline: 5, outline_color: '#000000', shadow: 4,
  glow: null, gradient: null, box: null, line_colors: null, stagger: 0,
  mode: 'karaoke', layout: 'flow',
  active: { color: '#FFD84D', scale: 1.08, box: null }, past: {}, future: {},
  emph_color: null, emph_scale: 1.0,
};

export function resolve(style) {
  const s = { ...STYLE_DEFAULTS, ...(style || {}) };
  s.active = { ...STYLE_DEFAULTS.active, ...(s.active || {}) };
  s.past = s.past || {}; s.future = s.future || {};
  return s;
}

const disp = (w, s) => s.case === 'upper' ? w.toUpperCase() : w;

/** Slot width factor so a scaled-up active / emphasis word never runs into its neighbours. */
function reserve(s) {
  let g = 1;
  if (s.mode === 'karaoke' || s.mode === 'karaoke_box') g = Math.max(g, s.active.scale ?? 1);
  if (s.emph_color) g = Math.max(g, s.emph_scale ?? 1);
  return g;
}

function rgba(hex) {
  let h = (hex || '#FFFFFF').replace('#', '');
  if (h.length === 6) h += 'FF';
  const n = [0, 2, 4, 6].map(i => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${n[0]},${n[1]},${n[2]},${(n[3] / 255).toFixed(3)})`;
}

export function wordStates(c, t, s) {
  const words = c.text.caption.words, rel = t - c.start, n = words.length;
  return words.map((w, i) => {
    const t0 = w.t0, end = i + 1 < n ? words[i + 1].t0 : Infinity;
    const state = rel < t0 ? 'future' : rel < end ? 'active' : 'past';
    const p = clamp((rel - t0) / POP_T);
    const o = { color: s.color, scale: 1, dy: 0, alpha: 1, chars: null, pill: false, grad: !!s.gradient, state };
    if (w.emph && s.emph_color) { o.color = s.emph_color; o.grad = false; o.scale *= (s.emph_scale ?? 1); }
    const mode = s.mode, act = s.active;
    if (['karaoke', 'karaoke_box', 'pop', 'bounce'].includes(mode) && state === 'active' && act.color) { o.color = act.color; o.grad = false; }
    if (['karaoke', 'karaoke_box', 'bounce'].includes(mode)) {
      if (state === 'future' && s.future.color) { o.color = s.future.color; o.grad = false; }
      if (state === 'past' && s.past.color) { o.color = s.past.color; o.grad = false; }
    }
    if ((mode === 'karaoke' || mode === 'karaoke_box') && state === 'active') o.scale *= 1 + ((act.scale ?? 1) - 1) * easeOutCubic(p);
    if (mode === 'karaoke_box' && state === 'active' && act.box) o.pill = true;
    if (mode === 'reveal') o.alpha = state === 'future' ? 0 : clamp((rel - t0) / FADE_T);
    else if (mode === 'pop') {
      if (state === 'future') o.alpha = 0;
      else { o.scale *= 0.6 + 0.4 * easeOutBack(p); o.alpha = clamp(p * 2); }
    } else if (mode === 'bounce' && state === 'active') o.dy = -Math.sin(Math.PI * clamp((rel - t0) / BOUNCE_T)) * 0.22;
    else if (mode === 'typewriter') {
      const ln = w.w.length;
      if (state === 'future') o.alpha = 0;
      else if (state === 'active') o.chars = clamp(Math.ceil((rel - t0) / Math.max(0.05, w.t1 - t0) * ln), 1, ln);
    }
    if (s.stagger) o.dy += (s.stagger / 100) * (i % 2 ? 1 : -1);
    return o;
  });
}

/** Cheap per-frame cache key: changes only when some word's look changes. */
export function captionStateKey(c, t) {
  if (!c.text.caption?.words?.length) return '';
  const s = resolve(c.text.caption.style);
  return wordStates(c, t, s).map(o => `${o.color}${o.scale.toFixed(3)}${o.dy.toFixed(3)}${o.alpha.toFixed(2)}${o.chars}`).join('|');
}

const mctx = document.createElement('canvas').getContext('2d');
const fontStr = (s, px) => `${s.weight} ${px}px "${s.font}", "Segoe UI", sans-serif`;
// Widths measured at 1000 px and scaled (same as caption.py: FreeType hints advances at small sizes).
const bigctx = document.createElement('canvas').getContext('2d');
function measure(s, txt, px) {
  bigctx.font = fontStr(s, 1000); bigctx.fontKerning = 'none';
  return bigctx.measureText(txt).width * px / 1000;
}
// Synthetic ascent/descent (em fractions), same as caption.py: browser and FreeType font metrics differ slightly.
function metrics(ctx, s, px) {
  ctx.font = fontStr(s, px); ctx.fontKerning = 'none';
  return { asc: 0.80 * px, desc: 0.25 * px };
}

export function layout(c, W, H, st, s, ctx = mctx) {
  const k = Math.min(W, H) / 1080;
  const size = Math.max(1, Math.round(s.size * k * st.scale));
  const { asc, desc } = metrics(ctx, s, size);
  const space = measure(s, ' ', size), maxw = (s.width ?? 0.86) * W;
  const words = c.text.caption.words;
  const grow = reserve(s);
  const lines = []; let cur = [], curW = 0;
  words.forEach((w, i) => {
    const nw = measure(s, disp(w.w, s), size);
    const ww = nw * ((s.mode === 'karaoke' || s.mode === 'karaoke_box' || w.emph) ? grow : 1);
    if (cur.length && (s.layout === 'stack' || curW + space + ww > maxw)) { lines.push(cur); cur = []; curW = 0; }
    curW += (cur.length ? space : 0) + ww;
    cur.push([i, ww, nw]);
  });
  if (cur.length) lines.push(cur);
  const lh = size * (s.line_height ?? 1.15);
  const ax = c.text.x * W, ay = c.text.y * H + st.dy * H, top = ay - lh * lines.length / 2;
  const out = lines.map((ln, li) => {
    const lineW = ln.reduce((a, [, ww]) => a + ww, 0) + space * (ln.length - 1);
    // (ww = slot width incl. room for scale-up, nw = natural width)
    let x = ax - lineW / 2;
    const base = top + li * lh + (lh - (asc + desc)) / 2 + asc;
    const items = ln.map(([i, ww, nw]) => { const it = { i, x, w: ww, nw }; x += ww + space; return it; });
    return { items, x0: ax - lineW / 2, w: lineW, base, top: top + li * lh };
  });
  return { size, lines: out, asc, desc, lh, k, top };
}

/** Block rect {x, y, w, h} in frame px, for the gizmo. */
export function captionRect(c, t, W, H, pos) {
  if (!c.text.caption?.words?.length) return { x: W / 2 - 4, y: H / 2 - 4, w: 8, h: 8 };
  const st = animState(c, t), s = resolve(c.text.caption.style);
  const cc = pos ? { ...c, text: { ...c.text, x: pos.x, y: pos.y } } : c;
  const L = layout(cc, W, H, st, s);
  const x0 = Math.min(...L.lines.map(l => l.x0)), x1 = Math.max(...L.lines.map(l => l.x0 + l.w)), pad = 0.2 * L.size;
  return { x: x0 - pad, y: L.top - pad * 0.5, w: x1 - x0 + 2 * pad, h: L.lh * L.lines.length + pad };
}

const scratch = document.createElement('canvas');
const fade = document.createElement('canvas');

export function renderCaption(canvas, c, t, W, H) {
  const cap = c.text.caption;
  if (!cap?.words?.length) return null;
  const st = animState(c, t);
  if (st.alpha <= 0.001) return null;
  const s = resolve(cap.style);
  const looks = wordStates(c, t, s);
  if (looks.every(o => o.alpha <= 0.001)) return null;
  const sc = canvas.width / W;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  scratch.width = canvas.width; scratch.height = canvas.height;
  const tc = scratch.getContext('2d');
  tc.setTransform(sc, 0, 0, sc, 0, 0);
  const L = layout(c, W, H, st, s, tc);
  const { size, lines, asc, desc, k } = L;
  const words = cap.words;
  const outline = Math.round((s.outline || 0) * k);
  const stroke = rgba(s.outline_color || '#000000');
  ctx.setTransform(sc, 0, 0, sc, 0, 0);
  const placed = [];
  lines.forEach((ln, li) => {
    if (s.box) {
      const h = size * 1.3, vc = ln.base - (asc - desc) / 2;
      ctx.fillStyle = rgba(s.box.color || '#000000B3');
      ctx.beginPath(); ctx.roundRect(ln.x0 - 0.3 * size, vc - h / 2, ln.w + 0.6 * size, h, (s.box.radius ?? 0.22) * size); ctx.fill();
    }
    for (const it of ln.items) {
      const o = looks[it.i];
      if (o.alpha <= 0.001) continue;
      let txt = disp(words[it.i].w, s);
      if (s.line_colors && o.color === s.color && !(o.state === 'active' && s.mode !== 'none')) {
        o.color = s.line_colors[li % s.line_colors.length]; o.grad = false;
      }
      const vc = ln.base - (asc - desc) / 2 + o.dy * size;
      if (o.chars != null) {
        placed.push({ txt: txt.slice(0, o.chars), x: it.x + (it.w - it.nw) / 2, base: ln.base + o.dy * size, px: size, o, li });
        continue;
      }
      const px = Math.abs(o.scale - 1) < 1e-4 ? size : Math.max(1, Math.round(size * o.scale));
      let ws = it.nw, base = ln.base + o.dy * size;
      if (px !== size) {
        const m2 = metrics(tc, s, px);
        ws = measure(s, txt, px);
        base = vc + (m2.asc - m2.desc) / 2;
      }
      const cx = it.x + it.w / 2, x = cx - ws / 2;
      if (o.pill) {
        const ph = size * o.scale * 1.18, pw = ws + 0.36 * size;
        ctx.fillStyle = rgba(s.active.box);
        ctx.beginPath(); ctx.roundRect(cx - pw / 2, vc - ph / 2, pw, ph, Math.min(ph / 2, 0.3 * size)); ctx.fill();
      }
      placed.push({ txt, x, base, px, o, li });
    }
  });
  // text layer: outlines for all solid words, then fills
  tc.clearRect(0, 0, W, H);
  tc.textBaseline = 'alphabetic'; tc.textAlign = 'left'; tc.lineJoin = 'round';
  const grads = s.gradient ? lines.map(ln => {
    const g = tc.createLinearGradient(0, ln.base - asc, 0, ln.base + desc);
    g.addColorStop(0, rgba(s.gradient[0])); g.addColorStop(1, rgba(s.gradient[1]));
    return g;
  }) : null;
  const solid = placed.filter(p => p.o.alpha >= 0.999), faded = placed.filter(p => p.o.alpha < 0.999);
  const drawWord = (g, p, strokeIt, fillIt) => {
    g.font = fontStr(s, p.px); g.fontKerning = 'none';
    if (strokeIt && outline) { g.lineWidth = outline * 2; g.strokeStyle = stroke; g.fillStyle = stroke; g.strokeText(p.txt, p.x, p.base); g.fillText(p.txt, p.x, p.base); }
    if (fillIt) { g.fillStyle = p.o.grad && grads ? grads[p.li] : rgba(p.o.color); g.fillText(p.txt, p.x, p.base); }
  };
  solid.forEach(p => drawWord(tc, p, true, false));
  solid.forEach(p => drawWord(tc, p, false, true));
  if (faded.length) {
    fade.width = canvas.width; fade.height = canvas.height;
    const fc = fade.getContext('2d');
    for (const p of faded) {
      fc.setTransform(1, 0, 0, 1, 0, 0); fc.clearRect(0, 0, fade.width, fade.height);
      fc.setTransform(sc, 0, 0, sc, 0, 0);
      fc.textBaseline = 'alphabetic'; fc.textAlign = 'left'; fc.lineJoin = 'round';
      const q = { ...p, o: { ...p.o, color: p.o.grad ? s.gradient[0] : p.o.color, grad: false } };
      drawWord(fc, q, true, true);
      tc.save(); tc.setTransform(1, 0, 0, 1, 0, 0); tc.globalAlpha = p.o.alpha; tc.drawImage(fade, 0, 0); tc.restore();
    }
  }
  // glow, shadow (shadow-only draws via the off-canvas offset trick), then the text
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  const shadowOnly = (color, blur, offY, times = 1) => {
    ctx.save();
    ctx.shadowColor = color; ctx.shadowBlur = blur; ctx.shadowOffsetX = BIG; ctx.shadowOffsetY = offY;
    for (let i = 0; i < times; i++) ctx.drawImage(scratch, -BIG, 0);
    ctx.restore();
  };
  if (s.glow) shadowOnly(rgba(s.glow.color || '#00E5FF'), (s.glow.r ?? 16) * k * sc, 0, Math.max(1, Math.floor(s.glow.strength ?? 1)));
  if ((s.shadow || 0) > 0) shadowOnly('rgba(0,0,0,0.6)', s.shadow * k * sc, Math.round(s.shadow * k * 0.5) * sc);
  ctx.drawImage(scratch, 0, 0);
  const key = looks.map(o => `${o.color}${o.scale.toFixed(3)}${o.dy.toFixed(3)}${o.alpha.toFixed(2)}${o.chars}${o.pill ? 1 : 0}`).join('|');
  return { alpha: st.alpha, key: `cap|${st.scale.toFixed(3)}|${st.dy.toFixed(4)}|${key}` };
}
