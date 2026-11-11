// Transform gizmo for the Program monitor: move / scale / rotate / crop the selected layer by dragging.
// Geometry comes from the same functions the renderers use (layerCorners/textQuad), so the box matches the pixels.
import { html, useState } from '../vendor/preact-htm.js';
import { S, set, useStore, clipById, trackById, linkedIds } from './store.js';
import { visualItems, motionAt, cropAt, textPosAt } from './evaluate.js';
import { layerCorners } from './gfx.js';
import { textRect } from './textlayer.js';
import { liveProps, commitProps } from './edit.js';

const D2R = Math.PI / 180;

/** {corners: [TL, TR, BL, BR] frame px, center, kind} for a clip at time t, or null. */
export function layerGeom(c, t, W, H) {
  if (!c) return null;
  const m = motionAt(c, t);
  if (c.type === 'text') {
    const pos = textPosAt(c, t);
    const r = textRect(c, t, W, H, pos);
    const piv = [pos.x * W, pos.y * H], s = m.scale ?? 1, th = (m.rot || 0) * D2R, co = Math.cos(th), si = Math.sin(th);
    const tf = ([x, y]) => { const dx = x - piv[0], dy = y - piv[1]; return [piv[0] + (dx * co - dy * si) * s, piv[1] + (dx * si + dy * co) * s]; };
    return { corners: [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]].map(tf), center: piv, kind: 'text', m, pos };
  }
  if (c.type !== 'media') return null;
  const a = S.assets[c.asset] || {};
  const sw = a.meta?.w, sh = a.meta?.h;
  if (!sw || !sh) return null;
  return { corners: layerCorners(W, H, sw, sh, m, cropAt(c, t)), center: [W / 2 + (m.x || 0), H / 2 + (m.y || 0)], kind: 'media', m, crop: cropAt(c, t) };
}

function insideQuad([px, py], q) {
  const poly = [q[0], q[1], q[3], q[2]];
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % 4];
    const cr = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1);
    if (cr !== 0) { if (sign === 0) sign = Math.sign(cr); else if (Math.sign(cr) !== sign) return false; }
  }
  return true;
}

/** Topmost visible clip under a frame-px point at time t. */
export function hitTest(pt, t) {
  const p = S.project, W = p.format.w, H = p.format.h;
  const items = visualItems(p, t).reverse();
  for (const it of items) {
    for (const c of it.kind === 'clip' ? [it.clip] : [it.b, it.a]) {
      if (!c || trackById(c.track)?.lock) continue;
      const g = layerGeom(c, t, W, H);
      if (g && insideQuad(pt, g.corners)) return c;
    }
  }
  return null;
}

/** The clip the gizmo edits: the first selected video/image/text clip visible at the playhead. */
export function gizmoTarget() {
  const p = S.project;
  if (!p || S.playing) return null;
  const visible = new Set(visualItems(p, S.t).flatMap(it => it.kind === 'clip' ? [it.clip.id] : [it.a?.id, it.b?.id]).filter(Boolean));
  for (const id of S.sel.clips) {
    const c = clipById(id);
    if (c && visible.has(id) && trackById(c.track)?.kind !== 'audio' && !trackById(c.track)?.lock) return c;
  }
  return null;
}

const bbox = pts => { const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]); return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) }; };

