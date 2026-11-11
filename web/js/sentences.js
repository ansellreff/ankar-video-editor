// Sentence timing inside narration clips (server: app/tts/layout.py, placement.py, context.py).
// tts.segs = [{text, a, b}] where each sentence sits in the generated file; tts.layout = [{at, speed}] (null = as generated).
// A sentence plays on the timeline at  clip.start - clip.in + at  for  (b - a) / speed  seconds.
import { S, set, toast, fps, clipById } from './store.js';
import { api } from './api.js';
import { projectDuration } from './evaluate.js';
import { player } from './player.js';

export const STRETCH = [0.88, 1.12];
export const PAD = 0.15;                  // same margin as placement.PAD (don't talk right up to someone)

export const hasSentences = c => c?.type === 'tts' && (c.tts?.segs?.length || 0) > 0;
export const segLen = (s, speed = 1) => Math.max(0, s.b - s.a) / (speed || 1);

/** [{i, text, t0, t1, speed}] for every sentence (also hidden ones), in timeline seconds. */
export function sentenceTimes(c) {
  const segs = c.tts.segs, lay = c.tts.layout || segs.map(s => ({ at: s.a, speed: 1 }));
  const o = c.start - (c.in || 0);
  return segs.map((s, i) => ({ i, text: s.text, speed: lay[i].speed, t0: o + lay[i].at, t1: o + lay[i].at + segLen(s, lay[i].speed) }));
}

/** Move sentence i to start `t` (timeline). ripple = later sentences move by the same amount. Clamped between neighbours. */
export function moved(c, base, i, t, ripple) {
  const out = base.map(x => ({ ...x }));
  const len = out[i].t1 - out[i].t0;
  const prevEnd = i > 0 ? out[i - 1].t1 + 0.02 : 0;
  let lim = Infinity;
  if (!ripple && i + 1 < out.length) lim = out[i + 1].t0 - 0.02 - len;
  t = Math.max(prevEnd, Math.min(lim, t), 0);
  const dt = t - out[i].t0;
  for (let k = i; k < out.length; k++) {
    if (k > i && !ripple) break;
    out[k].t0 += dt; out[k].t1 += dt;
  }
  return out;
}

export const overlapsTalk = (sp, speech) => (speech || []).some(([a, b]) => a < sp.t1 && b > sp.t0);

// ---------------------------------------------------------------- what's in the video (cached per edit)
let ctxKey = '', ctxTimer = null, ctxBusy = false;
function contextKey(p) {
  const parts = p.clips.filter(c => c.type === 'media' || (c.type === 'text' && c.meta?.subtitle))
    .map(c => [c.id, c.track, c.start, c.dur, c.in, c.out, c.speed, c.enabled, c.volume_db, c.type === 'text' ? c.text?.content : 0].join(','));
  const tr = p.tracks.map(t => [t.id, t.mute, t.role, t.duck, t.hidden].join(','));
  return parts.join(';') + '|' + tr.join(';');
}
/** Keep S.narrCtx = {cuts, speech} up to date while the project has sentence-timed narration. */
export function watchContext() {
  const p = S.project;
  if (!p || !p.clips.some(hasSentences)) return;
  const key = contextKey(p);
  if (key === ctxKey) return;
  clearTimeout(ctxTimer);
  ctxTimer = setTimeout(async () => {
    if (ctxBusy) { ctxKey = ''; return watchContext(); }
    ctxBusy = true; ctxKey = key;
    try { set({ narrCtx: await api('/api/tts/context', { t0: 0, t1: projectDuration(S.project) + 5 }) }); }
    catch (e) { ctxKey = ''; console.warn('narration context', e); }
    finally { ctxBusy = false; }
  }, 700);
}

// ---------------------------------------------------------------- edits (one undoable step each)
export async function applyTimes(cid, times, label = 'Move Sentence') {
  try {
    const r = await api('/api/tts/layout', { clip: cid, starts: times.map(x => x.t0), speeds: times.map(x => x.speed), label });
    set({ project: r.project, history: r.history, sentPending: null });
  } catch (e) { set({ sentPending: null }); toast(e.message, 'error'); }
}
export async function resetTiming(cid) {
  try { const r = await api('/api/tts/layout', { clip: cid, reset: true }); set({ project: r.project, history: r.history, sent: null }); }
  catch (e) { toast(e.message, 'error'); }
}

let nudgeTimer = null;
/** Arrow keys on a selected sentence: shown at once, sent to the server after a short pause (one undo step). */
export function nudge(dir, frame) {
  const sel = S.sent; const c = sel && clipById(sel.clip);
  if (!c || !hasSentences(c)) return false;
  const base = S.sentPending?.clip === c.id ? S.sentPending.times : sentenceTimes(c);
  const step = frame ? 1 / fps() : 0.1;
  const times = moved(c, base, sel.i, base[sel.i].t0 + dir * step, false);
  set({ sentPending: { clip: c.id, times } });
  clearTimeout(nudgeTimer);
  nudgeTimer = setTimeout(() => applyTimes(c.id, S.sentPending.times, 'Nudge Sentence'), 350);
  return true;
}

