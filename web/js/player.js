// Playback engine: media pool synced to a master clock, Web Audio mix, WebGL frames.
import { S, set, subscribe, fps } from './store.js';
import { Gfx, layerQuad, textQuad } from './gfx.js';
import { visualItems, srcTime, clipEnd, clipDur, fadeMult, projectDuration, motionAt, cropAt, textPosAt, prop, brandClip, brandMotion } from './evaluate.js';
import { animState, renderText } from './textlayer.js';
import { captionStateKey } from './captionlayer.js';
import { buildChain, fxActive } from './voicefx.js';

// ---------------------------------------------------------------- shared waveform cache
const waves = new Map();
export function getWave(aid, onReady) {
  const w = waves.get(aid);
  if (w && w.peaks) return w;
  if (!w) {
    const entry = { peaks: null, cbs: [] };
    waves.set(aid, entry);
    fetch(`/files/cache/media/${aid}/wave.json`).then(r => r.ok ? r.json() : null).then(j => {
      if (!j) { waves.delete(aid); return; }
      entry.peaks = j.peaks; entry.rate = j.rate; entry.cbs.forEach(f => f(entry)); entry.cbs = [];
    }).catch(() => waves.delete(aid));
  }
  if (onReady) waves.get(aid)?.cbs.push(onReady);
  return null;
}

export function mediaUrl(asset) {
  if (!asset) return null;
  if (asset.kind === 'video') return asset.derived?.proxy ? `/files/cache/media/${asset.id}/proxy.mp4` : null;
  return `/files/${asset.path.split('/').map(encodeURIComponent).join('/')}`;
}

class Player {
  constructor() {
    this.pool = new Map();
    this.textCache = new Map();
    this.dirty = true;
    this.t0 = 0; this.p0 = 0;
    this.actx = null; this.master = null;
    this.lastProject = null; this.lastT = -1;
  }

  async attach(canvas) {
    this.canvas = canvas;
    this.gfx = new Gfx(canvas);
    // canvas text never triggers webfont loading by itself: load every weight up front, redraw text when fonts arrive
    for (const f of S.presets.fonts) {                   // register every preset font (caption templates use several families)
      try { document.fonts.add(new FontFace(f.family, `url("/files/${f.file}")`, { weight: String(f.weight) })); } catch (e) { /* ignore */ }
    }
    const fontsReady = Promise.all(S.presets.fonts.map(f => document.fonts.load(`${f.weight} 64px "${f.family}"`).catch(() => null)));
    document.fonts.addEventListener('loadingdone', () => { this.textCache.clear(); this.dirty = true; });
    await Promise.all([this.gfx.load(S.presets), fontsReady]);
    this.textCache.clear();
    subscribe(() => {
      if (S.project !== this.lastProject) { this.lastProject = S.project; this.dirty = true; }
      if (!S.playing && S.t !== this.lastT) { this.lastT = S.t; this.dirty = true; }
    });
    const tick = () => {
      try { this.frame(); }
      catch (e) { if (!this.lastErr || Date.now() - this.lastErr > 5000) { console.error('preview frame failed', e); this.lastErr = Date.now(); } this.dirty = true; }
      requestAnimationFrame(tick);                       // never let one bad frame stop the preview
    };
    requestAnimationFrame(tick);
  }
  invalidate() { this.dirty = true; }

  // ---------------------------------------------------------------- transport
  play() {
    if (!S.project) return;
    this._audio();
    const end = this.endTime();
    let t = S.t;
    if (t >= end - 1e-3) t = S.loop && S.inPt != null ? S.inPt : 0;
    this.t0 = t; this.p0 = performance.now();
    set({ playing: true, t });
  }
  pause() { set({ playing: false }); for (const m of this.pool.values()) if (!m.el.paused && m.el.pause) m.el.pause(); this.dirty = true; }
  toggle() { S.playing ? this.pause() : this.play(); }
  seek(t) {
    t = Math.max(0, t);
    if (S.playing) { this.t0 = t; this.p0 = performance.now(); }
    set({ t });
  }
  endTime() {
    if (S.loop && S.outPt != null) return S.outPt;
    return projectDuration(S.project);
  }
  _audio() {
    if (this.actx) { if (this.actx.state === 'suspended') this.actx.resume(); return; }
    this.actx = new AudioContext();
    this.master = this.actx.createGain();
    this.master.connect(this.actx.destination);
    for (const m of this.pool.values()) this._connect(m);
  }
  _connect(m) {
    if (!this.actx || m.node || m.kind !== 'a') return;
    m.node = this.actx.createMediaElementSource(m.el);
    m.gain = this.actx.createGain();
    m.node.connect(m.gain).connect(this.master);
    m.fxKey = 'null';
  }
  /** (Re)build the clip's voice effects between its source and gain (Filter · Noise · Space · Distance · Pan). */
  _wireFx(m, c) {
    const key = JSON.stringify(c.voice_fx || null);
    if (!m.node || m.fxKey === key) return;
    m.fxKey = key;
    try { m.node.disconnect(); } catch (e) { /* ignore */ }
    m.fx?.dispose(); m.fx = null;
    if (fxActive(c.voice_fx)) {
      m.fx = buildChain(this.actx, c.voice_fx, () => { m.bedWanted = true; });
      m.node.connect(m.fx.input); m.fx.output.connect(m.gain);
    } else m.node.connect(m.gain);
  }

