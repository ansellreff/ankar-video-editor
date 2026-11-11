// Captions tab: Auto Captions, animated template gallery, "needs checking" review list, editable caption lines.
import { html, useState, useEffect, useRef } from '../vendor/preact-htm.js';
import { S, set, useStore, fps, clipById, toast } from './store.js';
import { op, batch, api } from './api.js';
import { A } from './actions.js';
import { player } from './player.js';
import { Icon, tc } from './util.js';
import { renderCaption } from './captionlayer.js';

const LANG = { en: 'EN', id: 'ID', zh: 'ZH', ms: 'MS', ja: 'JA', ko: 'KO' };
export const isSub = c => c.type === 'text' && (c.text.caption || c.text.preset === 'subtitle' || c.meta?.lang);
const wrapped = s => /^\(.*\)$/s.test(s.trim());
const needsCheck = c => c.meta?.review?.length && !c.meta?.review_ok;

// ---------------------------------------------------------------- animated template previews (one shared loop)
const SAMPLE = [['Having', 0, 0.35], ['fun', 0.35, 0.7], ['in', 0.7, 0.85], ['Taiwan!', 0.85, 1.6]];
const tiles = new Set();
let loopOn = false;
function loop() {
  if (!tiles.size) { loopOn = false; return; }
  const now = performance.now() / 1000;
  for (const t of tiles) t.draw(now);
  setTimeout(() => requestAnimationFrame(loop), 1000 / 20);
}
function sampleClip(tpl) {
  const { id, name, desc, anim, y, max_words, max_chars, user, ...style } = tpl;
  style.size = (style.size || 64) * 1.9;                 // tiles are landscape: enlarge so the look reads at thumbnail size
  style.width = 0.94;
  return { id: 'tpl_' + id, start: 0, dur: 2.4, text: { content: '', x: 0.5, y: 0.5, anim: anim || { in: 'none', in_dur: 0, out: 'none', out_dur: 0 },
    caption: { template: id, style, words: SAMPLE.map(([w, t0, t1]) => ({ w, t0, t1, emph: w === 'Taiwan!' })) } } };
}

export function TemplateTile({ tpl, on, onClick }) {
  const ref = useRef();
  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const c = sampleClip(tpl);
    let last = '';
    const t = { draw(now) {
      const tt = (now % 2.6);
      const k = `${Math.floor(tt * 20)}`;
      if (k === last) return; last = k;
      const r = renderCaption(cv, c, tt, 480, 270);
      cv.style.opacity = r ? r.alpha : 0;
    } };
    tiles.add(t);
    if (!loopOn) { loopOn = true; requestAnimationFrame(loop); }
    return () => tiles.delete(t);
  }, [JSON.stringify(tpl)]);
  return html`<button class=${`cap-tile ${on ? 'on' : ''}`} title=${tpl.desc || tpl.name} onClick=${onClick}>
    <canvas ref=${ref} width="320" height="180" />
    <span class="lbl">${tpl.user ? '★ ' : ''}${tpl.name}</span>
  </button>`;
}

export function TemplateGallery({ value, onPick }) {
  const tpls = useStore(s => s.presets?.caption_templates || []);
  const mine = tpls.filter(t => t.user), builtIn = tpls.filter(t => !t.user);
  return html`<div>
    ${mine.length > 0 && html`<div class="fx-group">★ My presets</div>
      <div class="cap-grid">${mine.map(t => html`<${TemplateTile} tpl=${t} on=${value === t.id} onClick=${() => onPick(t.id)} />`)}</div>`}
    ${mine.length > 0 && html`<div class="fx-group">Templates</div>`}
    <div class="cap-grid">${builtIn.map(t => html`<${TemplateTile} tpl=${t} on=${value === t.id} onClick=${() => onPick(t.id)} />`)}</div>
  </div>`;
}

// ---------------------------------------------------------------- review list
function listen(t, d) {
  player.seek(Math.max(0, t - 0.2)); player.play();
  setTimeout(() => player.pause(), (d + 0.5) * 1000);
}
const select = id => set({ sel: { clips: [id], transition: null, asset: null } });

