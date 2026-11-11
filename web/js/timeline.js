import { html, useRef, useState, useEffect, useLayoutEffect, useMemo } from '../vendor/preact-htm.js';
import { S, set, useStore, fps, snapT, clipById, trackById, linkedIds, toast } from './store.js';
import { op, batch } from './api.js';
import { A, selectClips } from './actions.js';
import { player, getWave } from './player.js';
import { clipDur, clipEnd, transWindow, projectDuration } from './evaluate.js';
import { Icon, tc, clamp } from './util.js';
import { hasSentences, sentenceTimes, moved as movedSentences, overlapsTalk, sentenceMenu, watchContext, applyTimes, resetTiming } from './sentences.js';

const TH = { video: 58, audio: 48, text: 34 };
const RULER = 28;
const SNAP_PX = 8;

// ---------------------------------------------------------------- helpers
function snapCandidates(exclude = new Set()) {
  const c = [0, S.t];
  for (const k of S.project.clips) if (!exclude.has(k.id)) c.push(k.start, clipEnd(k));
  for (const m of S.project.markers) c.push(m.t);
  if (S.inPt != null) c.push(S.inPt);
  if (S.outPt != null) c.push(S.outPt);
  return c;
}
function snapValue(t, cands) {
  if (S.snap === false) return { t, line: null };
  let best = null, bd = SNAP_PX / S.pps;
  for (const c of cands) { const d = Math.abs(c - t); if (d < bd) { bd = d; best = c; } }
  return best == null ? { t, line: null } : { t: best, line: best };
}
const HF = { s: 0.62, m: 1, l: 1.7 };
const CLIP_COLORS = { violet: '#7c5cff', rose: '#e0457b', orange: '#e8773a', green: '#2e9d5b', teal: '#1f8f9e', gray: '#5b6070' };
function laneLayout(tracks) {
  let y = 0;
  return tracks.map(t => { const h = Math.round(TH[t.kind] * (HF[t.height] || 1)); const r = { t, y, h }; y += h; return r; });
}

// ---------------------------------------------------------------- ruler
function Ruler({ width, scrollLeft, vw, onScrub }) {
  const ref = useRef();
  const pps = useStore(s => s.pps);
  const markers = useStore(s => s.project?.markers || []);
  const inPt = useStore(s => s.inPt), outPt = useStore(s => s.outPt);
  useLayoutEffect(() => {
    const c = ref.current; if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.ceil(vw * dpr); c.height = RULER * dpr; c.style.width = vw + 'px'; c.style.height = RULER + 'px';
    const ctx = c.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, vw, RULER);
    const steps = [1 / fps(), 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    const major = steps.find(s => s * pps >= 90) || 600;
    const minor = steps.slice().reverse().find(s => s * pps >= 9 && s < major) || major / 5;
    const t0 = scrollLeft / pps, t1 = (scrollLeft + vw) / pps;
    ctx.strokeStyle = '#3a3d45'; ctx.fillStyle = '#8b8f98'; ctx.font = '10px Cascadia Mono, Consolas, monospace';
    ctx.beginPath();
    for (let t = Math.floor(t0 / minor) * minor; t <= t1; t += minor) {
      const x = Math.round(t * pps - scrollLeft) + 0.5;
      const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
      ctx.moveTo(x, isMajor ? 12 : 20); ctx.lineTo(x, RULER);
      if (isMajor) ctx.fillText(tc(t, fps()).slice(major >= 1 ? 3 : 3, major >= 1 ? 8 : 11), x + 4, 11);
    }
    ctx.stroke();
  }, [pps, scrollLeft, vw]);
  return html`<div class="ruler" style=${`width:${width}px`} onPointerDown=${onScrub}>
    <canvas ref=${ref} style=${`left:${scrollLeft}px`} />
    ${inPt != null && outPt != null && html`<div class="inout" style=${`left:${inPt * pps}px;width:${(outPt - inPt) * pps}px`} />`}
    ${inPt != null && outPt == null && html`<div class="inout" style=${`left:${inPt * pps}px;width:2px;border-right:0`} />`}
    ${markers.map((m, i) => html`<div class=${`marker ${m.color === 'red' ? 'red' : ''}`} style=${`left:${m.t * pps}px;--lw:${Math.max(0, ((markers[i + 1]?.t ?? m.t + 60) - m.t) * pps - 14)}px`}
        title=${m.label || 'Marker (double-click to rename, right-click to remove)'}
        onPointerDown=${e => { e.stopPropagation(); player.seek(m.t); }}
        onDblClick=${() => { const l = prompt('Marker label', m.label || ''); if (l != null) op('update_marker', { id: m.id, patch: { label: l } }, 'Rename Marker'); }}
        onContextMenu=${e => { e.preventDefault(); op('remove_marker', { id: m.id }, 'Remove Marker'); }}>
      <i />${m.label && html`<span class="ml">${m.label}</span>`}</div>`)}
  </div>`;
}

function CornerTC() {
  const t = useStore(s => s.t);
  return html`<span>${tc(t, fps())}</span>`;
}

function Playhead({ height, scrollRef, vw }) {
  const t = useStore(s => s.t);
  const pps = useStore(s => s.pps);
  const playing = useStore(s => s.playing);
  useEffect(() => {
    const el = scrollRef.current; if (!el || !playing) return;
    const x = t * pps;
    if (x > el.scrollLeft + el.clientWidth - 60 || x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 120);
  }, [t, playing]);
  return html`<div class="playhead" style=${`left:${t * pps}px;height:${height}px`}><div class="knob" /></div>`;
}

