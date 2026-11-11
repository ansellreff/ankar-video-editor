// What is visible at time t. MIRROR of app/render/timeline.py — keep both in sync.
// clips whose length is `dur` (text, stills, freeze frames, narration) rather than (out-in)/speed
export const hasDur = c => c.type === 'text' || c.type === 'tts' || !!c.still || c.hold != null;
export const clipDur = c => hasDur(c) ? c.dur : (c.out - c.in) / (c.speed || 1);
export const clipEnd = c => c.start + clipDur(c);

export function srcTime(c, t, srcFps = 30) {
  if (c.type === 'tts') return Math.max(0, (c.in || 0) + t - c.start);   // narration: position in the generated file
  if (c.type !== 'media' || c.still) return 0;
  if (c.hold != null) return c.hold;                         // freeze frame
  const rel = (t - c.start) * (c.speed || 1);
  const st = c.reverse ? c.out - rel : c.in + rel;
  return Math.max(c.in, Math.min(st, c.out - 0.5 / srcFps));
}

export function transWindow(x, byId) {
  const a = byId[x.a], b = byId[x.b], d = x.dur;
  if (a && b) return [b.start - d / 2, b.start + d / 2, a, b];
  if (b) return [b.start, b.start + d, null, b];
  return [clipEnd(a) - d, clipEnd(a), a, null];
}

export function fadeMult(c, t) {
  let m = 1;
  if (c.fade_in > 0) m *= Math.min(1, Math.max(0, (t - c.start) / c.fade_in));
  if (c.fade_out > 0) m *= Math.min(1, Math.max(0, (clipEnd(c) - t) / c.fade_out));
  return m;
}

export function visualItems(p, t) {
  const tracks = p.tracks.filter(tr => (tr.kind === 'video' || tr.kind === 'text') && !tr.hidden);
  const rev = [...tracks].reverse();
  const order = [...rev.filter(tr => tr.kind === 'video'), ...rev.filter(tr => tr.kind === 'text')];
  const byId = Object.fromEntries(p.clips.map(c => [c.id, c]));
  const items = [];
  for (const tr of order) {
    const clips = p.clips.filter(c => c.track === tr.id && c.enabled !== false);
    const ids = new Set(clips.map(c => c.id));
    let hit = null, covered = new Set();
    for (const x of p.transitions) {
      if (!ids.has(x.a) && !ids.has(x.b)) continue;
      const [w0, w1, a, b] = transWindow(x, byId);
      if (w0 <= t && t < w1) {
        hit = { kind: 'transition', x, a, b, progress: (t - w0) / Math.max(x.dur, 1e-6) };
        covered = new Set([a, b].filter(Boolean).map(c => c.id));
        break;
      }
    }
    if (hit) { items.push(hit); continue; }
    for (const c of clips) {
      if (covered.has(c.id)) continue;
      if (c.start <= t && t < clipEnd(c)) { items.push({ kind: 'clip', clip: c }); break; }
    }
  }
  return items;
}

export const projectDuration = p => Math.max(0, ...p.clips.map(clipEnd));

// ---------------------------------------------------------------- keyframes (MIRROR of timeline.py prop/…At)
export const ANIMATABLE = ['motion.x', 'motion.y', 'motion.scale', 'motion.rot', 'motion.opacity',
  'crop.l', 'crop.t', 'crop.r', 'crop.b', 'text.x', 'text.y', 'volume_db'];
export function getPath(o, path) { return path.split('.').reduce((a, k) => a?.[k], o); }

/** Value of an animatable property at timeline time t (keys are relative to clip start). */
export function prop(c, path, t) {
  const ks = c.keys?.[path];
  if (!ks || !ks.length) return getPath(c, path);
  const rel = t - c.start;
  if (rel <= ks[0].t) return ks[0].v;
  const last = ks[ks.length - 1];
  if (rel >= last.t) return last.v;
  let i = 0;
  while (i < ks.length - 2 && ks[i + 1].t <= rel) i++;
  const a = ks[i], b = ks[i + 1];
  let u = (rel - a.t) / Math.max(b.t - a.t, 1e-9);
  const e = a.e || 'linear';
  if (e === 'hold') return a.v;
  if (e === 'ease') u = u * u * (3 - 2 * u);
  else if (e === 'ease_in') u = u * u;
  else if (e === 'ease_out') u = 1 - (1 - u) * (1 - u);
  return a.v + (b.v - a.v) * u;
}
const MOTION_DEF = { x: 0, y: 0, scale: 1, rot: 0, opacity: 1 };
export function motionAt(c, t) {
  const m = { ...(c.motion || {}) };
  for (const [k, d] of Object.entries(MOTION_DEF)) m[k] = prop(c, `motion.${k}`, t) ?? d;
  return m;
}
export function cropAt(c, t) {
  const r = { ...(c.crop || {}) };
  for (const k of ['l', 't', 'r', 'b']) r[k] = prop(c, `crop.${k}`, t) ?? 0;
  return r;
}
export function textPosAt(c, t) { return { x: prop(c, 'text.x', t), y: prop(c, 'text.y', t) }; }

/** Project-wide watermark/logo as a still clip over every frame (null when off). Mirror of timeline.py brand_clip. */
export function brandClip(p) {
  const br = p.settings?.brand || {};
  if (!br.enabled || !br.asset) return null;
  return { id: '_brand', type: 'media', asset: br.asset, still: true, start: 0, dur: 1e9, in: 0, out: 0, speed: 1,
    crop: {}, color: {}, filters: [], keys: {}, fade_in: 0, fade_out: 0, motion: { fit: 'none' } };
}
/** Corner placement (mirror of timeline.py brand_motion). */
export function brandMotion(W, H, sw, sh, br) {
  const s = br.size * W / Math.max(sw, 1), dw = sw * s, dh = sh * s, m = br.margin * Math.min(W, H), pos = br.position || 'tr';
  const x = pos === 'center' ? 0 : (pos === 'tl' || pos === 'bl') ? -(W / 2 - m - dw / 2) : (W / 2 - m - dw / 2);
  const y = pos === 'center' ? 0 : (pos === 'tl' || pos === 'tr') ? -(H / 2 - m - dh / 2) : (H / 2 - m - dh / 2);
  return { x, y, scale: s, rot: 0, opacity: br.opacity ?? 1, fit: 'none' };
}
