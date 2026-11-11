// Live preview + commit helpers shared by the Inspector and the monitor gizmo.
// Animated properties (with keyframes) are keyed at the playhead instead of changing the static value (auto-key),
// exactly like op_set_props on the server.
import { S, set, fps } from './store.js';
import { op } from './api.js';
import { player } from './player.js';

function merge(dst, patch) {
  for (const [k, v] of Object.entries(patch)) {
    if (v && typeof v === 'object' && !Array.isArray(v) && dst[k] && typeof dst[k] === 'object') merge(dst[k], v);
    else dst[k] = JSON.parse(JSON.stringify(v));
  }
}
function setPath(o, path, v) {
  const ks = path.split('.');
  let x = o;
  for (const k of ks.slice(0, -1)) x = x[k] ??= {};
  x[ks[ks.length - 1]] = v;
}
function applyProps(c, values, t) {
  for (const [path, v] of Object.entries(values)) {
    const ks = c.keys?.[path];
    if (ks && ks.length) {
      const rel = Math.round((Math.round(t * fps()) / fps() - c.start) * 1e6) / 1e6;
      const hit = ks.find(k => Math.abs(k.t - rel) <= 0.5 / fps());
      if (hit) hit.v = v; else { ks.push({ t: rel, v, e: 'ease' }); ks.sort((a, b) => a.t - b.t); }
    } else setPath(c, path, v);
  }
}

/** Local-only deep-merge patch for instant preview (server response replaces it). */
export function livePatch(ids, patch) {
  const p = JSON.parse(JSON.stringify(S.project));
  for (const c of p.clips) if (ids.includes(c.id)) merge(c, patch);
  set({ project: p }); player.invalidate();
}
export const commitPatch = (ids, patch, label) => op('update', { ids, patch }, label);

/** {path: value} edits for animatable properties (motion.*, crop.*, text.x/y, volume_db). */
export function liveProps(ids, values) {
  const p = JSON.parse(JSON.stringify(S.project));
  for (const c of p.clips) if (ids.includes(c.id)) applyProps(c, values, S.t);
  set({ project: p }); player.invalidate();
}
export const commitProps = (ids, values, label) => op('set_props', { ids, values, t: S.t }, label);