  // ---------------------------------------------------------------- media pool
  _ensure(c, role) {
    const key = c.id + role;
    const a = S.assets[c.asset];
    let url = mediaUrl(a), reversed = false;
    if (c.reverse && a?.kind === 'video' && url) {        // smooth reverse preview via a reversed proxy (built on demand)
      const rk = `${a.id}_${c.in.toFixed(3)}_${c.out.toFixed(3)}`;
      const ru = S.revProxies?.[rk];
      if (ru) { url = ru; reversed = true; }
      else if (!this.revAsked?.has(rk)) {
        (this.revAsked ||= new Set()).add(rk);
        fetch('/api/reverse_proxy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ asset: a.id, in: c.in, out: c.out }) })
          .then(r => r.json()).then(j => { if (j.ready) set(s => ({ revProxies: { ...(s.revProxies || {}), [rk]: j.url } })); }).catch(() => {});
      }
    }
    let m = this.pool.get(key);
    if (m && m.url === url) return m;
    if (m) this._drop(key);
    if (!url) return null;
    let el;
    if (a.kind === 'image') { el = new Image(); el.src = url; el.onload = () => (this.dirty = true); }
    else {
      el = document.createElement(role === 'v' ? 'video' : 'audio');
      el.preload = 'auto'; el.src = url; el.playsInline = true;
      el.muted = role === 'v';
      el.preservesPitch = false;
      el.addEventListener('seeked', () => (this.dirty = true));
      el.addEventListener('loadeddata', () => (this.dirty = true));
    }
    m = { el, url, kind: role, image: a.kind === 'image', clip: c.id, reversed };
    this.pool.set(key, m);
    this._connect(m);
    return m;
  }
  _drop(key) {
    const m = this.pool.get(key);
    if (!m) return;
    try { m.el.pause?.(); m.el.removeAttribute('src'); m.el.load?.(); } catch (e) { /* ignore */ }
    m.fx?.dispose(); m.node?.disconnect(); m.gain?.disconnect();
    this.gfx?.dropTexture(key);
    this.pool.delete(key);
  }
  _drive(m, c, t, playing) {
    if (m.image) return;
    const a = S.assets[c.asset];
    const sf = a?.meta?.fps || 30;
    // aim a quarter-frame inside the frame (exact boundaries can round down to the previous frame) — same as the export
    const want = c.type === 'tts' ? srcTime(c, t) : Math.min(srcTime(c, t, sf) + 0.25 / sf, c.out - 0.5 / sf);
    const el = m.el;
    if (el.readyState < 1) return;
    // freeze frames, and reversed clips without a reversed proxy, are driven frame by frame (seek, never play)
    const stepped = c.hold != null || (c.reverse && !m.reversed);
    if (m.reversed) {                                     // reversed proxy: file time runs forward
      const fwd = (c.out - c.in) - (want - c.in);
      if (playing) {
        el.playbackRate = c.speed || 1;
        if (el.paused) { el.currentTime = fwd; el.play().catch(() => {}); }
        else if (Math.abs(el.currentTime - fwd) > 0.25) el.currentTime = fwd;
      } else { if (!el.paused) el.pause(); if (!el.seeking && Math.abs(el.currentTime - fwd) > 0.5 / fps()) el.currentTime = fwd; }
      return;
    }
    if (stepped) {
      if (!el.paused) el.pause();
      if (!el.seeking && Math.abs(el.currentTime - want) > 0.5 / sf) el.currentTime = want;
      return;
    }
    el.preservesPitch = c.keep_pitch !== false;
    if (playing) {
      el.playbackRate = c.speed || 1;
      if (el.paused) { el.currentTime = want; el.play().catch(() => {}); }
      else if (Math.abs(el.currentTime - want) > 0.25) el.currentTime = want;
    } else {
      if (!el.paused) el.pause();
      if (!el.seeking && Math.abs(el.currentTime - want) > 0.5 / fps()) el.currentTime = want;
    }
  }

  // ---------------------------------------------------------------- per frame
  frame() {
    const p = S.project;
    if (!p || !this.gfx) return;
    let t = S.t;
    if (S.playing) {
      t = this.t0 + (performance.now() - this.p0) / 1000;
      const end = this.endTime();
      if (t >= end) {
        if (S.loop && S.inPt != null) { t = S.inPt; this.t0 = t; this.p0 = performance.now(); }
        else { t = end; this.pause(); }
      }
      set({ t });
    }
    const items = visualItems(p, t);
    const needed = new Set();
    // visual media
    for (const it of items) {
      for (const c of it.kind === 'clip' ? [it.clip] : [it.a, it.b]) {
        if (!c || c.type !== 'media') continue;
        const m = this._ensure(c, 'v');
        if (m) { needed.add(c.id + 'v'); this._drive(m, c, t, S.playing); }
      }
    }
    const bc = brandClip(p);                                // project-wide watermark / logo
    if (bc && S.assets[bc.asset] && this._ensure(bc, 'v')) needed.add('_brandv');
    // audio clips
    const aTracks = Object.fromEntries(p.tracks.filter(x => x.kind === 'audio').map(x => [x.id, x]));
    const solo = Object.values(aTracks).some(x => x.solo);
    const dlgLevel = this._dialogueLevel(p, t);
    for (const c of p.clips) {
      if (!aTracks[c.track] || (c.type !== 'media' && c.type !== 'tts') || !c.asset || c.enabled === false) continue;
      const active = c.start <= t && t < clipEnd(c);
      const soon = c.start > t && c.start - t < 2;
      if (!active && !soon) continue;
      const m = this._ensure(c, 'a');
      if (!m) continue;
      needed.add(c.id + 'a');
      if (!active && m.fx?.bed?.playing) m.fx.bed.stop();
      if (active) {
        this._drive(m, c, t, S.playing);
        this._wireFx(m, c);
        const bed = m.fx?.bed;                                // noise bed follows playback, aligned to the clip time
        if (bed) {
          const want = t - c.start;
          if (S.playing && (!bed.playing || Math.abs(bed.position() - want) > 0.25)) bed.start(want);
          else if (!S.playing && bed.playing) bed.stop();
        }
        if (m.gain) {
          const tr = aTracks[c.track];
          let g = 10 ** (((prop(c, 'volume_db', t) || 0) + (tr.volume_db || 0)) / 20) * fadeMult(c, t);
          if (tr.mute || (solo && !tr.solo) || (c.reverse && !m.reversed)) g = 0;
          if (tr.duck && dlgLevel) g *= 10 ** ((p.settings?.duck_db ?? -12) / 20);
          m.gain.gain.setTargetAtTime(g * S.volume, this.actx.currentTime, 0.04);
        }
      } else if (!m.el.paused) { m.el.pause(); m.fx?.bed?.stop(); }
      else if (Math.abs(m.el.currentTime - c.in) > 0.05 && !m.el.seeking && m.el.readyState >= 1) m.el.currentTime = c.in;
    }
    // pre-roll the next visual clips so cuts are instant
    for (const c of p.clips) {
      if (c.type === 'media' && c.start > t && c.start - t < 1.5 && (p.tracks.find(x => x.id === c.track)?.kind === 'video')) {
        const m = this._ensure(c, 'v');
        if (m) { needed.add(c.id + 'v'); if (!S.playing || m.el.paused) this._drive(m, c, c.start, false); }
      }
    }
    for (const [k, m] of this.pool) {
      if (!needed.has(k)) { if (!m.image && !m.el.paused) m.el.pause(); if (this.pool.size > 14) this._drop(k); }
    }
    this.visibleKeys = items.flatMap(it => it.kind === 'clip' ? [it.clip] : [it.a, it.b]).filter(c => c && c.type === 'media').map(c => c.id + 'v');
    if (needed.has('_brandv')) this.visibleKeys.push('_brandv');
    if (S.playing || this.dirty) { this.lutPending = false; this.draw(items, t); this.dirty = false; }
  }

  /** True when every visible layer has its frame loaded and drawn (used by snapshots/tests). */
  settled() {
    if (this.dirty || S.playing || this.lutPending) return false;
    for (const k of this.visibleKeys || []) {
      const m = this.pool.get(k);
      if (!m) return false;
      if (m.image ? !m.el.complete : (m.el.readyState < 2 || m.el.seeking)) return false;
    }
    return true;
  }

  _dialogueLevel(p, t) {
    const speech = new Set(p.tracks.filter(x => x.role === 'dialogue' || x.role === 'narration').map(x => x.id));
    for (const c of p.clips) {
      if (!speech.has(c.track) || !(c.start <= t && t < clipEnd(c)) || !c.asset) continue;
      const w = getWave(c.asset);
      if (!w) continue;
      const i = Math.floor(srcTime(c, t) * w.rate);
      if ((w.peaks[i] || 0) > 255 * Math.sqrt(10 ** (-40 / 20))) return true;
    }
    return false;
  }

  draw(items, t) {
    const g = this.gfx, p = S.project;
    const W = p.format.w, H = p.format.h, RW = this.canvas.width, RH = this.canvas.height;
    const pres = S.presets;
    const trById = Object.fromEntries(pres.transitions.map(x => [x.id, x]));
    const flById = Object.fromEntries(pres.filters.map(x => [x.id, x]));
    g.clear(null, 0, 0, 0, 1);
    const drawLayer = (c, target) => {
      const m = motionAt(c, t);
      const op = (m.opacity ?? 1) * fadeMult(c, t);
      if (c.type === 'text') {
        let tc = this.textCache.get(c.id);
        if (!tc) { tc = { canvas: document.createElement('canvas'), key: null }; this.textCache.set(c.id, tc); }
        const pos = textPosAt(c, t);
        const cc = { ...c, text: { ...c.text, x: pos.x, y: pos.y } };
        const st = animState(cc, t);
        const capKey = cc.text.caption ? captionStateKey(cc, t) : '';
        const key = `${RW}x${RH}|${JSON.stringify(cc.text)}|${st.chars}|${st.scale.toFixed(3)}|${st.dy.toFixed(4)}|${W}x${H}|${capKey}`;
        if (tc.key !== key) {
          tc.canvas.width = RW; tc.canvas.height = RH;
          tc.res = renderText(tc.canvas, cc, t, W, H);
          tc.key = key;
          if (tc.res) g.upload(c.id + 't', tc.canvas, true);
        }
        if (!tc.res) return;
        const tex = g.texs.get(c.id + 't');
        if (tex) g.draw(tex, target, textQuad(W, H, [pos.x * W, pos.y * H], m), op * st.alpha);
        return;
      }
      const src = this.pool.get(c.id + 'v');
      if (!src) return;
      const el = src.el;
      let sw, sh, tex;
      if (src.image) { if (!el.complete || !el.naturalWidth) return; sw = el.naturalWidth; sh = el.naturalHeight; }
      else { sw = el.videoWidth; sh = el.videoHeight; }
      if (!sw) return;
      if (src.image || el.readyState >= 2) tex = g.upload(c.id + 'v', el, !!src.image);   // stills premultiplied: transparent PNGs
      else tex = g.texs.get(c.id + 'v');
      if (!tex) return;
      const colorDef = pres.color.params;
      const col = Object.fromEntries(Object.entries(colorDef).map(([k, d]) => [k, c.color?.[k] ?? d.default]));
      const passes = [];
      if (Object.keys(col).some(k => Math.abs(col[k] - colorDef[k].default) > 1e-6)) passes.push([pres.color.shader, col]);
      for (const f of c.filters || []) {
        const fd = flById[f.type];
        if (!fd || f.enabled === false) continue;
        let lut = null;
        if (fd.lut) {                                      // .cube → 3D texture (async; redraw when it arrives)
          if (!f.file) continue;
          lut = g.lutTexture(f.file, () => { this.dirty = true; });
          if (!lut) { this.lutPending = true; continue; }
        }
        passes.push([fd.shader, Object.fromEntries(Object.entries(fd.params).map(([k, d]) => [k, f[k] ?? d.default])), lut]);
      }
      passes.forEach(([shader, vals, lut], i) => { tex = g.filterPass(tex, sw, sh, shader, vals, t, 'f' + (i % 2), lut); });
      g.draw(tex, target, layerQuad(W, H, sw, sh, m, cropAt(c, t)), op);
    };
    for (const it of items) {
      if (it.kind === 'clip') { drawLayer(it.clip, null); continue; }
      const fa = g.fbo(RW, RH, 'la'), fb = g.fbo(RW, RH, 'lb');
      g.clear(fa); g.clear(fb);
      if (it.a) drawLayer(it.a, fa);
      if (it.b) drawLayer(it.b, fb);
      const td = trById[it.x.type] || trById.cross_dissolve;
      const vals = { ...td.params, ...Object.fromEntries(Object.entries(it.x.params || {}).filter(([k]) => k in td.params)) };
      const res = g.transitionPass(fa.tex, fb.tex, RW, RH, td.shader, vals, it.progress, t);
      g.draw(res, null);
    }
    const bc = brandClip(p);                                // watermark / logo over everything (mirror of compositor)
    const bm = bc && this.pool.get('_brandv');
    if (bm?.image && bm.el.complete && bm.el.naturalWidth) {
      bc.motion = brandMotion(W, H, bm.el.naturalWidth, bm.el.naturalHeight, p.settings.brand);
      drawLayer(bc, null);
    }
    set({ previewFrame: S.previewFrame + 1 });
  }
}

export const player = new Player();