export function playSentence(c, i) {
  const sp = sentenceTimes(c)[i];
  player.seek(Math.max(0, sp.t0 - 0.05));
  player.play();
  const stopAt = sp.t1 + 0.15;
  const iv = setInterval(() => { if (!S.playing) return clearInterval(iv); if (S.t >= stopAt) { player.pause(); clearInterval(iv); } }, 30);
}

export function sentenceMenu(e, c, i) {
  e.preventDefault(); e.stopPropagation();
  set({ sent: { clip: c.id, i }, sel: { clips: [c.id], transition: null, asset: null } });
  const times = sentenceTimes(c), sp = times[i], ctx = S.narrCtx || { cuts: [], speech: [] };
  const len = sp.t1 - sp.t0;
  const to = (t, label) => applyTimes(c.id, moved(c, times, i, t, false), label);
  const cut = ctx.cuts.length ? ctx.cuts.reduce((b, k) => Math.abs(k - sp.t0) < Math.abs(b - sp.t0) ? k : b) + 0.05 : null;
  const free = t => {                                        // first start >= t that doesn't talk over anyone
    const busy = ctx.speech.map(([a, b]) => [a - PAD, b + PAD]).sort((x, y) => x[0] - y[0]);
    for (let again = true; again;) { again = false; for (const [a, b] of busy) if (a < t + len && b > t) { t = b; again = true; } }
    return t;
  };
  const speed = v => applyTimes(c.id, times.map((x, k) => k === i ? { ...x, speed: v, t1: x.t0 + (x.t1 - x.t0) * x.speed / v } : x), 'Sentence Speed');
  set({ ctx: { x: e.clientX, y: e.clientY, items: [
    { label: `“${sp.text.length > 38 ? sp.text.slice(0, 36) + '…' : sp.text}”`, off: true },
    { label: 'Play this sentence', run: () => playSentence(c, i) },
    { sep: true },
    { label: 'Snap to nearest shot change', run: () => to(cut, 'Snap Sentence to Shot'), off: cut == null },
    { label: 'Move to next gap in the talking', run: () => to(free(sp.t0), 'Move Sentence to Gap'), off: !ctx.speech.length || free(sp.t0) === sp.t0 },
    { label: 'Move to playhead', run: () => to(S.t, 'Move Sentence') },
    { sep: true },
    ...[[0.9, 'Speed 0.9× (slower)'], [1, 'Speed 1× (as generated)'], [1.1, 'Speed 1.1× (faster)']].map(([v, l]) =>
      ({ label: (Math.abs(sp.speed - v) < 0.01 ? '✓ ' : '') + l, run: () => speed(v) })),
    { sep: true },
    { label: 'Reset this sentence', run: () => {
      const segs = c.tts.segs, o = c.start - (c.in || 0);
      const t0 = o + segs[i].a;
      applyTimes(c.id, moved(c, times.map((x, k) => k === i ? { ...x, speed: 1, t1: x.t0 + segLen(segs[i]) } : x), i, t0, false), 'Reset Sentence');
    } },
    { label: 'Reset all sentence timing', run: () => resetTiming(c.id) },
    { label: 'Match to video…', run: () => set({ dialog: 'match', matchClip: c.id }) },
  ] } });
}

/** Text for "Copy request for Claude" when narration doesn't fit. */
export function claudeRequest(c, rep) {
  const name = c.label || (c.tts.text || '').slice(0, 40);
  const r = rep.range;
  if (!rep.fits) return `In AnKar Video Editor, the narration "${name}" (clip ${c.id}) is ${rep.over.toFixed(1)} s too long for the video `
    + `from ${r[0].toFixed(1)} s to ${r[1].toFixed(1)} s${rep.speech?.length ? ' (avoiding the people talking)' : ''}. Please shorten it by about `
    + `${rep.words} words, keep the meaning and the tone, match what's on screen, and regenerate it.\nSentences:\n`
    + rep.sentences.map((s, k) => `${k + 1}. ${s}`).join('\n');
  return `In AnKar Video Editor, the narration "${name}" (clip ${c.id}) leaves ${rep.spare.toFixed(1)} s free in the video from ${r[0].toFixed(1)} s to `
    + `${r[1].toFixed(1)} s. Please make it about ${rep.add_words} words longer to match what's on screen, keep the tone, and regenerate it.\nSentences:\n`
    + rep.sentences.map((s, k) => `${k + 1}. ${s}`).join('\n');
}