// ---------------------------------------------------------------- clip visuals
function Filmstrip({ c, a, w, h, pps }) {
  const st = a?.derived?.strip;
  if (!st || w < 8) return null;
  const fh = h, fw = st.tw * fh / st.th;
  const n = Math.min(80, Math.ceil(w / fw));
  const step = w / n > fw ? w / n : fw;
  const items = [];
  for (let i = 0; i < n; i++) {
    const x = i * step;
    if (x > w) break;
    const src = c.still ? 0 : c.in + (x / pps) * (c.speed || 1);
    const idx = clamp(Math.floor(src / st.interval), 0, st.count - 1);
    items.push(html`<div style=${`width:${Math.min(step, w - x)}px;background-image:url(/files/cache/media/${a.id}/strip.jpg?v=${a.mtime});
      background-size:${st.count * fw}px ${fh}px;background-position:${-idx * fw}px 0`} />`);
  }
  return html`<div class="strip">${items}</div>`;
}
function Waveform({ c, w }) {
  const ref = useRef();
  const [, bump] = useState(0);
  const wave = getWave(c.asset, () => bump(x => x + 1));
  useLayoutEffect(() => {
    const cv = ref.current; if (!cv || !wave) return;
    const W = Math.max(1, Math.min(4096, Math.round(w))), H = 34;
    cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d'); ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = 'rgba(255,255,255,.75)';
    const dur = clipDur(c), sp = c.type === 'tts' ? 1 : (c.speed || 1), gain = 10 ** ((c.volume_db || 0) / 20);
    const base = c.in || 0, rev = !!c.reverse;
    for (let x = 0; x < W; x++) {
      const xx = rev ? W - 1 - x : x;
      const s0 = base + (xx / W) * dur * sp, s1 = base + ((xx + 1) / W) * dur * sp;
      let m = 0;
      for (let i = Math.floor(s0 * wave.rate); i <= Math.floor(s1 * wave.rate); i++) m = Math.max(m, wave.peaks[i] || 0);
      const hh = Math.max(1, Math.min(1, (m / 255) * gain) * H * 0.95);
      ctx.fillRect(x, (H - hh) / 2, 1, hh);
    }
  }, [wave, w, c.in, c.out, c.speed, c.volume_db]);
  return html`<canvas class="wave" ref=${ref} />`;
}

