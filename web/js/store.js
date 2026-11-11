// Tiny global store + Preact hook. Server is the source of truth for `project`; UI-only state lives here.
import { useState, useEffect, useRef } from '../vendor/preact-htm.js';

export const S = {
  project: null, history: {}, assets: {}, presets: null, exports: [], packs: {},
  sel: { clips: [], transition: null, asset: null },
  t: 0, playing: false, pps: 60, scrollX: 0, tool: 'select', inPt: null, outPt: null,
  clipboard: null, exportJob: null, toasts: [], connected: false, dialog: null, ctx: null,
  safe: true, loop: false, volume: 1, previewFrame: 0,
  projectName: '', projectPath: '', projects: [], checkpoints: [], voices: [], ttsJobs: {}, task: null,
  monZoom: 'fit', recording: null,
};

const listeners = new Set();
let queued = false;
export function set(patch) {
  Object.assign(S, typeof patch === 'function' ? patch(S) : patch);
  if (!queued) { queued = true; queueMicrotask(() => { queued = false; listeners.forEach(f => f()); }); }
}
export function subscribe(f) { listeners.add(f); return () => listeners.delete(f); }

function same(a, b) {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => x === b[i]);
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(k => a[k] === b[k]);
  }
  return false;
}

export function useStore(sel) {
  const [, force] = useState(0);
  const selRef = useRef(sel); selRef.current = sel;
  const val = sel(S);
  const last = useRef(val); last.current = val;
  useEffect(() => subscribe(() => { if (!same(selRef.current(S), last.current)) force(x => x + 1); }), []);
  return val;
}

// ---------------------------------------------------------------- helpers over the project
export const fps = () => { const [n, d] = (S.project?.format.fps || '30000/1001').split('/').map(Number); return n / (d || 1); };
export const snapT = t => Math.round(t * fps()) / fps();
export const clipById = id => S.project?.clips.find(c => c.id === id);
export const trackById = id => S.project?.tracks.find(t => t.id === id);
export const assetOf = c => c && c.asset ? S.assets[c.asset] : null;
export function linkedIds(ids) {
  const out = [...ids]; const groups = new Set(ids.map(i => clipById(i)?.link).filter(Boolean));
  for (const c of S.project.clips) if (groups.has(c.link) && !out.includes(c.id)) out.push(c.id);
  return out;
}

let toastId = 0;
export function toast(text, kind = 'info', detail = '') {
  const id = ++toastId;
  set(s => ({ toasts: [...s.toasts, { id, text, kind, detail }] }));
  setTimeout(() => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), kind === 'error' ? 7000 : 4200);
}