function ReviewList({ caps, unclear }) {
  const n = caps.length + unclear.length;
  if (!n) return null;
  return html`<div class="review">
    <div class="review-head"><${Icon} n="alert" s=${14} /> Needs checking (${n})
      <span class="hint" style="margin-left:auto">Listen, fix the text, then ✓</span></div>
    ${unclear.map(m => html`<div class="review-row">
      <button class="sub-t" onClick=${() => player.seek(m.t)}>${tc(m.t, fps()).slice(3)}</button>
      <span class="why">Speech heard, no words recognised${m.dur ? ` (${m.dur.toFixed(1)} s)` : ''}</span>
      <button class="btn ghost icon small" title="Listen" onClick=${() => listen(m.t, m.dur || 1.5)}><${Icon} n="play" s=${12} /></button>
      <button class="btn ghost small" title="Add a caption here and type what is said"
        onClick=${() => op('add_captions', { captions_: [{ start: m.t, end: m.t + Math.max(1, m.dur || 1.5), words: [{ w: 'Type', t0: 0, t1: 0.5 }, { w: 'here', t0: 0.5, t1: Math.max(1, m.dur || 1.5) }] }],
          template: S.project.clips.find(c => c.text?.caption)?.text.caption.template || 'karaoke_line' }, 'Add caption')
          .then(ids => { op('set_review', { ids: [m.id] }, 'Resolve unclear speech'); select(ids[0]); setTimeout(() => window.dispatchEvent(new Event('vs-edit-text')), 200); })}>+ Caption</button>
      <button class="btn ghost icon small" title="Nothing to caption — dismiss" onClick=${() => op('set_review', { ids: [m.id] }, 'Dismiss')}>✓</button>
    </div>`)}
    ${caps.map(c => html`<div class="review-row">
      <button class="sub-t" onClick=${() => { player.seek(c.start + 0.01); select(c.id); }}>${tc(c.start, fps()).slice(3)}</button>
      <div style="display:grid;gap:3px;min-width:0;flex:1">
        <span class="why">${c.meta.review.join(' · ')}${c.meta.original ? html` — <i>“${c.meta.original}”</i>` : ''}</span>
        <input class="input" value=${c.text.content} onFocus=${() => select(c.id)}
          onChange=${e => op('update', { ids: [c.id], patch: { text: { content: e.target.value } } }, 'Edit Caption')} />
      </div>
      <button class="btn ghost icon small" title="Listen" onClick=${() => listen(c.start, c.dur)}><${Icon} n="play" s=${12} /></button>
      <button class="btn ghost icon small" title="Checked — looks right" onClick=${() => op('set_review', { ids: [c.id] }, 'Caption checked')}>✓</button>
    </div>`)}
  </div>`;
}

