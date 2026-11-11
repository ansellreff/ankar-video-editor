import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore, fps, toast } from './store.js';
import { api, projectAction } from './api.js';
import { A } from './actions.js';
import { projectDuration } from './evaluate.js';
import { Icon, tc, bytes, dur } from './util.js';
import { VoiceSampleDialog, SpeakersDialog } from './voicePanel.js';
import { VoiceWizard } from './voiceWizard.js';
import { MatchDialog } from './matchDialog.js';
import { ChangelogDialog } from './changelogDialog.js';
import { AssistantSettingsDialog } from './assistantPanel.js';
import { TemplateGallery } from './captionsPanel.js';
import { Progress } from './progress.js';
import { WhatsNewDialog } from './updates.js';

const close = () => set({ dialog: null });

function Dialog({ title, children, footer, width }) {
  useEffect(() => {
    const k = e => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);
  return html`<div class="scrim" onPointerDown=${e => e.target === e.currentTarget && close()}>
    <div class="dialog" style=${width ? `width:min(${width}px, calc(100vw - 32px))` : ''}>
      <div class="dh"><h2>${title}</h2><span style="flex:1" /><button class="btn ghost icon" onClick=${close}><${Icon} n="x" /></button></div>
      <div class="db">${children}</div>
      ${footer && html`<div class="df">${footer}</div>`}
    </div>
  </div>`;
}

function Seg({ value, options, onChange }) {
  return html`<div class="seg">${options.map(([v, l]) => html`<button class=${value === v ? 'on' : ''} onClick=${() => onChange(v)}>${l}</button>`)}</div>`;
}

function ExportDialog() {
  const job = useStore(s => s.exportJob);
  const exportsList = useStore(s => s.exports);
  const last = useStore(s => s.lastExport);
  const p = S.project;
  const [format, setFormat] = useState(p.format.preset);
  const [quality, setQuality] = useState('high');
  const hasIO = S.inPt != null && S.outPt != null && S.outPt > S.inPt;
  const [range, setRange] = useState('all');
  const total = projectDuration(p);
  const len = range === 'io' && hasIO ? S.outPt - S.inPt : total;
  const start = () => api('/api/export', { format, quality, range: range === 'io' && hasIO ? [S.inPt, S.outPt] : null })
    .then(() => set({ exportJob: { stage: 'video', value: 0 }, lastExport: null })).catch(e => toast(e.message, 'error'));
  const restore = name => { if (confirm(`Restore the timeline saved with ${name}? (You can undo this.)`)) api('/api/restore', { name }).then(r => { set({ project: r.project, history: r.history }); toast(`Restored ${name}`, 'ok'); close(); }); };
  return html`<${Dialog} title="Export video" width=${600} footer=${html`
      <button class="btn ghost" onClick=${() => A.open('exports')}><${Icon} n="folder" s=${14} /> Exports folder</button>
      <span style="flex:1" />
      ${job ? html`<button class="btn" onClick=${() => api('/api/export/cancel', {})}>Cancel export</button>`
            : html`<button class="btn primary" disabled=${!p.clips.length} onClick=${start}><${Icon} n="export" s=${14} /> Export ${dur(len)}</button>`}`}>
    <div class="row2"><span>Format</span><${Seg} value=${format} onChange=${setFormat} options=${[['reels', 'Reels · 1080×1920'], ['16:9', '16:9 · 1920×1080'], ['1:1', '1:1'], ['4:5', '4:5']]} /></div>
    <div class="row2"><span>Quality</span><${Seg} value=${quality} onChange=${setQuality} options=${[['draft', 'Draft (fast)'], ['high', 'High'], ['max', 'Maximum']]} /></div>
    <div class="row2"><span>Range</span><${Seg} value=${range} onChange=${setRange} options=${[['all', `Whole timeline (${dur(total)})`], ...(hasIO ? [['io', `In → Out (${dur(S.outPt - S.inPt)})`]] : [])]} /></div>
    <div class="hint">Renders from your original files on the GPU with the same effects you see in the monitor. Saved as the next version
      (<b>exports/vNN.mp4</b>) together with a copy of the timeline, so any version can be restored. Audio is normalized to ${p.settings.normalize_lufs ?? -14} LUFS.</div>
    ${job && html`<div><div style="display:flex;justify-content:space-between;margin-bottom:6px"><span>${job.stage === 'audio' ? 'Mixing audio…' : 'Rendering video…'}</span><span>${Math.round(job.value * 100)}%</span></div>
      <div class="bar"><i style=${`width:${job.value * 100}%`} /></div></div>`}
    ${last && !last.error && html`<div class="hint" style="color:var(--ok)">Done: v${String(last.version).padStart(2, '0')}.mp4 · ${last.frames} frames in ${last.seconds}s (${last.fps_render} fps) · ${last.lufs} LUFS</div>`}
    ${last?.error && html`<div class="hint" style="color:var(--danger)">Export failed: ${last.error}</div>`}
    <div style="font-weight:600;margin-top:4px">Versions</div>
    <div class="versions">
      ${exportsList.length === 0 && html`<div class="hint">No exports yet.</div>`}
      ${[...exportsList].sort((a, b) => (a.kind === 'draft') - (b.kind === 'draft') || b.time.localeCompare(a.time)).map(v => html`<div class="version">
        <span class="vn">${v.name.replace('.mp4', '').replace('draft/', '')}</span>
        ${v.kind === 'final' && html`<span class="chip on" style="border:0">Final</span>`}${v.kind === 'draft' && html`<span class="chip" style="border:0">Draft</span>`}
        <span class="vm">${v.time.replace('T', ' ')} · ${bytes(v.size)}</span>
        <a class="btn small" href=${v.url} target="_blank"><${Icon} n="play" s=${11} /> Play</a>
        ${v.restorable && html`<button class="btn small" onClick=${() => restore(v.name)}><${Icon} n="reset" s=${12} /> Restore</button>`}
      </div>`)}
    </div>
  </${Dialog}>`;
}

function IntroDialog() {
  const packs = S.packs || {};
  const [l1, setL1] = useState('Friday, October 30th 2026');
  const [l2, setL2] = useState('05:00 PM');
  const [pack, setPack] = useState('slim');
  const [start, setStart] = useState(S.introStart ?? 0);
  const go = () => {
    const lines = [
      { text: l1, weight: 500, size: 80, y: 860 / 1920, spacing: 1, track: 'T1' },
      ...(l2.trim() ? [{ text: l2, weight: 700, size: 107, y: 1040 / 1920, spacing: 4, track: 'T2' }] : []),
    ];
    A.typedIntro({ lines, pack, start }); close(); set({ introStart: null });
  };
  return html`<${Dialog} title="Typed Intro" footer=${html`<button class="btn ghost" onClick=${close}>Cancel</button><button class="btn primary" onClick=${go}><${Icon} n="keyboard" s=${14} /> Add to timeline</button>`}>
    <div class="hint">Black screen, text types on letter by letter with a real keyboard sound synced to each letter (your v3 intro). Text goes on T1/T2, sound on A3.</div>
    <div class="row2"><span>Line 1</span><input class="input" value=${l1} onInput=${e => setL1(e.target.value)} /></div>
    <div class="row2"><span>Line 2 (bold)</span><input class="input" value=${l2} onInput=${e => setL2(e.target.value)} /></div>
    <div class="row2"><span>Keyboard sound</span><select class="input" value=${pack} onChange=${e => setPack(e.target.value)}>
      ${Object.entries(packs).map(([k, v]) => html`<option value=${k}>${v.name} — ${v.license}</option>`)}</select></div>
    <div class="row2"><span>Start at</span><input class="input" type="number" step="0.1" min="0" value=${start} onInput=${e => setStart(+e.target.value)} /></div>
  </${Dialog}>`;
}

const SHORTCUTS = [
  ['Play / pause', 'Space'], ['Shuttle back / stop / forward', 'J / K / L'], ['Previous / next frame', '← / →'], ['Back / forward 1 s', 'Shift+← / →'],
  ['Previous / next edit point', '↑ / ↓'], ['Go to start / end', 'Home / End'], ['Split at playhead', 'Ctrl+K'], ['Delete / ripple delete', 'Del / Shift+Del'],
  ['Undo / redo', 'Ctrl+Z / Ctrl+Shift+Z'], ['Copy / cut / paste', 'Ctrl+C / X / V'], ['Select all / deselect', 'Ctrl+A / Esc'],
  ['Selection / razor / rate-stretch tool', 'V / C / R'], ['Snapping', 'S'], ['Add marker', 'M'], ['Set in / out, clear', 'I / O, Alt+X'],
  ['Speed / Duration', 'Ctrl+R'], ['Insert 2 s freeze frame', 'Shift+F'], ['Show clip source (match frame)', 'F'],
  ['Add edit to all tracks', 'Ctrl+Shift+K'], ['Nudge selected layer 1 px / 10 px', 'Ctrl+arrows / +Shift'],
  ['Move / scale / rotate / crop a layer', 'drag in the monitor'], ['New / open project', 'Ctrl+Alt+N / Ctrl+O'],
  ['Save checkpoint / Save As', 'Ctrl+S / Ctrl+Shift+S'], ['Add AI narration at playhead', 'Ctrl+Shift+N'],
  ['Zoom in / out / fit (keeps the playhead in view)', '= / - / \\'], ['Go to playhead', 'P'], ['Zoom at mouse', 'Ctrl+wheel'], ['Cross dissolve at playhead', 'Ctrl+D'], ['Add title', 'Ctrl+T'],
  ['Unlink', 'Ctrl+L'], ['Enable / disable clip', 'Shift+E'], ['Export', 'Ctrl+E'], ['Ignore link while moving · ripple trim', 'hold Alt'],
];
function ShortcutsDialog() {
  return html`<${Dialog} title="Keyboard shortcuts" width=${560}>
    <div class="shortcuts">${SHORTCUTS.map(([a, k]) => html`<span>${a}</span><span class="kbd">${k}</span>`)}</div>
  </${Dialog}>`;
}
function AboutDialog() {
  return html`<${Dialog} title="How this project works" width=${620}>
    <div style="display:grid;gap:10px;color:var(--text-2)">
      <div><b style="color:var(--text)">Your files.</b> Each project has its own folder (<code>projects/&lt;name&gt;/</code>). Drop anything into its <code>import/</code> — it's sorted into <code>assets/</code> (video, photos, brand, audio/music, sfx, voiceover, subtitles) and <code>docs/</code> (script, storyboard) automatically. The Project panel updates live; nothing is uploaded.</div>
      <div><b style="color:var(--text)">The edit.</b> Everything you do is saved instantly to <code>projects/vlog/project.json</code> (autosave copies in <code>autosave/</code>). Undo/redo covers every change.</div>
      <div><b style="color:var(--text)">Edit with Claude.</b> Ask Claude in the chat, e.g. “add a cross dissolve between the 2nd and 3rd clip” — Claude edits project.json and this window updates within a second (you'll see a toast). Undo works for those edits too.</div>
      <div><b style="color:var(--text)">Preview vs export.</b> The monitor plays fast low-res proxies (in <code>cache/</code>). Export renders the originals on the GPU with the same shaders, to <code>exports/vNN.mp4</code> + a timeline snapshot you can restore.</div>
    </div>
  </${Dialog}>`;
}

function ProjectsDialog() {
  const tab = useStore(s => s.projectsTab || 'open');
  const projects = useStore(s => s.projects || []);
  const cps = useStore(s => s.checkpoints || []);
  const current = useStore(s => s.projectName);
  const [name, setName] = useState('');
  const [fmt, setFmt] = useState('reels');
  const setTab = t => set({ projectsTab: t });
  useEffect(() => { api('/api/projects').then(r => set({ projects: r.projects, checkpoints: r.checkpoints })); }, []);
  const act = (a, b, msg) => projectAction(a, b).then(() => { if (msg) toast(msg, 'ok'); if (a !== 'delete' && a !== 'duplicate') close(); });
  const thumb = p => p.thumb && S.assets[p.thumb]?.derived?.poster ? `background-image:url(/files/cache/media/${p.thumb}/poster.jpg)` : '';
  return html`<${Dialog} title="Projects" width=${720}>
    <div class="seg" style="justify-self:start">${[['open', 'Open'], ['new', 'New'], ['saveas', 'Save As'], ['checkpoints', 'Checkpoints']].map(([k, l]) =>
      html`<button class=${tab === k ? 'on' : ''} onClick=${() => setTab(k)}>${l}</button>`)}</div>
    ${tab === 'open' && html`<div class="proj-grid">
      ${[...projects].sort((a, b) => a.recent - b.recent).map(p => html`<div class=${`proj-card ${p.current ? 'current' : ''}`}>
        <div class="pt" style=${thumb(p)} onClick=${() => !p.current && act('open', { name: p.name }, `Opened “${p.name}”`)}>${!p.thumb ? html`<${Icon} n="film" s=${22} />` : ''}</div>
        <div class="pm"><div class="pn">${p.name}${p.current ? html` <span class="hint">· open</span>` : ''}</div>
          <div class="hint">${p.format} · ${dur(p.duration)} · ${p.clips} clips · ${p.modified.replace('T', ' ')}</div>
          <div class="pa">
            ${!p.current && html`<button class="btn small primary" onClick=${() => act('open', { name: p.name }, `Opened “${p.name}”`)}>Open</button>`}
            <button class="btn small" onClick=${() => { const n = prompt('Duplicate as', `${p.name} copy`); if (n) act('duplicate', { name: p.name, new: n }, `Duplicated as “${n}”`).then(() => api('/api/projects').then(r => set({ projects: r.projects }))); }}>Duplicate</button>
            <button class="btn small" onClick=${() => { const n = prompt('Rename project', p.name); if (n && n !== p.name) projectAction('rename', { name: p.name, new: n }).then(() => api('/api/projects').then(r => set({ projects: r.projects }))); }}>Rename</button>
            <button class="btn small danger" onClick=${() => confirm(`Move “${p.name}” (its folder with assets and exports) to projects/_trash? You can restore it from there.`) && act('delete', { name: p.name }, `Moved “${p.name}” to trash`)}><${Icon} n="trash" s=${12} /></button>
          </div></div>
      </div>`)}
    </div>`}
    ${tab === 'new' && html`<div style="display:grid;gap:12px">
      <div class="row2"><span>Name</span><input class="input" placeholder="e.g. Taiwan Vlog — final" value=${name} onInput=${e => setName(e.target.value)} /></div>
      <div class="row2"><span>Format</span><${Seg} value=${fmt} onChange=${setFmt} options=${[['reels', 'Instagram Reels'], ['16:9', '16:9 YouTube'], ['1:1', '1:1'], ['4:5', '4:5']]} /></div>
      <div class="hint">Each project is one folder: <b>projects/&lt;name&gt;/</b> with its own assets, import, docs and exports. A new project starts empty. AI voices, fonts, LUTs and noise beds are shared by all projects.</div>
      <div><button class="btn primary" disabled=${!name.trim()} onClick=${() => act('new', { name, format: fmt }, `Created “${name}”`)}><${Icon} n="plus" s=${14} /> Create project</button></div>
    </div>`}
    ${tab === 'saveas' && html`<div style="display:grid;gap:12px">
      <div class="row2"><span>New name</span><input class="input" placeholder=${`${current} copy`} value=${name} onInput=${e => setName(e.target.value)} /></div>
      <div class="hint">Copies the current timeline into a new project and switches to it. “${current}” stays as it is.</div>
      <div><button class="btn primary" disabled=${!name.trim()} onClick=${() => act('save_as', { name }, `Saved as “${name}”`)}>Save As</button></div>
    </div>`}
    ${tab === 'checkpoints' && html`<div style="display:grid;gap:8px">
      <div style="display:flex;gap:8px"><input class="input" placeholder="Label (optional), e.g. before music" value=${name} onInput=${e => setName(e.target.value)} />
        <button class="btn primary" onClick=${() => projectAction('checkpoint', { label: name }).then(() => setName(''))}>Save checkpoint</button></div>
      <div class="hint">Edits are saved instantly anyway; checkpoints are named restore points (Ctrl+S makes one).</div>
      <div class="versions">${cps.length === 0 ? html`<div class="hint">No checkpoints yet.</div>` : cps.map(c => html`<div class="version">
        <span class="vn">${c.time}</span><span class="vm">${c.label || '—'}</span>
        <button class="btn small" onClick=${() => { A.revert(c.file); close(); }}><${Icon} n="reset" s=${12} /> Revert</button></div>`)}</div>
    </div>`}
  </${Dialog}>`;
}

function SpeedDialog() {
  const c = S.sel.clips.map(id => S.project.clips.find(k => k.id === id)).find(k => k && k.type === 'media' && !k.still && k.hold == null);
  const srcLen = c ? c.out - c.in : 1;
  const [pct, setPct] = useState(Math.round((c?.speed || 1) * 100));
  const [rev, setRev] = useState(!!c?.reverse);
  const [pitch, setPitch] = useState(c?.keep_pitch !== false);
  const [blend, setBlend] = useState(!!c?.blend);
  const [ripple, setRipple] = useState(true);
  if (!c) { close(); return null; }
  const newDur = srcLen / (pct / 100);
  const go = () => A.setSpeed({ speed: pct / 100, reverse: rev, keep_pitch: pitch, blend, ripple }).then(close);
  return html`<${Dialog} title="Speed / Duration" width=${480} footer=${html`<button class="btn ghost" onClick=${close}>Cancel</button><button class="btn primary" onClick=${go}>Apply</button>`}>
    <div class="row2"><span>Speed</span><div style="display:flex;gap:8px;align-items:center">
      <input class="input" type="number" min="10" max="1600" step="5" value=${pct} style="width:90px" onInput=${e => setPct(Math.max(10, Math.min(1600, +e.target.value || 100)))} /> %</div></div>
    <div class="row2"><span>Presets</span><div class="seg">${[25, 50, 75, 100, 150, 200, 400].map(v => html`<button class=${pct === v ? 'on' : ''} onClick=${() => setPct(v)}>${v < 100 ? (v / 100) + '×' : v === 100 ? '1×' : (v / 100) + '×'}</button>`)}</div></div>
    <div class="row2"><span>Duration</span><div style="display:flex;gap:8px;align-items:center">
      <input class="input" type="number" min="0.1" step="0.1" value=${newDur.toFixed(2)} style="width:90px" onChange=${e => { const d = +e.target.value; if (d > 0) setPct(Math.round(srcLen / d * 1000) / 10); }} /> seconds</div></div>
    <label class="check"><input type="checkbox" checked=${rev} onChange=${e => setRev(e.target.checked)} /> Reverse (play backwards)</label>
    <label class="check"><input type="checkbox" checked=${pitch} onChange=${e => setPitch(e.target.checked)} /> Keep audio pitch (no chipmunk / deep voice)</label>
    <label class="check"><input type="checkbox" checked=${blend} onChange=${e => setBlend(e.target.checked)} /> Smooth slow motion (frame blending, export)</label>
    <label class="check"><input type="checkbox" checked=${ripple} onChange=${e => setRipple(e.target.checked)} /> Ripple: push / pull the clips after it</label>
    <div class="hint">Slow motion below 50% looks smoothest from footage shot at 60 fps or more. Linked audio changes speed with the video.</div>
  </${Dialog}>`;
}

function CaptionsDialog() {
  const tpls = useStore(s => s.presets?.caption_templates || []);
  const task = useStore(s => s.task);
  const selIds = S.sel.clips.filter(id => S.project.clips.some(c => c.id === id && c.type === 'media' && !c.still));
  const hasDialogue = S.project.clips.some(c => c.type === 'media' && S.project.tracks.find(t => t.id === c.track)?.role === 'dialogue');
  const [scope, setScope] = useState(selIds.length ? 'clip' : 'dialogue');
  const [tpl, setTpl] = useState(S.project.clips.find(c => c.text?.caption)?.text.caption.template || 'karaoke_line');
  const t = tpls.find(x => x.id === tpl) || tpls[0] || {};
  const [mw, setMw] = useState(null);
  const [pos, setPos] = useState('bottom');
  const [replace, setReplace] = useState(true);
  const [busy, setBusy] = useState(false);
  const [since, setSince] = useState(null);
  const [done, setDone] = useState(null);
  const words = mw ?? t.max_words ?? 5;
  const start = () => {
    setBusy(true); setDone(null); setSince(Date.now());
    api('/api/captions/auto', { scope, ids: selIds, template: tpl, max_words: words, max_chars: Math.max(t.max_chars || 28, words * 6), position: pos, replace })
      .then(r => { set({ project: r.project, history: r.history }); setDone(r); toast(`Added ${r.captions} captions`, 'ok'); })
      .catch(e => toast(e.message, 'error')).finally(() => setBusy(false));
  };
  const check = () => set({ dialog: null, fxTab: 'captions' });
  return html`<${Dialog} title="Auto Captions" width=${760} footer=${html`
      <span class="hint">Runs on your PC (Whisper medium). About 1× the length of the speech.</span><span style="flex:1" />
      ${done ? html`<button class="btn" onClick=${() => setDone(null)}>Run again</button><button class="btn primary" onClick=${check}>${done.review ? `Check ${done.review} unclear spot${done.review > 1 ? 's' : ''}` : 'Done'}</button>`
             : html`<button class="btn primary" disabled=${busy || (scope === 'clip' && !selIds.length)} onClick=${start}><${Icon} n="cc" s=${14} /> ${busy ? 'Working…' : 'Create captions'}</button>`}`}>
    <div class="row2"><span>Caption</span><${Seg} value=${scope} onChange=${setScope} options=${[
      ['clip', selIds.length ? `Selected clip${selIds.length > 1 ? 's' : ''} (${selIds.length})` : 'Selected clip (select one first)'],
      ['dialogue', `Dialogue track${hasDialogue ? '' : ' (empty)'}`], ['timeline', 'Dialogue + narration']]} /></div>
    <div class="row2" style="align-items:start"><span>Style</span><div style="max-height:300px;overflow:auto;padding-right:4px">
      <${TemplateGallery} value=${tpl} onPick=${id => { setTpl(id); setMw(null); }} /></div></div>
    <div class="row2"><span>Words per line</span><div style="display:flex;gap:10px;align-items:center">
      <input type="range" min="1" max="8" step="1" value=${words} onInput=${e => setMw(+e.target.value)} style="width:180px" /><b>${words}</b>
      <span class="hint">${words <= 2 ? 'punchy, one beat at a time' : words <= 5 ? 'short lines (best for vertical video)' : 'longer, classic subtitles'}</span></div></div>
    <div class="row2"><span>Position</span><${Seg} value=${pos} onChange=${setPos} options=${[['bottom', 'Lower third (template)'], ['middle', 'Middle'], ['top', 'Top']]} /></div>
    <label class="check"><input type="checkbox" checked=${replace} onChange=${e => setReplace(e.target.checked)} /> Replace captions that are already there (no duplicates)</label>
    ${busy && html`<${Progress} value=${task?.value ?? null} stage=${task ? `${task.name} — ${task.stage || ''}` : 'Starting…'} since=${since} estimate=${30} />`}
    ${done && html`<div class="done-box"><${Icon} n="check" s=${16} /> Added <b>${done.captions}</b> captions.
      ${done.review ? html` <b>${done.review}</b> spot${done.review > 1 ? 's' : ''} sounded unclear — they're listed under <b>Needs checking</b> in the Captions tab and marked red on the timeline.` : ' Everything was clear.'}
      You can change the style anytime (Captions tab or Inspector) and fix any word — timing is kept.</div>`}
  </${Dialog}>`;
}

export function Dialogs() {
  const d = useStore(s => s.dialog);
  if (d === 'captions') return html`<${CaptionsDialog} />`;
  if (d === 'voiceSample') return html`<${VoiceSampleDialog} close=${close} Dialog=${Dialog} />`;
  if (d === 'speakers') return html`<${SpeakersDialog} close=${close} Dialog=${Dialog} />`;
  if (d === 'wizard') return html`<${VoiceWizard} close=${close} Dialog=${Dialog} />`;
  if (d === 'match') return html`<${MatchDialog} close=${close} Dialog=${Dialog} Seg=${Seg} />`;
  if (d === 'changelog') return html`<${ChangelogDialog} close=${close} Dialog=${Dialog} />`;
  if (d === 'aiSettings') return html`<${AssistantSettingsDialog} close=${close} Dialog=${Dialog} />`;
  if (d === 'projects') return html`<${ProjectsDialog} />`;
  if (d === 'speed') return html`<${SpeedDialog} />`;
  if (d === 'export') return html`<${ExportDialog} />`;
  if (d === 'intro') return html`<${IntroDialog} />`;
  if (d === 'shortcuts') return html`<${ShortcutsDialog} />`;
  if (d === 'about') return html`<${AboutDialog} />`;
  if (d === 'whatsnew') return html`<${WhatsNewDialog} close=${close} Dialog=${Dialog} />`;
  return null;
}

export function ContextMenu() {
  const ctx = useStore(s => s.ctx);
  useEffect(() => {
    if (!ctx) return;
    const off = e => { if (!e.target.closest?.('.ctx')) set({ ctx: null }); };
    setTimeout(() => window.addEventListener('pointerdown', off), 0);
    return () => window.removeEventListener('pointerdown', off);
  }, [ctx]);
  if (!ctx) return null;
  const x = Math.min(ctx.x, window.innerWidth - 230), y = Math.min(ctx.y, window.innerHeight - ctx.items.length * 32 - 20);
  return html`<div class="ctx" style=${`left:${x}px;top:${y}px`}>
    ${ctx.items.map(it => it.sep ? html`<div class="sep" />` : html`<button class="item" disabled=${it.off} onClick=${() => { set({ ctx: null }); it.run(); }}>
      <span class="label">${it.label}</span>${it.kbd && html`<span class="kbd">${it.kbd}</span>`}</button>`)}
  </div>`;
}

export function Toasts() {
  const toasts = useStore(s => s.toasts);
  return html`<div class="toasts">${toasts.map(t => html`<div class=${`toast ${t.kind}`}><span class="ti" /><div><div>${t.text}</div>${t.detail && html`<div class="td">${t.detail}</div>`}</div></div>`)}</div>`;
}
