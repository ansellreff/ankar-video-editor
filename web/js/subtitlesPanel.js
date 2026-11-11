// Subtitles tab: every subtitle line in one list — edit text, toggle "( )" for translated lines, shift, restyle.
import { html, useState } from '../vendor/preact-htm.js';
import { S, set, useStore, fps, clipById, toast } from './store.js';
import { op, batch, api } from './api.js';
import { A } from './actions.js';
import { player } from './player.js';
import { Icon, tc } from './util.js';

const LANG = { en: 'EN', id: 'ID', zh: 'ZH', ms: 'MS', ja: 'JA', ko: 'KO' };
const isSub = c => c.type === 'text' && (c.text.preset === 'subtitle' || c.meta?.lang);
const wrapped = s => /^\(.*\)$/s.test(s.trim());

export function SubtitlesPanel() {
  const project = useStore(s => s.project);
  const sel = useStore(s => s.sel);
  const [gloss, setGloss] = useState(null);
  const subs = project.clips.filter(isSub).sort((a, b) => a.start - b.start);
  const glossary = project.settings.glossary || [];
  const toggleParen = c => {
    const t = c.text.content.trim();
    const next = wrapped(t) ? t.slice(1, -1).trim() : `(${t})`;
    op('update', { ids: [c.id], patch: { text: { content: next }, meta: { ...(c.meta || {}), translated: !wrapped(t) } } }, 'Toggle translated');
  };
  const shiftAll = d => batch(subs.map(c => ({ op: 'move', args: { ids: [c.id], delta: d, ignore_link: true } })), `Shift subtitles ${d > 0 ? '+' : ''}${d}s`);
  const styleAll = () => {
    const src = sel.clips.map(clipById).find(c => c && isSub(c));
    if (!src) return toast('Select one subtitle first — its style is copied to all', 'error');
    batch(subs.filter(c => c.id !== src.id).map(c => ({ op: 'update', args: { ids: [c.id], patch: { text: { style: src.text.style, x: src.text.x, y: src.text.y, anim: src.text.anim } } } })), 'Style all subtitles');
  };
  return html`<div style="display:grid;gap:8px;padding:8px 10px 12px">
    <button class="btn primary" onClick=${A.transcribe}><${Icon} n="cc" s=${14} /> Transcribe selected clip → English</button>
    <div class="hint">English speech is written as is; Indonesian / Mandarin is translated to English and shown in ( ). Uses Whisper (medium) on your PC.</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small" onClick=${() => shiftAll(-0.1)}>−0.1 s</button>
      <button class="btn small" onClick=${() => shiftAll(0.1)}>+0.1 s</button>
      <button class="btn small" onClick=${styleAll} title="Copy the selected subtitle's style to all">Style all like selected</button>
    </div>
    <details>
      <summary class="hint" style="cursor:pointer">Names & places glossary (${glossary.length})</summary>
      <textarea class="input" rows="3" style="margin-top:6px" value=${gloss ?? glossary.join(', ')} onInput=${e => setGloss(e.target.value)}
        onBlur=${() => { if (gloss != null) { op('set_settings', { patch: { glossary: gloss.split(',').map(s => s.trim()).filter(Boolean) } }, 'Glossary'); setGloss(null); } }} />
      <div class="hint">Helps Whisper spell names right (e.g. Fo Guang Shan, E-DA Theme Park).</div>
    </details>
    <div class="sub-list">
      ${subs.length === 0 && html`<div class="hint">No subtitles yet. Select a clip with speech and click Transcribe, or double-click an .srt/.ass file in the Project panel.</div>`}
      ${subs.map(c => html`<div class=${`sub-row ${sel.clips.includes(c.id) ? 'on' : ''}`}>
        <button class="sub-t" title="Jump here" onClick=${() => { player.seek(c.start + 0.01); set({ sel: { clips: [c.id], transition: null, asset: null } }); }}>${tc(c.start, fps()).slice(3)}</button>
        <span class=${`lang ${c.meta?.lang && c.meta.lang !== 'en' ? 'tr' : ''}`} style=${c.meta?.src ? 'cursor:pointer' : ''}
          title=${(c.meta?.original ? `Original: ${c.meta.original}\n` : '') + (c.meta?.src ? 'Click: wrong language? Redo this line as English / Indonesian / Mandarin' : '')}
          onClick=${e => c.meta?.src && set({ ctx: { x: e.clientX, y: e.clientY, items: [['en', 'English (no brackets)'], ['id', 'Indonesian → English ( )'], ['zh', 'Mandarin → English ( )']]
            .map(([l, lab]) => ({ label: `Redo as ${lab}`, run: () => { toast('Re-transcribing line…'); api('/api/subtitles/redo', { clip: c.id, lang: l })
              .then(r => set({ project: r.project, history: r.history })).catch(err => toast(err.message, 'error')); } })) } })}>${LANG[c.meta?.lang] || '··'}</span>
        <input class="input" value=${c.text.content} onChange=${e => op('update', { ids: [c.id], patch: { text: { content: e.target.value } } }, 'Edit Subtitle')} />
        <button class=${`btn ghost icon small ${wrapped(c.text.content) ? 'on' : ''}`} title="Translated line: wrap in ( )" onClick=${() => toggleParen(c)}>( )</button>
        <button class="btn ghost icon small danger" title="Delete line" onClick=${() => op('delete', { ids: [c.id] }, 'Delete Subtitle')}><${Icon} n="x" s=${12} /></button>
      </div>`)}
    </div>
  </div>`;
}