// ---------------------------------------------------------------- panel
export function CaptionsPanel() {
  const project = useStore(s => s.project);
  const sel = useStore(s => s.sel);
  const [gloss, setGloss] = useState(null);
  const [wpl, setWpl] = useState(null);
  const subs = project.clips.filter(isSub).sort((a, b) => a.start - b.start);
  const caps = subs.filter(c => c.text.caption);
  const glossary = project.settings.glossary || [];
  const selCap = sel.clips.map(clipById).find(c => c?.text?.caption);
  const current = selCap?.text.caption.template || caps[0]?.text.caption.template;
  const unclear = project.markers.filter(m => m.kind === 'unclear');
  const toggleParen = c => {
    const t = c.text.content.trim();
    const next = wrapped(t) ? t.slice(1, -1).trim() : `(${t})`;
    op('update', { ids: [c.id], patch: { text: { content: next }, meta: { ...(c.meta || {}), translated: !wrapped(t) } } }, 'Toggle translated');
  };
  const shiftAll = d => batch(subs.map(c => ({ op: 'move', args: { ids: [c.id], delta: d, ignore_link: true } })), `Shift captions ${d > 0 ? '+' : ''}${d}s`);
  const words = wpl ?? (caps.length ? Math.max(...caps.slice(0, 20).map(c => c.text.caption.words.length)) : 5);
  return html`<div style="display:grid;gap:10px;padding:8px 10px 12px">
    <button class="btn primary big" onClick=${A.autoCaptions}><${Icon} n="cc" s=${16} /> Auto Captions…</button>
    <div class="hint">Pick a clip (or the whole Dialogue track) and the app writes word-timed captions in the style you choose.
      Indonesian / Mandarin is translated to English in ( ). Unclear words are listed below for you to check.</div>
    <${ReviewList} caps=${caps.filter(needsCheck)} unclear=${unclear} />
    <div class="fx-group" style="margin:0">Caption style <span class="hint" style="font-weight:400">— ${sel.clips.length && selCap ? 'applies to the selected captions' : 'applies to all captions'}</span></div>
    <${TemplateGallery} value=${current} onPick=${id => A.captionTemplate(id).catch(() => {})} />
    ${caps.length > 0 && html`<div class="field wide" style="grid-template-columns:auto 1fr auto;display:grid;gap:8px;align-items:center">
      <label>Words per line</label>
      <input type="range" min="1" max="8" step="1" value=${words} onInput=${e => setWpl(+e.target.value)} />
      <button class="btn small" onClick=${() => op('rechunk_captions', { ids: selCap ? sel.clips : 'all', max_words: words, max_chars: Math.max(14, words * 7) }, `Captions: ${words} words per line`).then(() => setWpl(null))}>Apply ${words}</button>
    </div>`}
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small" onClick=${() => shiftAll(-0.1)} title="Captions too late? Move all earlier">−0.1 s</button>
      <button class="btn small" onClick=${() => shiftAll(0.1)} title="Captions too early? Move all later">+0.1 s</button>
    </div>
    <details>
      <summary class="hint" style="cursor:pointer">Names & places glossary (${glossary.length})</summary>
      <textarea class="input" rows="3" style="margin-top:6px" value=${gloss ?? glossary.join(', ')} onInput=${e => setGloss(e.target.value)}
        onBlur=${() => { if (gloss != null) { op('set_settings', { patch: { glossary: gloss.split(',').map(s => s.trim()).filter(Boolean) } }, 'Glossary'); setGloss(null); } }} />
      <div class="hint">Helps Whisper spell names right (e.g. Fo Guang Shan, E-DA Theme Park). These words are also highlighted by "Keyword Highlight".</div>
    </details>
    <div class="fx-group" style="margin:0">All lines (${subs.length})</div>
    <div class="sub-list">
      ${subs.length === 0 && html`<div class="hint">No captions yet. Click Auto Captions, or double-click an .srt/.ass file in the Project panel.</div>`}
      ${subs.map(c => html`<div class=${`sub-row ${sel.clips.includes(c.id) ? 'on' : ''}`}>
        <button class="sub-t" title="Jump here" onClick=${() => { player.seek(c.start + 0.01); select(c.id); }}>${tc(c.start, fps()).slice(3)}</button>
        <span class=${`lang ${c.meta?.lang && c.meta.lang !== 'en' ? 'tr' : ''} ${needsCheck(c) ? 'warn' : ''}`}
          title=${(needsCheck(c) ? `Check: ${c.meta.review.join(' · ')}\n` : '') + (c.meta?.original ? `Original: ${c.meta.original}\n` : '') + (c.meta?.src ? 'Click: wrong language? Redo this line' : '')}
          onClick=${e => c.meta?.src && set({ ctx: { x: e.clientX, y: e.clientY, items: [['en', 'English (no brackets)'], ['id', 'Indonesian → English ( )'], ['zh', 'Mandarin → English ( )']]
            .map(([l, lab]) => ({ label: `Redo as ${lab}`, run: () => { toast('Re-transcribing line…'); api('/api/subtitles/redo', { clip: c.id, lang: l })
              .then(r => set({ project: r.project, history: r.history })).catch(err => toast(err.message, 'error')); } })) } })}>${needsCheck(c) ? '?' : LANG[c.meta?.lang] || '··'}</span>
        <input class="input" value=${c.text.content} onFocus=${() => select(c.id)} onChange=${e => op('update', { ids: [c.id], patch: { text: { content: e.target.value } } }, 'Edit Caption')} />
        <button class=${`btn ghost icon small ${wrapped(c.text.content) ? 'on' : ''}`} title="Translated line: wrap in ( )" onClick=${() => toggleParen(c)}>( )</button>
        <button class="btn ghost icon small danger" title="Delete line" onClick=${() => op('delete', { ids: [c.id] }, 'Delete Caption')}><${Icon} n="x" s=${12} /></button>
      </div>`)}
    </div>
  </div>`;
}
