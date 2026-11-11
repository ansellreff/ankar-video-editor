// Every user command in one place: used by the menu bar, shortcuts, context menus and panels.
import { S, set, clipById, trackById, linkedIds, snapT, fps, toast } from './store.js';
import { op, batch, undo, redo, api, openFolder, rescan, projectAction } from './api.js';
// (op() resolves to the op's result — e.g. the new transition ids — and toasts errors itself)
import { player } from './player.js';
import { clipEnd, projectDuration } from './evaluate.js';
import { clamp } from './util.js';

const sel = () => S.sel.clips.filter(id => clipById(id));
export const selectClips = (ids, add = false) =>
  set({ sel: { clips: add ? [...new Set([...S.sel.clips, ...ids])] : ids, transition: null, asset: S.sel.asset } });

function textPreset(id) { return S.presets.text_presets.find(p => p.id === id) || S.presets.text_presets[0]; }

export const A = {
  undo, redo, rescan,
  save: () => projectAction('checkpoint', { label: '' }),
  open: target => openFolder(target),

  // ------------------------------------------------ projects
  openProject: tab => set({ dialog: 'projects', projectsTab: tab || 'open' }),
  newProject: () => set({ dialog: 'projects', projectsTab: 'new' }),
  saveAs: () => set({ dialog: 'projects', projectsTab: 'saveas' }),
  switchProject: name => projectAction('open', { name }).then(() => toast(`Opened “${name}”`, 'ok')),
  renameProject() {
    const n = prompt('Rename project', S.projectName);
    if (n && n !== S.projectName) projectAction('rename', { name: S.projectName, new: n }).then(() => toast(`Renamed to “${n}”`, 'ok'));
  },
  revert: file => { if (confirm('Go back to this checkpoint? (Undo can bring the current state back.)')) projectAction('revert', { file }); },

  // ------------------------------------------------ time tools
  speedDialog() {
    const c = sel().map(clipById).find(c => c && c.type === 'media' && !c.still && c.hold == null);
    if (!c) return toast('Select a video or audio clip first', 'error');
    set({ dialog: 'speed' });
  },
  setSpeed: args => op('set_speed', { ids: sel(), ...args }, 'Speed/Duration'),
  freeze(mode = 'insert', dur = 2) {
    const c = sel().map(clipById).find(c => c && c.type === 'media' && trackById(c.track)?.kind === 'video');
    return op('freeze_frame', { t: S.t, id: c?.id || null, dur, mode }, mode === 'insert' ? 'Insert Frame Hold' : 'Freeze Rest of Clip')
      .then(ids => ids && selectClips(ids));
  },
  matchFrame() {
    const c = clipById(sel()[0]);
    if (!c?.asset) return toast('Select a clip to find its source file');
    set({ sel: { ...S.sel, asset: c.asset } });
    setTimeout(() => document.querySelector('.asset.selected')?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 50);
  },
  splitAll() { op('split', { t: S.t, ids: null }, 'Add Edit to All Tracks'); },
  renameClip() {
    const c = clipById(sel()[0]); if (!c) return;
    const n = prompt('Clip name (shown on the timeline)', c.label || '');
    if (n != null) op('update', { ids: [c.id], patch: { label: n } }, 'Rename Clip');
  },
  colorLabel(label_color) { const ids = sel(); if (ids.length) op('update', { ids, patch: { label_color } }, 'Clip Color'); },
  trackHeight: (id, h) => op('set_track', { id, patch: { height: h } }, 'Track Height'),

  // ------------------------------------------------ transport
  play: () => player.toggle(),
  step: n => { player.pause(); player.seek(snapT(S.t + n / fps())); },
  goStart: () => player.seek(0),
  goEnd: () => player.seek(projectDuration(S.project)),
  jumpEdit(dir) {
    const edges = [...new Set(S.project.clips.flatMap(c => [c.start, clipEnd(c)]))].sort((a, b) => a - b);
    const t = dir > 0 ? edges.find(e => e > S.t + 1e-3) : [...edges].reverse().find(e => e < S.t - 1e-3);
    if (t != null) player.seek(t);
  },

  // ------------------------------------------------ editing
  split() {
    const ids = sel();
    op('split', { t: S.t, ids: ids.length ? ids : null }, 'Split');
  },
  del(ripple = false) {
    if (S.sel.transition) { op('remove_transition', { id: S.sel.transition }, 'Remove Transition'); set({ sel: { ...S.sel, transition: null } }); return; }
    const ids = sel();
    if (!ids.length) return;
    op('delete', { ids, ripple }, ripple ? 'Ripple Delete' : 'Delete');
    set({ sel: { ...S.sel, clips: [] } });
  },
  copy() {
    const ids = linkedIds(sel());
    if (!ids.length) return;
    set({ clipboard: JSON.parse(JSON.stringify(ids.map(clipById))) });
    toast(`Copied ${ids.length} clip${ids.length > 1 ? 's' : ''}`);
  },
  cut() { A.copy(); A.del(false); },
  paste() { if (S.clipboard) op('paste', { clips: S.clipboard, t: S.t }, 'Paste').then(ids => selectClips(ids)); },
  selectAll() { selectClips(S.project.clips.map(c => c.id)); },
  deselect() { set({ sel: { clips: [], transition: null, asset: null }, ctx: null }); },
  unlink() { const ids = sel(); if (ids.length) op('unlink', { ids }, 'Unlink'); },
  link() { const ids = sel(); if (ids.length > 1) op('link', { ids }, 'Link'); },
  toggleEnabled() {
    const ids = sel(); if (!ids.length) return;
    op('update', { ids, patch: { enabled: !(clipById(ids[0]).enabled !== false) } }, 'Enable/Disable');
  },
  speed(v) {
    const ids = sel().filter(id => clipById(id).type === 'media' && !clipById(id).still);
    if (ids.length) op('update', { ids, patch: { speed: v } }, `Speed ${Math.round(v * 100)}%`);
  },
  fades(d = 0.5) {
    const ids = sel(); if (ids.length) op('update', { ids, patch: { fade_in: d, fade_out: d } }, 'Add Fades');
  },
  resetMotion() {
    const ids = sel(); if (ids.length) op('update', { ids, patch: { motion: { x: 0, y: 0, scale: 1, rot: 0, opacity: 1, fit: 'fit' }, crop: { l: 0, t: 0, r: 0, b: 0 } } }, 'Reset Motion');
  },
  closeGap(track, t) { op('close_gap', { track, t }, 'Close Gap'); },

  // ------------------------------------------------ markers / in-out
  marker() { op('add_marker', { t: S.t, label: '' }, 'Add Marker'); },
  setIn() { set({ inPt: S.t, outPt: S.outPt != null && S.outPt <= S.t ? null : S.outPt }); },
  setOut() { set({ outPt: S.t, inPt: S.inPt != null && S.inPt >= S.t ? null : S.inPt }); },
  clearInOut() { set({ inPt: null, outPt: null }); },
  toggleLoop() { set({ loop: !S.loop }); },

  // ------------------------------------------------ view
  // zoom AROUND the playhead (it stays where it is on screen; if it was off screen it comes to the middle) — user:
  // "when I zoom out the timeline the cursor is gone"
  zoomTo(npps) {
    npps = clamp(npps, 2, 800);
    const el = document.querySelector('.tl-scroll');
    if (!el) return set({ pps: npps });
    const w = el.clientWidth, x = S.t * S.pps - el.scrollLeft;
    const sx = x >= 0 && x <= w ? x : w / 2;
    set({ pps: npps });
    requestAnimationFrame(() => { el.scrollLeft = Math.max(0, S.t * npps - sx); });
  },
  zoom(f) { A.zoomTo(S.pps * f); },
  // scroll the timeline so the playhead (the current-time line) is in the middle of the view
  goToPlayhead() {
    const el = document.querySelector('.tl-scroll');
    if (el) el.scrollTo({ left: Math.max(0, S.t * S.pps - el.clientWidth / 2), behavior: 'smooth' });
  },
  zoomFit() {
    const el = document.querySelector('.tl-scroll');
    const d = Math.max(5, projectDuration(S.project));
    if (el) set({ pps: clamp((el.clientWidth - 40) / d, 2, 800) });
  },
  tool: name => set({ tool: name }),
  toggleSnap: () => set({ snap: S.snap === false }),
  toggleSafe: () => set({ safe: !S.safe }),

  // ------------------------------------------------ tracks / sequence
  addTrack: kind => op('add_track', { kind }, `Add ${kind} track`),
  format: preset => op('set_format', { preset }, `Format ${preset}`),
  track: (id, patch, label = 'Track') => op('set_track', { id, patch }, label),

  // ------------------------------------------------ adding things
  addAsset(aid, start = S.t, track = null) {
    const a = S.assets[aid];
    if (!a) return;
    if (a.kind === 'subtitle') return api('/api/subtitles/import', { asset: aid, start }).then(r => { set({ project: r.project, history: r.history }); toast(`Imported ${r.lines} subtitle lines`, 'ok'); }).catch(e => toast(e.message, 'error'));
    if (a.kind === 'font') return toast('Fonts are used by text styles automatically');
    if (a.status !== 'ready' && a.kind !== 'image') toast('Still preparing this file — the preview appears when it is ready');
    return op('add_media', { asset: aid, start: snapT(start), ...(track ? { track } : {}) }, `Add ${a.name}`).then(ids => selectClips(ids));
  },
  addText(presetId = 'title', start = S.t, track = 'T1') {
    const p = textPreset(presetId);
    const d = p.defaults;
    return op('add_text', { track, start: snapT(start), dur: p.dur, content: d.content, preset: p.id, x: d.x, y: d.y, style: d.style, anim: d.anim }, `Add ${p.name}`)
      .then(ids => selectClips(ids));
  },
  applyFilter(type, ids = sel(), extra = {}, label = null) {
    const fd = S.presets.filters.find(f => f.id === type);
    const targets = ids.filter(id => { const c = clipById(id); return c && c.type === 'media' && trackById(c.track)?.kind === 'video'; });
    if (!targets.length) return toast('Select a video or image clip first (or drop the filter onto one)', 'error');
    const defaults = Object.fromEntries(Object.entries(fd.params).map(([k, v]) => [k, v.default]));
    return batch(targets.map(id => ({ op: 'update', args: { ids: [id], patch: { filters: [...(clipById(id).filters || []), { type, ...defaults, ...extra }] } } })), label || `Add ${fd.name}`);
  },
  /** Add a LUT (.cube in library/luts) to the selected clips; a clip that already has a LUT gets it swapped. */
  applyLut(file, ids = sel()) {
    const lut = (S.luts || []).find(l => l.file === file);
    const targets = ids.filter(id => { const c = clipById(id); return c && c.type === 'media' && trackById(c.track)?.kind === 'video'; });
    if (!targets.length) return toast('Select a video or image clip first (or drop the LUT onto one)', 'error');
    return batch(targets.map(id => {
      const fl = clipById(id).filters || [];
      const i = fl.findIndex(f => f.type === 'lut');
      const next = i >= 0 ? fl.map((f, j) => j === i ? { ...f, file } : f) : [...fl, { type: 'lut', amount: 1, file }];
      return { op: 'update', args: { ids: [id], patch: { filters: next } } };
    }), `LUT: ${lut?.name || file.split('/').pop()}`);
  },
  /** Look preset (color + LUT + filters) on the selected video clips — or on every clip of V1 when nothing is selected. */
  applyLook(look, ids = sel()) {
    const l = (S.presets.looks || []).find(x => x.id === look);
    const vids = ids.filter(id => { const c = clipById(id); return c && c.type === 'media' && trackById(c.track)?.kind === 'video'; });
    const args = vids.length ? { look, ids: vids } : { look, track: 'V1' };
    return op('apply_look', args, `Look: ${l?.name || look}`)
      .then(r => toast(`${l?.name || look} on ${r.length} clip${r.length === 1 ? '' : 's'}${vids.length ? '' : ' (all of V1)'}`, 'ok')).catch(() => {});
  },
  saveLook(clip) {
    const name = prompt('Name for this look (color + LUT + filters)', 'My look');
    if (!name) return;
    return api('/api/looks/save_preset', { clip, name }).then(r => { set(s => ({ presets: { ...s.presets, looks: r.looks }, fxTab: 'luts' })); toast(`Saved “${name}” under ★ My looks`, 'ok'); })
      .catch(e => toast(e.message, 'error'));
  },
  /** Transition pack on every cut: between the selected clips if 2+ are selected, otherwise the whole V1 track. */
  transitionPack(pack) {
    const ids = sel().filter(i => trackById(clipById(i)?.track)?.kind !== 'audio');
    const p = (S.presets.transition_packs || []).find(x => x.id === pack);
    return op('apply_transition_pack', ids.length >= 2 ? { pack, ids } : { pack, track: 'V1' }, `${p?.name || pack} transitions`)
      .then(r => toast(`${p?.name || pack}: ${r.length} transition${r.length === 1 ? '' : 's'} added`, 'ok')).catch(() => {});
  },
  refreshLuts: () => api('/api/luts').then(r => { set({ luts: r.luts }); toast(`${r.luts.length} LUTs`, 'ok'); }),
  /** Transition onto a clip edge. edge: 'start' | 'end' | 'auto' (nearest edge to the playhead). */
  applyTransition(type, clipId = sel()[0], edge = 'auto') {
    const td = S.presets.transitions.find(x => x.id === type);
    let c = clipById(clipId);
    if (!c) { // no selection: use the cut nearest the playhead on any video track
      const cand = S.project.clips.filter(k => trackById(k.track)?.kind === 'video')
        .flatMap(k => [{ c: k, edge: 'start', t: k.start }, { c: k, edge: 'end', t: clipEnd(k) }])
        .sort((a, b) => Math.abs(a.t - S.t) - Math.abs(b.t - S.t))[0];
      if (!cand) return toast('Add clips to the timeline first', 'error');
      c = cand.c; edge = cand.edge;
    }
    if (trackById(c.track)?.kind === 'audio') return toast('Transitions go on video or text clips. For audio use fades (Inspector ▸ Audio).', 'error');
    if (edge === 'auto') edge = Math.abs(S.t - c.start) < Math.abs(S.t - clipEnd(c)) ? 'start' : 'end';
    const half = 0.5 / fps();
    const same = S.project.clips.filter(k => k.track === c.track && k.id !== c.id);
    const args = { type, dur: td.default_dur, params: {} };
    if (edge === 'start') { const prev = same.find(k => Math.abs(clipEnd(k) - c.start) <= half); args.a = prev?.id || null; args.b = c.id; }
    else { const next = same.find(k => Math.abs(k.start - clipEnd(c)) <= half); args.a = c.id; args.b = next?.id || null; }
    return op('add_transition', args, `Add ${td.name}`);
  },
  typedIntro(opts) {
    return api('/api/generate/typed_intro', opts).then(r => { set({ project: r.project, history: r.history }); toast('Typed intro added (text on T1/T2, keyboard sound on A3)', 'ok'); })
      .catch(e => toast(e.message, 'error'));
  },
  transcribe() {
    const c = clipById(sel()[0]);
    if (!c || c.type !== 'media') return toast('Select a clip with speech first', 'error');
    toast('Transcribing… this can take a minute');
    return api('/api/subtitles/transcribe', { clip: c.id }).then(r => { set({ project: r.project, history: r.history }); toast(`Added ${r.lines} subtitle lines`, 'ok'); })
      .catch(e => toast(e.message, 'error'));
  },
  dialog: name => set({ dialog: name }),

  // ------------------------------------------------ auto captions
  autoCaptions: () => set({ dialog: 'captions' }),
  /** Apply a caption template to the selected captions/text clips, or to every caption when none is selected. */
  captionTemplate(id) {
    const ids = sel().filter(i => clipById(i)?.type === 'text');
    const all = !ids.length;
    if (all && !S.project.clips.some(c => c.text?.caption)) return toast('No captions yet — click Auto Captions first', 'error');
    const name = (S.presets.caption_templates.find(t => t.id === id) || {}).name || id;
    return op('restyle_captions', { ids: all ? 'all' : ids, template: id }, `Caption style: ${name}`)
      .then(() => toast(all ? `${name} applied to all captions` : `${name} applied to ${ids.length} clip(s)`, 'ok'));
  },
  saveCaptionPreset(clip, name) {
    return api('/api/captions/save_preset', { clip, name }).then(r => { set(s => ({ presets: { ...s.presets, caption_templates: r.templates } })); toast(`Saved “${name}” under ★ My presets`, 'ok'); })
      .catch(e => toast(e.message, 'error'));
  },

  // ------------------------------------------------ layouts (split screen, picture-in-picture)
  /** kind: full | split_lr | split_tb | left | right | top | bottom | pip_tl | pip_tr | pip_bl | pip_br */
  layout(kind, ids = sel()) {
    const p = S.project, W = p.format.w, H = p.format.h;
    const order = Object.fromEntries(p.tracks.map((t, i) => [t.id, i]));
    const vids = ids.map(clipById).filter(c => c && c.type === 'media' && trackById(c.track)?.kind === 'video')
      .sort((a, b) => order[b.track] - order[a.track]);              // bottom track (V1) first
    if (!vids.length) return toast('Select one or more video clips first (e.g. one on V1 and one on V2)', 'error');
    const half = (c, side) => {                                          // show the middle of the clip in one half of the frame
      const a = S.assets[c.asset]?.meta || {}; const sw = a.w || W, sh = a.h || H;
      const base = Math.max(W / sw, H / sh), dw = sw * base, dh = sh * base;
      const horiz = side === 'left' || side === 'right';
      const cx = Math.max(0, (1 - (horiz ? W / 2 : W) / dw) / 2), cy = Math.max(0, (1 - (horiz ? H : H / 2) / dh) / 2);
      return { motion: { fit: 'fill', scale: 1, rot: 0, x: side === 'left' ? -W / 4 : side === 'right' ? W / 4 : 0, y: side === 'top' ? -H / 4 : side === 'bottom' ? H / 4 : 0 },
               crop: { l: cx, r: cx, t: cy, b: cy } };
    };
    const pip = (corner) => {
      const s = 0.38, m = 0.045;
      return { motion: { fit: 'fit', scale: s, rot: 0, x: (corner.includes('l') ? -1 : 1) * (W / 2 - W * s / 2 - W * m), y: (corner.includes('t') ? -1 : 1) * (H / 2 - H * s / 2 - H * m) },
               crop: { l: 0, r: 0, t: 0, b: 0 } };
    };
    const full = { motion: { fit: 'fit', scale: 1, rot: 0, x: 0, y: 0 }, crop: { l: 0, r: 0, t: 0, b: 0 } };
    let patches;
    if (kind === 'split_lr') patches = vids.length > 1 ? [half(vids[0], 'left'), half(vids[1], 'right')] : [half(vids[0], 'left')];
    else if (kind === 'split_tb') patches = vids.length > 1 ? [half(vids[0], 'top'), half(vids[1], 'bottom')] : [half(vids[0], 'top')];
    else if (['left', 'right', 'top', 'bottom'].includes(kind)) patches = vids.map(c => half(c, kind));
    else if (kind.startsWith('pip_')) patches = vids.map((c, i) => i === vids.length - 1 ? pip(kind.slice(4)) : full);
    else patches = vids.map(() => full);
    return batch(vids.slice(0, patches.length).map((c, i) => ({ op: 'update', args: { ids: [c.id], patch: patches[i] } })), `Layout: ${kind.replace('_', ' ')}`);
  },

  animPreset(name, ids = sel()) {
    const targets = ids.filter(id => { const c = clipById(id); return c && trackById(c.track)?.kind !== 'audio'; });
    if (!targets.length) return toast('Select a video, image or text clip first', 'error');
    return op('apply_anim_preset', { ids: targets, name }, name === 'clear' ? 'Remove Keyframes' : 'Animation Preset');
  },

  // ------------------------------------------------ AI narration
  addNarration(start = S.t, dur = 4) {
    const voice = (S.voices || [])[0]?.name || null;
    return op('add_tts', { start: snapT(start), dur, text: '', voice, tone: 'neutral' }, 'Add Narration').then(ids => {
      selectClips(ids);
      setTimeout(() => window.dispatchEvent(new CustomEvent('vs-edit-narration')), 80);
      if (!voice) toast('Tip: create a voice in Effects ▸ AI Voice so narration sounds like you');
    });
  },
  generateNarration(ids = null) {
    return api('/api/tts/generate', ids ? { ids } : {}).then(r => {
      const sk = r.skipped || [];
      if (r.queued.length) toast(`Generating ${r.queued.length} narration line${r.queued.length > 1 ? 's' : ''}…`);
      else if (!sk.length) toast('All narration is already up to date');
      if (sk.length) {
        const fmt = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
        toast(`Skipped ${sk.length} narration clip${sk.length > 1 ? 's' : ''}: ${sk.map(s => `${fmt(s.start)} (${s.reason})`).join(', ')}`, 'error');
        if (sk.length === 1 || ids) { set({ sel: { clips: [sk[0].id], transition: null, asset: null } }); player.seek(sk[0].start + 0.01); }
      }
    }).catch(e => toast(e.message, 'error'));
  },
  speakersDialog(asset = null, clip = null) { A.voiceWizard(asset || (clip ? clipById(clip)?.asset : null)); },
  voiceWizard(asset = null, voice = null) { set({ wizardInit: { asset, voice }, dialog: 'wizard' }); },
  narrationMp3(clipId) {
    return api('/api/tts/mp3', { clip: clipId }).then(r => {
      const a = document.createElement('a'); a.href = r.url; a.download = r.name; document.body.appendChild(a); a.click(); a.remove();
      toast(`Saved ${r.mp3}`, 'ok');
    }).catch(e => toast(e.message, 'error'));
  },
  voiceSampleDialog(clipId, voice, asset) {
    const c = clipById(clipId || S.sel.clips[0]);
    const usable = c && c.type === 'media' && S.assets[c.asset]?.meta?.has_audio;
    set({ voiceSample: { clip: !asset && usable ? c.id : null, voice, asset }, dialog: 'voiceSample' });
  },

  // ------------------------------------------------ snapshot & voiceover
  snapshot() {
    return api('/api/snapshot', { t: S.t }).then(r => toast(`Saved frame: ${r.path}`, 'ok')).catch(e => toast(e.message, 'error'));
  },
  async recordVoiceover() {
    if (S.recording) { S.recording.stop?.(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } }); }
    catch (e) { return toast('Microphone not available: ' + e.message, 'error'); }
    const start = S.t;
    for (const n of [3, 2, 1]) { set({ recording: { count: n } }); await new Promise(r => setTimeout(r, 700)); }
    const rec = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '' });
    const chunks = [];
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    const t0 = performance.now();
    const tick = setInterval(() => set({ recording: { ...S.recording, count: 0, elapsed: (performance.now() - t0) / 1000 } }), 200);
    rec.onstop = async () => {
      clearInterval(tick); stream.getTracks().forEach(tr => tr.stop());
      set({ recording: null });
      if (S.playing) player.pause();
      const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
      try {
        const r = await fetch(`/api/record?start=${start}`, { method: 'POST', body: blob, headers: { 'Content-Type': blob.type } });
        const j = await r.json(); if (!r.ok) throw new Error(j.detail || j.error);
        set({ project: j.project, history: j.history });
        toast(`Voiceover saved to ${j.path} and placed on the Narration track`, 'ok');
      } catch (e) { toast('Recording failed: ' + e.message, 'error'); }
    };
    set({ recording: { count: 0, elapsed: 0, stop: () => rec.stop() } });
    rec.start(250);
    player.seek(start); player.play();
  },
};