// ---------------------------------------------------------------- main
export function Timeline() {
  const project = useStore(s => s.project);
  const pps = useStore(s => s.pps);
  const sel = useStore(s => s.sel);
  const tool = useStore(s => s.tool);
  const snap = useStore(s => s.snap);
  const assets = useStore(s => s.assets);
  const narrCtx = useStore(s => s.narrCtx);
  const sent = useStore(s => s.sent);
  const sentPending = useStore(s => s.sentPending);
  const scroll = useRef(), heads = useRef();
  const [drag, setDrag] = useState(null);
  const dragRef = useRef(null);
  const [vw, setVw] = useState(800);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [dropLane, setDropLane] = useState(null);

  // view model (applies drag ghosts) — computed before any early return (hook order)
  const view = useMemo(() => {
    const m = new Map();
    if (!project) return m;
    const tracks = project.tracks;
    for (const c of project.clips) {
      let s = c.start, d = clipDur(c), tr = c.track, ghost = false;
      if (drag?.mode === 'move' && drag.moved && drag.ids.includes(c.id)) {
        s = Math.max(0, c.start + drag.dt); ghost = true;
        const kind = trackById(c.track).kind;
        if (drag.shift && kind === trackById(drag.primary.track).kind) {
          const same = tracks.filter(t => t.kind === kind).map(t => t.id);
          tr = same[clamp(same.indexOf(c.track) + drag.shift, 0, same.length - 1)];
        }
      }
      if ((drag?.mode === 'trim' || drag?.mode === 'rate') && drag.moved) {
        const p = clipById(drag.id);
        const aligned = drag.id === c.id || (c.link && c.link === p.link && (drag.edge === 'start' ? Math.abs(c.start - p.start) < 1e-3 : Math.abs(clipEnd(c) - clipEnd(p)) < 1e-3));
        if (aligned) { ghost = true; if (drag.edge === 'start') { d = clipEnd(c) - drag.t; s = drag.t; } else d = drag.t - c.start; }
      }
      let times = null;                                        // narration sentences (dragged / nudged ones shown at once)
      if (hasSentences(c)) {
        times = drag?.mode === 'sent' && drag.cid === c.id ? drag.times : sentPending?.clip === c.id ? sentPending.times : sentenceTimes(c);
        if ((drag?.mode === 'sent' && drag.cid === c.id) || sentPending?.clip === c.id) {   // the clip grows to keep moved sentences
          const base = sentenceTimes(c), vis = base.filter(x => x.t1 > c.start && x.t0 < clipEnd(c)).map(x => x.i);
          const v = times.filter(x => vis.includes(x.i));
          if (v.length) { const s2 = Math.min(s, ...v.map(x => x.t0)), e2 = Math.max(s + d, ...v.map(x => x.t1 + 0.12)); d = e2 - s2; s = s2; }
        }
      }
      (m.get(tr) || m.set(tr, []).get(tr)).push({ c, s, d, ghost, times });
    }
    return m;
  }, [project, drag, sentPending]);
  useEffect(() => { watchContext(); }, [project]);

  useEffect(() => {
    const ro = new ResizeObserver(() => setVw(scroll.current.clientWidth));
    ro.observe(scroll.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const el = scroll.current;
    const onWheel = e => {
      if (!(e.ctrlKey || e.altKey)) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const tAt = (e.clientX - r.left + el.scrollLeft) / S.pps;
      const npps = clamp(S.pps * (e.deltaY < 0 ? 1.18 : 1 / 1.18), 2, 800);
      set({ pps: npps });
      requestAnimationFrame(() => { el.scrollLeft = tAt * npps - (e.clientX - r.left); });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  if (!project) return html`<div class="panel timeline" />`;
  const tracks = project.tracks;
  const lanes = laneLayout(tracks);
  const lanesH = lanes.reduce((s, l) => s + l.h, 0);
  const total = projectDuration(project);
  const contentW = Math.max(vw, (total + 30) * pps);
  const xToT = clientX => { const r = scroll.current.getBoundingClientRect(); return Math.max(0, (clientX - r.left + scroll.current.scrollLeft) / S.pps); };
  const laneAt = clientY => {
    const r = scroll.current.getBoundingClientRect();
    const y = clientY - r.top + scroll.current.scrollTop - RULER;
    return lanes.find(l => y >= l.y && y < l.y + l.h) || (y < 0 ? lanes[0] : lanes[lanes.length - 1]);
  };

  // ---------------------------------------------------------------- drag engine
  // Edge auto-scroll (like Premiere): while dragging near / past the left or right edge, the timeline scrolls by
  // itself — faster the closer you are — and the dragged thing keeps following the pointer.
  const EDGE = 56;
  const begin = (d, e) => {
    d = { ...d, sx0: scroll.current.scrollLeft };
    dragRef.current = d; setDrag({ ...d });
    let last = e, raf = 0, alive = true;
    const move = ev => { last = ev; const nd = onMove(dragRef.current, ev); if (nd) { dragRef.current = nd; setDrag({ ...nd }); } };
    const tick = () => {
      if (!alive) return;
      const el = scroll.current, r = el.getBoundingClientRect();
      const x = last.clientX;
      let v = 0;
      if (x < r.left + EDGE) v = -Math.min(40, 4 + (r.left + EDGE - x) * 0.45);
      else if (x > r.right - EDGE) v = Math.min(40, 4 + (x - (r.right - EDGE)) * 0.45);
      if (v) {
        const before = el.scrollLeft;
        el.scrollLeft = Math.max(0, Math.min(el.scrollWidth - el.clientWidth, before + v));
        if (el.scrollLeft !== before) { const nd = onMove(dragRef.current, last); if (nd) { dragRef.current = nd; setDrag({ ...nd }); } }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const up = ev => {
      alive = false; cancelAnimationFrame(raf);
      window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
      onUp(dragRef.current, ev); dragRef.current = null; setDrag(null);
    };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };
  const onMove = (d, e) => {
    const dx = e.clientX - d.x0 + (scroll.current.scrollLeft - (d.sx0 ?? scroll.current.scrollLeft));   // + how far the view scrolled
    if (d.mode === 'scrub') { player.seek(snapT(xToT(e.clientX))); return d; }
    if (d.mode === 'move') {
      let dt = dx / S.pps;
      const moving = d.ids.map(clipById).filter(Boolean);
      const minStart = Math.min(...moving.map(c => c.start));
      dt = Math.max(dt, -minStart);
      let line = null;
      const cands = snapCandidates(new Set(d.ids));
      if (S.snap !== false) {
        let best = null, bd = SNAP_PX / S.pps;
        for (const c of moving) for (const edge of [c.start + dt, clipEnd(c) + dt])
          for (const k of cands) { const dd = Math.abs(k - edge); if (dd < bd) { bd = dd; best = { adj: k - edge, k }; } }
        if (best) { dt += best.adj; line = best.k; }
      }
      const lane = laneAt(e.clientY);
      const pk = trackById(d.primary.track).kind;
      let shift = 0, target = null;
      if (lane && lane.t.kind === pk) {
        const same = tracks.filter(t => t.kind === pk).map(t => t.id);
        shift = same.indexOf(lane.t.id) - same.indexOf(d.primary.track);
        target = lane.t.id;
      }
      return { ...d, dt, line, shift, target, moved: d.moved || Math.abs(dx) > 3 || shift !== 0 };
    }
    if (d.mode === 'trim') {
      const c = clipById(d.id);
      let t = d.t0 + dx / S.pps;
      const one = 1 / fps();
      const s = snapValue(t, snapCandidates(new Set(linkedIds([d.id]))));
      t = s.t;
      const a = S.project.assets[c.asset];
      if (d.edge === 'start') {
        t = Math.min(t, clipEnd(c) - one);
        if (c.type === 'media' && !c.still) t = Math.max(t, c.start - c.in / (c.speed || 1));
        t = Math.max(0, t);
      } else {
        t = Math.max(t, c.start + one);
        if (c.type === 'media' && !c.still && a?.dur) t = Math.min(t, c.start + (a.dur - c.in) / (c.speed || 1));
      }
      return { ...d, t, line: s.line, moved: d.moved || Math.abs(dx) > 2 };
    }
    if (d.mode === 'rate') {                         // rate stretch: the edge moves, the speed changes to fit
      const c = clipById(d.id);
      const one = 1 / fps();
      const s = snapValue(d.t0 + dx / S.pps, snapCandidates(new Set(linkedIds([d.id]))));
      const srcLen = c.out - c.in;
      let t = s.t;
      if (d.edge === 'start') t = clamp(t, clipEnd(c) - srcLen * 10, clipEnd(c) - Math.max(one, srcLen / 16));
      else t = clamp(t, c.start + Math.max(one, srcLen / 16), c.start + srcLen * 10);
      t = Math.max(0, t);
      return { ...d, t, line: s.line, moved: d.moved || Math.abs(dx) > 2 };
    }
    if (d.mode === 'sent') {                         // drag one sentence (Shift: it and every later one)
      const c = clipById(d.cid);
      let t = d.base[d.i].t0 + dx / S.pps, line = null;
      if (S.snap !== false) {                        // shot changes first, then playhead / markers / clip edges
        const cuts = (S.narrCtx?.cuts || []).map(k => k + 0.05);
        const others = [S.t, ...S.project.markers.map(m => m.t), ...S.project.clips.filter(k => k.track !== c.track).flatMap(k => [k.start, clipEnd(k)])];
        let best = null, bd = SNAP_PX / S.pps;
        for (const k of cuts) { const dd = Math.abs(k - t); if (dd < bd * 1.5) { bd = dd / 1.5; best = { t: k, line: k - 0.05 }; } }
        if (!best) for (const k of others) { const dd = Math.abs(k - t); if (dd < bd) { bd = dd; best = { t: k, line: k }; } }
        if (best) { t = best.t; line = best.line; }
      }
      const times = movedSentences(c, d.base, d.i, t, d.ripple);
      return { ...d, times, line, moved: d.moved || Math.abs(dx) > 2 };
    }
    if (d.mode === 'tdur') {
      const x = S.project.transitions.find(k => k.id === d.id);
      const k = x.a && x.b ? 2 : 1;
      const nd = Math.max(1 / fps(), d.dur0 + (d.side === 'r' ? 1 : -1) * k * dx / S.pps);
      return { ...d, dur: nd, moved: true };
    }
    if (d.mode === 'marquee') {
      const r = scroll.current.getBoundingClientRect();
      return { ...d, x1: e.clientX - r.left + scroll.current.scrollLeft, y1: e.clientY - r.top + scroll.current.scrollTop, moved: true };
    }
    return d;
  };
  const onUp = (d, e) => {
    if (!d) return;
    if (d.mode === 'move' && d.moved) {
      const trackChange = d.shift !== 0 ? d.target : null;
      if (Math.abs(d.dt) > 1e-6 || trackChange) op('move', { ids: d.ids, delta: d.dt, track: trackChange, ignore_link: d.alt }, 'Move');
    } else if (d.mode === 'trim' && d.moved) {
      op('trim', { id: d.id, edge: d.edge, t: d.t, ripple: d.alt, ignore_link: false }, d.alt ? 'Ripple Trim' : 'Trim');
    } else if (d.mode === 'rate' && d.moved) {
      const c = clipById(d.id);
      if (d.edge === 'end') op('set_speed', { ids: [d.id], duration: d.t - c.start, ripple: false }, 'Rate Stretch');
      else batch([{ op: 'set_speed', args: { ids: [d.id], duration: clipEnd(c) - d.t, ripple: false } },
                  { op: 'move', args: { ids: [d.id], delta: d.t - c.start } }], 'Rate Stretch');
    } else if (d.mode === 'sent') {
      if (d.moved) { set({ sentPending: { clip: d.cid, times: d.times } }); applyTimes(d.cid, d.times, d.ripple ? 'Move Sentences' : 'Move Sentence'); }
    } else if (d.mode === 'tdur' && d.moved) {
      op('update_transition', { id: d.id, patch: { dur: d.dur } }, 'Transition Duration');
    } else if (d.mode === 'marquee') {
      const x0 = Math.min(d.xs, d.x1 ?? d.xs) / S.pps, x1 = Math.max(d.xs, d.x1 ?? d.xs) / S.pps;
      const y0 = Math.min(d.ys, d.y1 ?? d.ys) - RULER, y1 = Math.max(d.ys, d.y1 ?? d.ys) - RULER;
      if (d.moved) {
        const hit = S.project.clips.filter(c => { const l = lanes.find(L => L.t.id === c.track); return l && c.start < x1 && clipEnd(c) > x0 && l.y < y1 && l.y + l.h > y0; }).map(c => c.id);
        selectClips(hit, d.add);
      }
    }
  };

  // ---------------------------------------------------------------- pointer handlers
  const onSentDown = (e, c, i) => {
    if (e.button !== 0 || S.tool === 'razor') return;
    e.stopPropagation();
    if (trackById(c.track).lock) return toast(`Track ${c.track} is locked`);
    set({ sent: { clip: c.id, i }, sel: { clips: [c.id], transition: null, asset: null } });
    begin({ mode: 'sent', x0: e.clientX, cid: c.id, i, base: sentenceTimes(c), times: sentenceTimes(c), ripple: e.shiftKey, moved: false }, e);
  };
  const onClipDown = (e, c) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    if (S.sent) set({ sent: null });
    if (trackById(c.track).lock) return toast(`Track ${c.track} is locked`);
    if (S.tool === 'razor') {
      const t = snapValue(snapT(xToT(e.clientX)), snapCandidates()).t;
      op('split', { t, ids: e.shiftKey ? null : [c.id] }, 'Razor');
      return;
    }
    const group = e.altKey ? [c.id] : linkedIds([c.id]);
    let ids;
    if (e.shiftKey || e.ctrlKey) {
      ids = S.sel.clips.includes(c.id) ? S.sel.clips.filter(i => !group.includes(i)) : [...new Set([...S.sel.clips, ...group])];
      selectClips(ids);
      if (!ids.includes(c.id)) return;
    } else {
      ids = S.sel.clips.includes(c.id) ? S.sel.clips : group;
      if (!S.sel.clips.includes(c.id)) selectClips(group);
    }
    begin({ mode: 'move', x0: e.clientX, ids, primary: c, alt: e.altKey, dt: 0, shift: 0, moved: false }, e);
  };
  const onEdgeDown = (e, c, edge) => {
    if (e.button !== 0 || S.tool === 'razor') return;
    e.stopPropagation();
    if (trackById(c.track).lock) return;
    if (!S.sel.clips.includes(c.id)) selectClips(e.altKey ? [c.id] : linkedIds([c.id]));
    if (S.tool === 'rate') {
      if (c.type !== 'media' || c.still || c.hold != null) return toast('Rate stretch works on video/audio clips (not stills, text or freeze frames)');
      const t0 = edge === 'start' ? c.start : clipEnd(c);
      return begin({ mode: 'rate', x0: e.clientX, id: c.id, edge, t0, t: t0, moved: false }, e);
    }
    begin({ mode: 'trim', x0: e.clientX, id: c.id, edge, t0: edge === 'start' ? c.start : clipEnd(c), t: edge === 'start' ? c.start : clipEnd(c), alt: e.altKey, moved: false }, e);
  };
  const onLaneDown = e => {
    if (e.button !== 0) return;
    const r = scroll.current.getBoundingClientRect();
    const xs = e.clientX - r.left + scroll.current.scrollLeft, ys = e.clientY - r.top + scroll.current.scrollTop;
    if (!e.shiftKey && !e.ctrlKey) set({ sel: { clips: [], transition: null, asset: null }, sent: null });
    begin({ mode: 'marquee', x0: e.clientX, xs, ys, add: e.shiftKey || e.ctrlKey, moved: false }, e);
  };
  const onScrub = e => { if (e.button !== 0) return; player.seek(snapT(xToT(e.clientX))); begin({ mode: 'scrub', x0: e.clientX }, e); };

  // ---------------------------------------------------------------- drag & drop from panels
  const onDragOver = (e, lane) => {
    if (!e.dataTransfer.types.includes('application/x-vlog')) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    if (dropLane !== lane.t.id) setDropLane(lane.t.id);
  };
  const onDrop = (e, lane) => {
    e.preventDefault(); setDropLane(null);
    const d = JSON.parse(e.dataTransfer.getData('application/x-vlog') || 'null');
    if (!d) return;
    const raw = xToT(e.clientX);
    const t = snapValue(snapT(raw), snapCandidates()).t;
    const tk = lane.t;
    const under = S.project.clips.find(c => c.track === tk.id && c.start <= raw && raw < clipEnd(c));
    if (d.kind === 'asset') {
      const a = S.assets[d.id];
      if (!a) return;
      let track = null;
      if (a.kind === 'video') track = tk.kind === 'text' ? 'V1' : tk.id;
      else if (a.kind === 'image') track = tk.kind === 'video' ? tk.id : 'V1';
      else if (a.kind === 'audio') track = tk.kind === 'audio' ? tk.id : null;
      A.addAsset(d.id, t, track);
    } else if (d.kind === 'text') A.addText(d.id, t, tk.kind === 'text' ? tk.id : 'T1');
    else if (d.kind === 'transition') {
      if (!under) return toast('Drop transitions onto a clip (near its start or end)', 'error');
      A.applyTransition(d.id, under.id, raw - under.start < clipEnd(under) - raw ? 'start' : 'end');
    } else if (d.kind === 'filter') {
      if (!under) return toast('Drop filters onto a video clip', 'error');
      A.applyFilter(d.id, [under.id]);
    } else if (d.kind === 'look') {
      if (!under) return toast('Drop looks onto a video clip', 'error');
      A.applyLook(d.id, S.sel.clips.includes(under.id) ? S.sel.clips : [under.id]);
    } else if (d.kind === 'lut') {
      if (!under) return toast('Drop LUTs onto a video clip', 'error');
      A.applyLut(d.id, S.sel.clips.includes(under.id) ? S.sel.clips : [under.id]);
    } else if (d.kind === 'layout') {
      if (!under) return toast('Drop layouts onto a video clip', 'error');
      A.layout(d.id, S.sel.clips.includes(under.id) ? S.sel.clips : [under.id]);
    } else if (d.kind === 'anim') {
      if (!under) return toast('Drop animation presets onto a clip', 'error');
      A.animPreset(d.id, [under.id]);
    } else if (d.kind === 'generator') { set({ introStart: t }); A.dialog('intro'); }
  };

  // ---------------------------------------------------------------- context menus
  const clipMenu = (e, c) => {
    e.preventDefault(); e.stopPropagation();
    if (!S.sel.clips.includes(c.id)) selectClips(linkedIds([c.id]));
    const isMedia = c.type === 'media' && !c.still;
    if (c.type === 'tts') return set({ ctx: { x: e.clientX, y: e.clientY, items: [
      { label: c.tts.file && !c.tts.stale ? 'Regenerate voice' : 'Generate voice', run: () => A.generateNarration([c.id]) },
      ...(c.tts.file ? [{ label: 'Download as MP3', run: () => A.narrationMp3(c.id) }] : []),
      { sep: true },
      { label: 'Match to video…', run: () => set({ dialog: 'match', matchClip: c.id }), off: !hasSentences(c) },
      ...(c.tts.layout ? [{ label: 'Reset sentence timing', run: () => resetTiming(c.id) }] : []),
      { sep: true },
      { label: 'Split at Playhead', kbd: 'Ctrl+K', run: A.split },
      { label: 'Copy', kbd: 'Ctrl+C', run: A.copy }, { label: 'Delete', kbd: 'Del', run: () => A.del(false) },
      { label: 'Rename…', run: A.renameClip },
    ] } });
    set({ ctx: { x: e.clientX, y: e.clientY, items: [
      { label: 'Split at Playhead', kbd: 'Ctrl+K', run: A.split },
      { label: 'Copy', kbd: 'Ctrl+C', run: A.copy }, { label: 'Cut', kbd: 'Ctrl+X', run: A.cut },
      { sep: true },
      { label: 'Delete', kbd: 'Del', run: () => A.del(false) }, { label: 'Ripple Delete', kbd: 'Shift+Del', run: () => A.del(true) },
      { sep: true },
      c.link ? { label: 'Unlink Audio/Video', run: A.unlink } : { label: 'Link with selection', run: A.link },
      { label: c.enabled === false ? 'Enable' : 'Disable', run: A.toggleEnabled },
      ...(isMedia && c.hold == null ? [{ label: 'Speed / Duration…', kbd: 'Ctrl+R', run: A.speedDialog },
        { label: c.reverse ? 'Play forwards' : 'Reverse', run: () => op('set_speed', { ids: [c.id], reverse: !c.reverse }, 'Reverse') }] : []),
      ...(isMedia && trackById(c.track).kind === 'video' ? [{ label: 'Insert Frame Hold (2 s)', kbd: 'Shift+F', run: () => A.freeze('insert', 2) },
        { label: 'Freeze Rest of Clip', run: () => A.freeze('rest') }] : []),
      { sep: true },
      ...(trackById(c.track).kind !== 'audio' ? [
        { label: 'Cross Dissolve at start', run: () => A.applyTransition('cross_dissolve', c.id, 'start') },
        { label: 'Cross Dissolve at end', run: () => A.applyTransition('cross_dissolve', c.id, 'end') }] : []),
      { label: 'Add Fade In & Out', run: () => A.fades(0.5) },
      ...(isMedia ? [{ label: 'Transcribe → English subtitles', run: A.transcribe },
        { label: 'Clone a voice from this clip…', run: () => A.voiceWizard(c.asset) },
        { label: 'Use as voice sample…', run: () => A.voiceSampleDialog?.(c.id) }] : []),
      { sep: true },
      { label: 'Rename…', run: A.renameClip },
      { label: 'Color label', run: () => set({ ctx: { x: e.clientX, y: e.clientY, items: [
        ...Object.keys(CLIP_COLORS).map(k => ({ label: `● ${k}`, run: () => A.colorLabel(k) })), { label: 'Default', run: () => A.colorLabel(null) }] } }) },
      { label: 'Show source in Project', kbd: 'F', run: A.matchFrame, off: !c.asset },
    ] } });
  };
  const laneMenu = (e, lane) => {
    e.preventDefault();
    const t = snapT(xToT(e.clientX));
    set({ ctx: { x: e.clientX, y: e.clientY, items: [
      { label: 'Paste here', run: () => S.clipboard && op('paste', { clips: S.clipboard, t }, 'Paste'), off: !S.clipboard },
      { label: 'Close gap here (ripple)', run: () => A.closeGap(lane.t.id, t) },
      { label: 'Add Title here', run: () => A.addText('title', t, lane.t.kind === 'text' ? lane.t.id : 'T1') },
      ...(lane.t.kind === 'audio' ? [{ label: 'Add AI narration here', run: () => A.addNarration(t) }] : []),
      { label: 'Add Marker here', run: () => op('add_marker', { t }, 'Add Marker') },
    ] } });
  };

  const byId = Object.fromEntries(project.clips.map(c => [c.id, c]));

  const marquee = drag?.mode === 'marquee' && drag.moved ? {
    left: Math.min(drag.xs, drag.x1), top: Math.min(drag.ys, drag.y1), width: Math.abs(drag.x1 - drag.xs), height: Math.abs(drag.y1 - drag.ys) } : null;

  return html`<div class=${`panel timeline ${tool === 'razor' ? 'tl-razor' : ''} ${tool === 'rate' ? 'tl-rate' : ''}`}>
    <div class="tl-toolbar">
      <span class="panel-title" style="margin-right:6px">Timeline</span>
      <button class=${`btn ghost icon ${tool === 'select' ? 'on' : ''}`} title="Selection tool (V)" onClick=${() => A.tool('select')}><${Icon} n="pointer" s=${15} /></button>
      <button class=${`btn ghost icon ${tool === 'razor' ? 'on' : ''}`} title="Razor tool (C) — click a clip to cut it" onClick=${() => A.tool('razor')}><${Icon} n="razor" s=${15} /></button>
      <button class=${`btn ghost icon ${tool === 'rate' ? 'on' : ''}`} title="Rate Stretch tool (R) — drag a clip edge to speed it up / slow it down to fit" onClick=${() => A.tool('rate')}><${Icon} n="gauge" s=${15} /></button>
      <button class="btn ghost icon" title="Insert 2 s freeze frame at the playhead (Shift+F)" onClick=${() => A.freeze('insert', 2)}><${Icon} n="snow" s=${15} /></button>
      <button class=${`btn ghost icon ${snap !== false ? 'on' : ''}`} title="Snapping (S)" onClick=${A.toggleSnap}><${Icon} n="magnet" s=${15} /></button>
      <div class="sep" />
      <button class="btn ghost icon" title="Split at playhead (Ctrl+K)" onClick=${A.split}><${Icon} n="razor" s=${14} /></button>
      <button class="btn ghost icon" title="Add marker (M)" onClick=${A.marker}><${Icon} n="flag" s=${14} /></button>
      <button class="btn ghost icon" title="Delete selection (Del)" onClick=${() => A.del(false)}><${Icon} n="trash" s=${14} /></button>
      <div class="sep" />
      <span class="hint">${sel.clips.length ? `${sel.clips.length} selected` : 'Drag clips here · Alt = ignore link / ripple trim'}</span>
      <span style="flex:1" />
      <button class="btn ghost icon" title="Zoom out (-)" onClick=${() => A.zoom(1 / 1.4)}><${Icon} n="minus" s=${14} /></button>
      <input class="zoom" type="range" min="0" max="1" step="0.001" value=${Math.log(pps / 2) / Math.log(400)} style=${`--fill:${Math.log(pps / 2) / Math.log(400) * 100}%`}
        onInput=${e => A.zoomTo(2 * Math.pow(400, +e.target.value))} title="Zoom" />
      <button class="btn ghost icon" title="Zoom in (=)" onClick=${() => A.zoom(1.4)}><${Icon} n="plus" s=${14} /></button>
      <button class="btn ghost icon" title="Zoom to fit (\\)" onClick=${A.zoomFit}><${Icon} n="fit" s=${14} /></button>
      <button class="btn ghost icon" title="Go to playhead (P): scroll the timeline to the current time" onClick=${A.goToPlayhead}><${Icon} n="locate" s=${14} /></button>
    </div>
    <div class="tl-main">
      <div class="tl-heads" ref=${heads}>
        <div class="tl-heads-inner" style=${`transform:translateY(-${scrollTop}px)`}>
          <div class="tl-corner"><${CornerTC} /></div>
          ${lanes.map(({ t, h }) => html`<div class=${`track-head ${t.kind}`} style=${`height:${h}px`}>
            <span class="tid" title="Click: track height (small / medium / large)" style="cursor:pointer"
              onClick=${() => A.trackHeight(t.id, { s: 'm', m: 'l', l: 's' }[t.height || 'm'])}>${t.id}</span>
            <span class="tname" title="Double-click to rename" onDblClick=${() => { const n = prompt('Track name', t.name); if (n) A.track(t.id, { name: n }, 'Rename Track'); }}>${t.name}${t.duck ? html` <span class="hint" title="Ducks under dialogue">duck</span>` : ''}</span>
            ${t.kind !== 'audio' && html`<button class=${`tbtn ${t.hidden ? 'on' : ''}`} title="Show / hide" onClick=${() => A.track(t.id, { hidden: !t.hidden }, 'Toggle Track')}><${Icon} n=${t.hidden ? 'eyeoff' : 'eye'} s=${13} /></button>`}
            ${t.kind === 'audio' && html`<button class=${`tbtn mute ${t.mute ? 'on' : ''}`} title="Mute" onClick=${() => A.track(t.id, { mute: !t.mute }, 'Mute Track')}>M</button>
              <button class=${`tbtn ${t.solo ? 'on' : ''}`} title="Solo" onClick=${() => A.track(t.id, { solo: !t.solo }, 'Solo Track')}>S</button>`}
            <button class=${`tbtn ${t.lock ? 'on' : ''}`} title="Lock" onClick=${() => A.track(t.id, { lock: !t.lock }, 'Lock Track')}><${Icon} n=${t.lock ? 'lock' : 'unlock'} s=${13} /></button>
          </div>`)}
        </div>
      </div>
      <div class="tl-scroll" ref=${scroll} onScroll=${e => { setScrollLeft(e.target.scrollLeft); setScrollTop(e.target.scrollTop); }}>
        <div class="tl-content" style=${`width:${contentW}px;height:${RULER + lanesH + 40}px`}>
          <${Ruler} width=${contentW} scrollLeft=${scrollLeft} vw=${vw} onScrub=${onScrub} />
          ${lanes.map(lane => {
            const t = lane.t;
            const items = view.get(t.id) || [];
            const trans = project.transitions.filter(x => byId[x.a]?.track === t.id || byId[x.b]?.track === t.id);
            return html`<div class=${`lane ${t.kind} ${dropLane === t.id ? 'drop' : ''} ${t.lock ? 'locked' : ''}`} style=${`height:${lane.h}px`}
                onPointerDown=${onLaneDown} onContextMenu=${e => laneMenu(e, lane)}
                onDragOver=${e => onDragOver(e, lane)} onDragLeave=${() => setDropLane(null)} onDrop=${e => onDrop(e, lane)}>
              ${t.role === 'narration' && narrCtx && items.some(x => x.times) && html`<div class="talkband">
                ${narrCtx.speech.map(([a, b]) => html`<i class="talk" style=${`left:${a * pps}px;width:${Math.max(1, (b - a) * pps)}px`} title="Someone talks in the video here" />`)}
                ${narrCtx.cuts.map(k => html`<i class="cutmark" style=${`left:${k * pps}px`} title="Shot change" />`)}</div>`}
              ${items.map(({ c, s, d, ghost, times }) => {
                const a = assets[c.asset];
                const missing = c.type === 'media' && !a;
                const w = Math.max(2, d * pps);
                const kind = t.kind;
                const name = c.label || (c.type === 'text' ? c.text.content.replace(/\n/g, ' · ')
                  : c.type === 'tts' ? `🗣 ${c.tts?.text || 'Narration'}` : (a?.name || project.assets[c.asset]?.path?.split('/').pop() || 'missing'));
                const hasFx = (c.filters?.length || Object.keys(c.color || {}).length) > 0;
                const keyTimes = [...new Set(Object.values(c.keys || {}).flat().map(k => k.t))];
                const tint = CLIP_COLORS[c.label_color || ''];
                return html`<div key=${c.id} class=${`clip ${kind} ${c.type === 'tts' ? 'tts' : ''} ${sel.clips.includes(c.id) ? 'selected' : ''} ${ghost ? 'ghost' : ''} ${c.enabled === false ? 'disabled' : ''} ${missing ? 'missing' : ''}`}
                    style=${`left:${s * pps}px;width:${w}px${tint ? `;background:${tint}` : ''}`} title=${`${name}\n${tc(c.start, fps())} → ${tc(clipEnd(c), fps())}`}
                    onPointerDown=${e => onClipDown(e, c)} onContextMenu=${e => clipMenu(e, c)}
                    onDragOver=${e => onDragOver(e, lane)} onDrop=${e => { e.stopPropagation(); onDrop(e, lane); }}>
                  ${kind === 'video' && !missing && html`<${Filmstrip} c=${c} a=${a} w=${w} h=${lane.h - 22} pps=${pps} />`}
                  ${kind === 'audio' && !missing && c.asset && html`<${Waveform} c=${c} w=${w} />`}
                  ${c.type === 'tts' && w > 50 && !times && html`<div class="ttext" style="top:17px">${c.tts.tone}${c.tts.voice ? ` · ${c.tts.voice}` : ''}</div>`}
                  ${times && html`<div class="tsegs">${times.map(sp => {
                    const sw = (sp.t1 - sp.t0) * pps;
                    const on = sent?.clip === c.id && sent.i === sp.i;
                    const talk = overlapsTalk(sp, narrCtx?.speech);
                    return html`<div key=${sp.i} class=${`tseg ${on ? 'on' : ''} ${talk ? 'talkover' : ''} ${Math.abs(sp.speed - 1) > 0.01 ? 'sped' : ''}`}
                        style=${`left:${(sp.t0 - s) * pps}px;width:${Math.max(3, sw)}px`}
                        title=${`${sp.text}\n${tc(sp.t0, fps())} → ${tc(sp.t1, fps())}${Math.abs(sp.speed - 1) > 0.01 ? ` · ${sp.speed.toFixed(2)}×` : ''}${talk ? '\n⚠ talks over someone in the video' : ''}\nDrag to move · Shift+drag moves the rest too · ←/→ nudge · right-click for more`}
                        onPointerDown=${e => onSentDown(e, c, sp.i)} onContextMenu=${e => sentenceMenu(e, c, sp.i)}
                        onDblClick=${e => { e.stopPropagation(); player.seek(sp.t0); }}>
                      ${sw > 26 ? sp.text : ''}</div>`;
                  })}</div>`}
                  ${c.type === 'text' && w > 40 && html`<div class="ttext">${c.text.caption ? (c.text.caption.template || '').replace(/_/g, ' ') : c.text.anim.in !== 'none' ? `${c.text.anim.in.replace('_', ' ')} in` : ''}</div>`}
                  <div class="cname">${c.meta?.review?.length && !c.meta.review_ok ? html`<span class="chk" title=${`Please check: ${c.meta.review.join(' · ')}`}>?</span>` : ''}${hasFx && html`<span class="fxdot" title="Has color/filters" />`}${c.link && html`<${Icon} n="link" s=${10} />`}
                    ${c.hold != null && html`<span title="Freeze frame"><${Icon} n="snow" s=${11} /></span>`}
                    <span style="overflow:hidden;text-overflow:ellipsis">${missing ? '⚠ missing: ' : ''}${name}</span>
                    ${c.reverse ? html`<span class="speed" title="Reversed">◀◀</span>` : ''}
                    ${c.speed && c.speed !== 1 && c.hold == null ? html`<span class="speed">${Math.round(c.speed * 100)}%</span>` : ''}
                    ${c.type === 'tts' && S.ttsJobs[c.id]?.state === 'running' ? html`<span class="speed">generating…</span>` : ''}
                    ${c.type === 'tts' && !c.tts?.file && S.ttsJobs[c.id]?.state !== 'running' ? html`<span class="speed" title="Not generated yet">needs voice</span>` : ''}</div>
                  ${keyTimes.length > 0 && html`<div class="keys">${keyTimes.map(kt => html`<i style=${`left:${kt * pps}px`} title="Keyframe — click to jump"
                    onPointerDown=${e => { e.stopPropagation(); player.seek(c.start + kt); }} />`)}</div>`}
                  ${c.fade_in > 0 && html`<div class="fade in" style=${`width:${c.fade_in * pps}px`} />`}
                  ${c.fade_out > 0 && html`<div class="fade out" style=${`width:${c.fade_out * pps}px`} />`}
                  <div class="edge l" onPointerDown=${e => onEdgeDown(e, c, 'start')} />
                  <div class="edge r" onPointerDown=${e => onEdgeDown(e, c, 'end')} />
                </div>`;
              })}
              ${trans.map(x => {
                const dd = drag?.mode === 'tdur' && drag.id === x.id ? { ...x, dur: drag.dur } : x;
                const [w0, w1] = transWindow(dd, byId);
                const td = S.presets.transitions.find(k => k.id === x.type);
                return html`<div key=${x.id} class=${`trans ${sel.transition === x.id ? 'selected' : ''}`} style=${`left:${w0 * pps}px;width:${Math.max(6, (w1 - w0) * pps)}px`}
                    title=${`${td?.name || x.type} · ${x.dur.toFixed(2)} s — drag the ends to change duration`}
                    onPointerDown=${e => { e.stopPropagation(); set({ sel: { clips: [], transition: x.id, asset: null } }); }}
                    onContextMenu=${e => { e.preventDefault(); e.stopPropagation(); set({ sel: { clips: [], transition: x.id, asset: null }, ctx: { x: e.clientX, y: e.clientY, items: [{ label: 'Remove transition', run: () => A.del() }] } }); }}>
                  ${(w1 - w0) * pps > 40 ? (td?.name || '').split(' ')[0] : ''}
                  <div class="h l" onPointerDown=${e => { e.stopPropagation(); begin({ mode: 'tdur', x0: e.clientX, id: x.id, side: 'l', dur0: x.dur, dur: x.dur }, e); }} />
                  <div class="h r" onPointerDown=${e => { e.stopPropagation(); begin({ mode: 'tdur', x0: e.clientX, id: x.id, side: 'r', dur0: x.dur, dur: x.dur }, e); }} />
                </div>`;
              })}
            </div>`;
          })}
          <${Playhead} height=${RULER + lanesH} scrollRef=${scroll} vw=${vw} />
          ${drag?.line != null && html`<div class="snapline" style=${`left:${drag.line * pps}px;height:${RULER + lanesH}px`} />`}
          ${marquee && html`<div class="marquee" style=${`left:${marquee.left}px;top:${marquee.top}px;width:${marquee.width}px;height:${marquee.height}px`} />`}
        </div>
      </div>
    </div>
  </div>`;
}