export function Gizmo({ k }) {
  useStore(s => [s.project, s.sel, s.t, s.playing]);
  const [guides, setGuides] = useState([]);
  const c = gizmoTarget();
  const p = S.project;
  if (!c) return null;
  const W = p.format.w, H = p.format.h;
  const g = layerGeom(c, S.t, W, H);
  if (!g) return null;
  const [TL, TR, BL, BR] = g.corners;
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const hs = 7 / k;                                   // handle half-size in frame px
  const topMid = mid(TL, TR);
  const up = [topMid[0] - g.center[0], topMid[1] - g.center[1]];
  const ul = Math.hypot(...up) || 1;
  const knob = [topMid[0] + up[0] / ul * 34 / k, topMid[1] + up[1] / ul * 34 / k];

  const toFrame = (e, svg) => { const r = svg.getBoundingClientRect(); return [(e.clientX - r.left) / r.width * W, (e.clientY - r.top) / r.height * H]; };

  const start = (e, mode, extra = {}, tc = c, tg = g) => {
    e.stopPropagation(); e.preventDefault();
    const svg = e.currentTarget.ownerSVGElement || e.currentTarget;
    const p0 = toFrame(e, svg);
    if (mode === 'move' && tc === c) {                 // a different layer on top of the press point wins (like Premiere)
      const top = hitTest(p0, S.t);
      if (top && top.id !== c.id) {
        set({ sel: { clips: linkedIds([top.id]), transition: null, asset: null } });
        const g2 = layerGeom(top, S.t, W, H);
        if (g2) return start({ ...e, currentTarget: e.currentTarget, stopPropagation() {}, preventDefault() {}, clientX: e.clientX, clientY: e.clientY }, 'move', {}, top, g2);
        return;
      }
    }
    const c0 = tc;
    const m0 = tg.m, crop0 = tg.crop, pos0 = tg.pos, center = tg.center, kind0 = tg.kind;
    const others = visualItems(p, S.t).flatMap(it => it.kind === 'clip' ? [it.clip] : []).filter(o => o.id !== c0.id)
      .map(o => layerGeom(o, S.t, W, H)).filter(Boolean).map(o => bbox(o.corners));
    const box0 = bbox(tg.corners);
    const thr = 8 / k;
    let last = null;
    const compute = ev => {
      const pt = toFrame(ev, svg);
      let dx = pt[0] - p0[0], dy = pt[1] - p0[1];
      const gl = [];
      if (mode === 'move') {
        if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
        if (S.snap !== false) {
          const xs = [0, W / 2, W, W * 0.05, W * 0.95, ...others.flatMap(o => [o.x0, o.x1, (o.x0 + o.x1) / 2])];
          const ys = [0, H / 2, H, H * 0.05, H * 0.95, ...others.flatMap(o => [o.y0, o.y1, (o.y0 + o.y1) / 2])];
          const mine = (a0, a1, d) => [a0 + d, a1 + d, (a0 + a1) / 2 + d];
          let best = null;
          for (const v of mine(box0.x0, box0.x1, dx)) for (const tx of xs) { const dd = tx - v; if (Math.abs(dd) < thr && (!best || Math.abs(dd) < Math.abs(best.d))) best = { d: dd, at: tx }; }
          if (best) { dx += best.d; gl.push({ x: best.at }); }
          best = null;
          for (const v of mine(box0.y0, box0.y1, dy)) for (const ty of ys) { const dd = ty - v; if (Math.abs(dd) < thr && (!best || Math.abs(dd) < Math.abs(best.d))) best = { d: dd, at: ty }; }
          if (best) { dy += best.d; gl.push({ y: best.at }); }
        }
        setGuides(gl);
        return kind0 === 'text' ? { 'text.x': +(pos0.x + dx / W).toFixed(5), 'text.y': +(pos0.y + dy / H).toFixed(5) }
                                 : { 'motion.x': Math.round((m0.x || 0) + dx), 'motion.y': Math.round((m0.y || 0) + dy) };
      }
      if (mode === 'scale') {
        const d0 = Math.hypot(p0[0] - center[0], p0[1] - center[1]) || 1;
        let s = (m0.scale ?? 1) * Math.hypot(pt[0] - center[0], pt[1] - center[1]) / d0;
        if (Math.abs(s - 1) < 0.03) s = 1;                      // snap to 100%
        return { 'motion.scale': +Math.max(0.05, s).toFixed(4) };
      }
      if (mode === 'rotate') {
        const a0 = Math.atan2(p0[1] - center[1], p0[0] - center[0]), a1 = Math.atan2(pt[1] - center[1], pt[0] - center[0]);
        let r = (m0.rot || 0) + (a1 - a0) / D2R;
        r = ((r + 180) % 360 + 360) % 360 - 180;
        if (ev.shiftKey) r = Math.round(r / 15) * 15; else if (Math.abs(r) < 2) r = 0;
        return { 'motion.rot': +r.toFixed(2) };
      }
      if (mode === 'crop') {
        const ux = [TR[0] - TL[0], TR[1] - TL[1]], uy = [BL[0] - TL[0], BL[1] - TL[1]];
        const lx = Math.hypot(...ux) || 1, ly = Math.hypot(...uy) || 1;
        const fullW = lx / Math.max(0.05, 1 - crop0.l - crop0.r), fullH = ly / Math.max(0.05, 1 - crop0.t - crop0.b);
        const along = (dx * ux[0] + dy * ux[1]) / lx, down = (dx * uy[0] + dy * uy[1]) / ly;
        const e2 = extra.edge, v = {};
        const cl = (x, other) => +Math.min(0.95 - other, Math.max(0, x)).toFixed(4);
        if (e2 === 'l') v['crop.l'] = cl(crop0.l + along / fullW, crop0.r);
        if (e2 === 'r') v['crop.r'] = cl(crop0.r - along / fullW, crop0.l);
        if (e2 === 't') v['crop.t'] = cl(crop0.t + down / fullH, crop0.b);
        if (e2 === 'b') v['crop.b'] = cl(crop0.b - down / fullH, crop0.t);
        return v;
      }
    };
    const move = ev => { last = compute(ev); liveProps([c0.id], last); };
    const up = () => {
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
      setGuides([]);
      if (last) commitProps([c0.id], last, { move: 'Move', scale: 'Scale', rotate: 'Rotate', crop: 'Crop' }[mode]);
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };

  const poly = [TL, TR, BR, BL].map(q => q.join(',')).join(' ');
  const handle = (pt, cursor, onDown, round = false, title = '') => round
    ? html`<circle cx=${pt[0]} cy=${pt[1]} r=${hs} class="gz-h" style=${`cursor:${cursor}`} onPointerDown=${onDown}><title>${title}</title></circle>`
    : html`<rect x=${pt[0] - hs * 0.8} y=${pt[1] - hs * 0.8} width=${hs * 1.6} height=${hs * 1.6} class="gz-h sq" style=${`cursor:${cursor}`} onPointerDown=${onDown}><title>${title}</title></rect>`;
  return html`<g class="gizmo">
    ${guides.map(gd => gd.x != null ? html`<line x1=${gd.x} y1="0" x2=${gd.x} y2=${H} class="gz-guide" />` : html`<line x1="0" y1=${gd.y} x2=${W} y2=${gd.y} class="gz-guide" />`)}
    <polygon points=${poly} class="gz-box" onPointerDown=${e => start(e, 'move')}
      onDblClick=${() => c.type === 'text' && window.dispatchEvent(new CustomEvent('vs-edit-text'))}><title>Drag to move${c.type === 'text' ? ' · double-click to edit text' : ''}</title></polygon>
    <line x1=${topMid[0]} y1=${topMid[1]} x2=${knob[0]} y2=${knob[1]} class="gz-line" />
    ${handle(knob, 'grab', e => start(e, 'rotate'), true, 'Rotate (Shift = 15° steps)')}
    ${[TL, TR, BL, BR].map(q => handle(q, 'nwse-resize', e => start(e, 'scale'), true, 'Scale'))}
    ${g.kind === 'media' && [['l', mid(TL, BL)], ['r', mid(TR, BR)], ['t', topMid], ['b', mid(BL, BR)]].map(([edge, pt]) =>
      handle(pt, edge === 'l' || edge === 'r' ? 'ew-resize' : 'ns-resize', e => start(e, 'crop', { edge }), false, 'Crop'))}
    <circle cx=${g.center[0]} cy=${g.center[1]} r=${hs * 0.45} class="gz-center" />
  </g>`;
}

/** Ctrl+arrow nudge for the gizmo target (1 px, Shift = 10 px). Returns true if handled. */
export function nudge(dx, dy) {
  const c = gizmoTarget();
  if (!c) return false;
  const p = S.project, W = p.format.w, H = p.format.h;
  const g = layerGeom(c, S.t, W, H);
  const v = g.kind === 'text' ? { 'text.x': +(g.pos.x + dx / W).toFixed(5), 'text.y': +(g.pos.y + dy / H).toFixed(5) }
                             : { 'motion.x': (g.m.x || 0) + dx, 'motion.y': (g.m.y || 0) + dy };
  commitProps([c.id], v, 'Nudge');
  return true;
}

export function selectAt(pt) {
  const c = hitTest(pt, S.t);
  if (c) set({ sel: { clips: linkedIds([c.id]), transition: null, asset: null } });
  else set({ sel: { clips: [], transition: null, asset: null } });
  return c;
}
