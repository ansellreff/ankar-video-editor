// Text layers on Canvas2D. MIRROR of app/render/text.py — keep both in sync (no kerning on either side).
import { renderCaption, captionRect } from './captionlayer.js';
const easeOutCubic = x => 1 - (1 - x) ** 3;
const easeOutBack = x => 1 + 2.70158 * (x - 1) ** 3 + 1.70158 * (x - 1) ** 2;

export function animState(c, t) {
  const tx = c.text, an = tx.anim, rel = t - c.start, dur = c.dur;
  const st = { alpha: 1, scale: 1, dy: 0, chars: tx.content.length };
  const ind = Math.max(an.in_dur || 0, 1e-6), outd = Math.max(an.out_dur || 0, 1e-6);
  const pi = Math.min(1, Math.max(0, rel / ind)), po = Math.min(1, Math.max(0, (dur - rel) / outd));
  const k = an.in || 'none';
  if (k === 'fade') st.alpha *= pi;
  else if (k === 'pop') { st.scale = 0.85 + 0.15 * easeOutBack(pi); st.alpha *= Math.min(1, pi * 2); }
  else if (k === 'slide_up') { st.dy = (1 - easeOutCubic(pi)) * 0.04; st.alpha *= pi; }
  else if (k === 'typewriter') {
    st.chars = tx.times ? tx.times.filter(x => x <= rel + 1e-6).length : Math.floor(pi * tx.content.length + 1e-6);
  }
  if ((an.out || 'none') !== 'none' && (an.out_dur || 0) > 0) st.alpha *= po;
  return st;
}

function rgba(hex) {
  let h = (hex || '#FFFFFF').replace('#', '');
  if (h.length === 6) h += 'FF';
  const n = [0, 2, 4, 6].map(i => parseInt(h.slice(i, i + 2), 16));
  return `rgba(${n[0]},${n[1]},${n[2]},${(n[3] / 255).toFixed(3)})`;
}

const scratch = document.createElement('canvas');
const measureCtx = document.createElement('canvas').getContext('2d');

/** Block rectangle {x, y, w, h} in frame px (before motion scale/rotation), for the gizmo and hit testing. */
export function textRect(c, t, W, H, pos) {
  if (c.text.caption) return captionRect(c, t, W, H, pos);
  const st = animState(c, t);
  const s = c.text.style, k = Math.min(W, H) / 1080;
  const size = Math.max(1, Math.round(s.size * k * st.scale));
  measureCtx.font = `${s.weight} ${size}px "${s.font}", "Segoe UI", sans-serif`;
  measureCtx.fontKerning = 'none';
  const sp = (s.spacing || 0) * k * st.scale, lh = size * (s.line_height || 1.2);
  const lines = c.text.content.split('\n');
  const widths = lines.map(ln => ln ? measureCtx.measureText(ln).width + sp * (ln.length - 1) : 0);
  const bw = Math.max(8, ...widths), bh = lh * lines.length;
  const ax = (pos?.x ?? c.text.x) * W, ay = (pos?.y ?? c.text.y) * H + st.dy * H;
  const x0 = s.align === 'left' ? ax : s.align === 'right' ? ax - bw : ax - bw / 2;
  const pad = s.box ? 0.35 * size : 0.1 * size, padY = s.box ? 0.2 * size : 0.05 * size;
  return { x: x0 - pad, y: ay - bh / 2 - padY, w: bw + 2 * pad, h: bh + 2 * padY };
}

/** Draws the text clip into `canvas` (sized to the render resolution). Returns {alpha} or null if invisible. */
export function renderText(canvas, c, t, W, H) {
  if (c.text.caption) return renderCaption(canvas, c, t, W, H);
  const st = animState(c, t);
  if (st.alpha <= 0.001 || (st.chars <= 0 && c.text.anim.in === 'typewriter')) return null;
  const sc = canvas.width / W;
  const s = c.text.style, tx = c.text;
  const k = Math.min(W, H) / 1080;
  const size = Math.max(1, Math.round(s.size * k * st.scale));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  scratch.width = canvas.width; scratch.height = canvas.height;
  const tc = scratch.getContext('2d');
  tc.setTransform(sc, 0, 0, sc, 0, 0);
  tc.clearRect(0, 0, W, H);
  tc.font = `${s.weight} ${size}px "${s.font}", "Segoe UI", sans-serif`;
  tc.fontKerning = 'none';
  tc.textBaseline = 'alphabetic'; tc.textAlign = 'left';
  const m = tc.measureText('Hg');
  const asc = m.fontBoundingBoxAscent ?? size * 1.05, desc = m.fontBoundingBoxDescent ?? size * 0.35;
  const sp = (s.spacing || 0) * k * st.scale;
  const lh = size * (s.line_height || 1.2);
  const lines = tx.content.split('\n');
  const offs = lines.map(ln => Array.from({ length: ln.length + 1 }, (_, i) => tc.measureText(ln.slice(0, i)).width + i * sp));
  const widths = lines.map((ln, i) => ln ? offs[i][ln.length] - sp : 0);
  const blockW = Math.max(0, ...widths), blockH = lh * lines.length;
  const ax = tx.x * W, ay = tx.y * H + st.dy * H, top = ay - blockH / 2;
  const x0s = widths.map(w => s.align === 'left' ? ax : s.align === 'right' ? ax - w : ax - w / 2);

  // box (drawn on the final canvas, under the text)
  ctx.setTransform(sc, 0, 0, sc, 0, 0);
  if (s.box) {
    const bx0 = s.align === 'left' ? ax : s.align === 'right' ? ax - blockW : ax - blockW / 2;
    const px = 0.35 * size, py = 0.2 * size;
    ctx.fillStyle = rgba(s.box_color || '#000000B3');
    ctx.beginPath(); ctx.roundRect(bx0 - px, top - py, blockW + 2 * px, blockH + 2 * py, 0.15 * size); ctx.fill();
  }
  // glyphs on the scratch layer
  const outline = Math.round((s.outline || 0) * k);
  tc.lineJoin = 'round'; tc.lineWidth = outline * 2; tc.strokeStyle = rgba(s.outline_color || '#000000'); tc.fillStyle = rgba(s.color);
  let budget = st.chars;
  lines.forEach((ln, li) => {
    const base = top + li * lh + (lh - (asc + desc)) / 2 + asc;
    for (let i = 0; i < ln.length; i++) {
      if (budget <= 0) break;
      budget--;
      const ch = ln[i];
      if (ch === ' ') continue;
      const x = x0s[li] + offs[li][i];
      if (outline) tc.strokeText(ch, x, base);
      tc.fillText(ch, x, base);
    }
    budget--;
  });
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  if ((s.shadow || 0) > 0) {
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.6)'; ctx.shadowBlur = s.shadow * k * sc; ctx.shadowOffsetY = Math.round(s.shadow * k * 0.5) * sc;
    ctx.drawImage(scratch, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(scratch, 0, 0);
  }
  return { alpha: st.alpha, key: `${st.chars}|${st.scale.toFixed(3)}|${st.dy.toFixed(4)}` };
}
