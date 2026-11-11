// AI Voice tab: voice profiles (samples from your own clips/files/mic), tones, narration clips.
import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore, toast, clipById } from './store.js';
import { api, op } from './api.js';
import { A } from './actions.js';
import { player } from './player.js';
import { Icon } from './util.js';
import { PaceControls } from './paceControls.js';
import { VoiceFxControls } from './voiceFxControls.js';

let audioEl = null;

/** Files that can contain someone's voice: your videos first, then voiceover/music audio (no SFX, samples or generated files). */
export function voiceSources() {
  const skip = ['/sfx/', '/voices/', '/generated/'];
  return Object.values(S.assets)
    .filter(a => (a.kind === 'video' || a.kind === 'audio') && a.meta?.has_audio && !skip.some(s => a.path.includes(s)))
    .sort((a, b) => (a.kind === 'video' ? 0 : 1) - (b.kind === 'video' ? 0 : 1) || (a.path.includes('_samples') ? 1 : 0) - (b.path.includes('_samples') ? 1 : 0)
      || a.path.localeCompare(b.path));
}
export function playFile(path) {
  if (!audioEl) audioEl = new Audio();
  audioEl.src = `/files/${path.split('/').map(encodeURIComponent).join('/')}`;
  audioEl.play().catch(() => {});
}

// ElevenLabs voice_settings (stability / similarity / style / speaker boost); stored in config/settings.json
const EL_PRESETS = [
  ['steady', 'Steady', 'Consistent narrator: same energy and speed every line', { stability: 0.75, similarity: 0.85, style: 0.0, speaker_boost: true }],
  ['balanced', 'Balanced', 'Natural with a little variation', { stability: 0.55, similarity: 0.85, style: 0.15, speaker_boost: true }],
  ['expressive', 'Expressive', 'More emotion, but less predictable', { stability: 0.35, similarity: 0.8, style: 0.45, speaker_boost: true }],
];
function ElVoiceSettings({ cfg, save }) {
  const v = cfg.el_voice || { auto: true, stability: 0.55, similarity: 0.85, style: 0, speaker_boost: true };
  const v3 = (cfg.el_model || '').includes('v3');
  const put = patch => save({ el_voice: { ...v, auto: false, ...patch } });
  const preset = EL_PRESETS.find(p => !v.auto && Object.entries(p[3]).every(([k, x]) => Math.abs((v[k] === true ? 1 : v[k] === false ? 0 : v[k]) - (x === true ? 1 : x === false ? 0 : x)) < 0.01));
  const row = (label, key, tip, left, right) => html`<div class="el-row" title=${tip}>
    <span class="pace-l">${label}</span><span class="hint el-end">${left}</span>
    <input type="range" min="0" max="1" step="0.05" value=${v[key]} disabled=${v.auto} style=${`--fill:${v[key] * 100}%`} onChange=${e => put({ [key]: +e.target.value })} />
    <span class="hint el-end">${right}</span><span class="pace-n">${Math.round(v[key] * 100)}%</span></div>`;
  return html`<div class="el-voice">
    <div class="vh" style="font-size:12.5px">Voice settings</div>
    <div class="seg pace-seg">
      <button class=${v.auto ? 'on' : ''} title="Settings follow each line's tone (Cheerful, Serious…)" onClick=${() => save({ el_voice: { ...v, auto: true } })}>Auto</button>
      ${EL_PRESETS.map(([id, label, tip, vals]) => html`<button class=${preset?.[0] === id ? 'on' : ''} title=${tip} onClick=${() => put(vals)}>${label}</button>`)}
    </div>
    ${row('Stability', 'stability', 'Higher = steadier, more consistent delivery between lines. Lower = more emotional range, but each take can sound different.', 'varied', 'steady')}
    ${row('Similarity', 'similarity', 'How closely to stick to the cloned voice. Very high can also copy background noise from the samples.', 'loose', 'exact')}
    ${!v3 && row('Style', 'style', 'Exaggerates the speaking style. Adds character, but makes lines less consistent (and slower to generate). 0% for steady narration.', 'none', 'strong')}
    <label class="check"><input type="checkbox" checked=${v.speaker_boost} disabled=${v.auto} onChange=${e => put({ speaker_boost: e.target.checked })} />
      <span class="hint">Speaker boost (closer to the original speaker)</span></label>
    <div class="hint">${v.auto ? 'Auto: each line’s tone sets these. Pick Steady for the most consistent narration.' : v3 ? 'v3 models only take Stability 0 / 50 / 100%; the nearest is used.' : 'Lines made with these settings are cached; change them and press Regenerate to hear the difference.'}</div>
  </div>`;
}

function EngineCard() {
  const cfg = useStore(s => s.ttsStatus?.config) || {};
  const installed = useStore(s => s.ttsStatus?.installed);
  const [acc, setAcc] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = patch => api('/api/tts/config', patch).then(c => set(s => ({ ttsStatus: { ...(s.ttsStatus || {}), config: c } })))
    .catch(e => toast(e.message, 'error'));
  const check = () => { setBusy(true); api('/api/tts/elevenlabs/check', {}).then(c => { setAcc(c); set({ elCaps: c }); }).catch(e => { setAcc(null); toast(e.message, 'error'); }).finally(() => setBusy(false)); };
  const el = cfg.engine === 'elevenlabs';
  return html`<div class="voice-card">
    <div class="vh">Voice engine</div>
    <div class="seg">
      <button class=${!el ? 'on' : ''} onClick=${() => save({ engine: 'local' })}>Local (free, on this PC)</button>
      <button class=${el ? 'on' : ''} onClick=${() => save({ engine: 'elevenlabs' })}>ElevenLabs (cloud)</button>
    </div>
    ${!el && html`<div class="hint">${installed ? 'Chatterbox runs on your PC: private and unlimited, about 30–60 s per line.' : 'Local engine not installed (.venv-tts).'}</div>`}
    ${el && html`
      ${cfg.key_set ? html`<div class="hint">API key saved <b>${cfg.key_masked}</b> (${cfg.key_source}).
          <button class="btn ghost small" onClick=${() => window.open('/keys', 'vs-keys')}>Manage API keys…</button></div>`
        : html`<div style="display:flex;gap:6px;align-items:center"><span class="hint">No ElevenLabs key yet.</span>
          <button class="btn small primary" onClick=${() => window.open('/keys', 'vs-keys')}>Add it on the API Keys page</button></div>
          <div class="hint">Get it at elevenlabs.io ▸ Developers ▸ API keys. Keys are encrypted on this PC, protected by your password, and never shown again.</div>`}
      ${cfg.key_set && html`<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="btn small" disabled=${busy} onClick=${check}>${busy ? 'Checking…' : 'Check account'}</button>
        ${acc?.credits && html`<span class="hint"><b>${acc.credits.left.toLocaleString()}</b> of ${acc.credits.limit.toLocaleString()} characters left · ${acc.credits.tier}</span>`}
      </div>
      ${acc?.problems?.length > 0 && html`<div class="notice warn">${acc.problems.map(p => html`<div style="margin-bottom:4px">• ${p}</div>`)}</div>`}
      ${acc && !acc.problems?.length && html`<div class="notice ok">Ready to clone voices with ElevenLabs.</div>`}
      <div class="field wide"><label>Model</label><select class="input" value=${cfg.el_model} onChange=${e => save({ el_model: e.target.value })}>
        ${(acc?.models || [{ id: cfg.el_model, name: cfg.el_model }]).map(m => html`<option value=${m.id}>${m.name}</option>`)}</select></div>`}
      <${ElVoiceSettings} cfg=${cfg} save=${save} />
      <label class="check"><input type="checkbox" checked=${cfg.fallback} onChange=${e => save({ fallback: e.target.checked })} />
        <span class="hint">If ElevenLabs fails (credits used up, bad key), make that line with the local voice instead</span></label>
      <div class="hint">With ElevenLabs your voice samples are uploaded to make the clone, and each line uses credits (≈1 per character). Switch back to Local anytime.</div>`}
  </div>`;
}

function HowTo() {
  return html`<details class="voice-card" open=${!(S.voices || []).length}>
    <summary class="vh" style="cursor:pointer">How to clone your voice from a video</summary>
    <ol class="howto">
      <li>Drop your video into this project's <b>import/</b> folder. <button class="btn ghost small" onClick=${() => A.open('import')}>Open folder</button> It shows up in the Project panel.</li>
      <li>Click <b>Find speakers in a video</b> below, choose the video, <b>Find speakers</b>.</li>
      <li>Listen to Person 1 / Person 2, pick yourself, type your name, tick permission, <b>Make voice</b>.</li>
      <li>Test it in <b>Try it → MP3</b> and download the MP3, or put narration on the timeline: <b>Narration at playhead</b> (or right-click the A4 track), type the text, pick voice + tone, <b>Generate voice</b>.</li>
    </ol>
  </details>`;
}

export function VoicePanel() {
  const voices = useStore(s => s.voices || []);
  const status = useStore(s => s.ttsStatus);
  const project = useStore(s => s.project);
  const jobs = useStore(s => s.ttsJobs || {});
  const selIds = useStore(s => s.sel.clips);
  const [newName, setNewName] = useState('');
  const [consent, setConsent] = useState(false);
  useEffect(() => { api('/api/voices').then(r => set({ voices: r.voices, ttsStatus: r.tts })); }, []);
  const narr = project.clips.filter(c => c.type === 'tts');
  const vnames = new Set(voices.map(v => v.name));
  const pending = narr.filter(c => c.tts.stale || !c.tts.file);
  const ready = pending.filter(c => (c.tts.text || '').trim() && (!c.tts.voice || vnames.has(c.tts.voice)));
  const blocked = pending.filter(c => !ready.includes(c));
  const stale = ready.length;
  const fmtT = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  const jump = c => { set({ sel: { clips: [c.id], transition: null, asset: null } }); player.seek(c.start + 0.01); setTimeout(() => window.dispatchEvent(new Event('vs-edit-narration')), 200); };
  const running = Object.values(jobs).filter(j => j.state === 'running' || j.state === 'queued').length;
  const create = () => api('/api/voices/create', { name: newName, consent }).then(r => { set({ voices: r.voices }); setNewName(''); setConsent(false); toast(`Voice “${r.name}” created — now add samples`, 'ok'); })
    .catch(e => toast(e.message, 'error'));
  const del = f => confirm('Delete this sample? (It is kept in cache/trash in case you need it back.)') && api('/api/voices/delete_sample', { file: f }).then(r => set({ voices: r.voices }));
  const voiceMenu = (e, v) => {
    const users = project.clips.filter(c => c.type === 'tts' && c.tts?.voice === v.name).length;
    set({ ctx: { x: e.clientX, y: e.clientY, items: [
      { label: 'Rebuild from a recording…', run: () => set({ wizardInit: { rebuild: v.name }, dialog: 'wizard' }) },
      { label: 'Rename voice…', run: () => { const n = prompt(`New name for “${v.name}”`, v.name); if (n && n.trim() !== v.name)
        api('/api/voices/rename', { name: v.name, new: n }).then(r => { set({ voices: r.voices }); toast(`Renamed to “${r.name}”`, 'ok'); }).catch(err => toast(err.message, 'error')); } },
      { label: 'Delete voice…', run: () => { if (!confirm(`Delete the voice “${v.name}” and all ${v.samples.length} of its samples?${users ? `\n\n${users} narration clip(s) in this project use it: they keep their audio, but need another voice before regenerating.` : ''}\n\nThe files are moved to cache/trash, so a mistake can still be undone by hand.`)) return;
        api('/api/voices/delete', { name: v.name }).then(r => { set({ voices: r.voices }); toast(`Deleted voice “${v.name}”`, 'ok'); }).catch(err => toast(err.message, 'error')); } },
    ] } });
  };
  const sampleMenu = (e, v, s) => {
    const others = voices.filter(o => o.name !== v.name);
    const moods = ['neutral', 'cheerful', 'excited', 'curious', 'warm', 'calm', 'serious', 'dramatic'].filter(m => m !== s.mood);   // = app/tts/base.py MOODS
    set({ ctx: { x: e.clientX, y: e.clientY, items: [
      { label: '▶ Play', run: () => playFile(s.file) },
      { sep: true },
      ...others.map(o => ({ label: `Move to “${o.name}”`, run: () => api('/api/voices/move_sample', { file: s.file, voice: o.name })
        .then(r => { set({ voices: r.voices }); toast(`Moved to ${o.name}`, 'ok'); }).catch(err => toast(err.message, 'error')) })),
      ...(others.length ? [{ sep: true }] : []),
      ...moods.map(m => ({ label: `Tag as ${m}`, run: () => api('/api/voices/move_sample', { file: s.file, voice: v.name, mood: m })
        .then(r => set({ voices: r.voices })).catch(err => toast(err.message, 'error')) })),
      { sep: true },
      { label: 'Delete sample', run: () => del(s.file) },
    ] } });
  };
  const resetAll = () => {
    const t = prompt(`This removes ALL ${voices.length} voice(s) and their samples, so you can train from scratch.\nA backup is kept in cache/trash.\n\nType RESET to confirm:`);
    if (t !== 'RESET') return t != null && toast('Not reset (you need to type RESET)', 'error');
    api('/api/voices/reset', { confirm: 'RESET' }).then(r => { set({ voices: r.voices }); toast(`All voices reset (${r.voices.length ? '' : 'none left'}; backup in ${r.backup})`, 'ok'); })
      .catch(err => toast(err.message, 'error'));
  };
  return html`<div style="display:grid;gap:10px;padding:8px 10px 12px">
    <button class="btn primary" style="height:40px" onClick=${() => A.voiceWizard()}><${Icon} n="voice" s=${15} /> Voice from Video</button>
    <div class="hint" style="margin-top:-4px">Upload a video → extract the person's voice → the AI learns it → it narrates your text (MP3 or timeline).</div>
    <${TryIt} />
    <${EngineCard} />
    ${status?.config?.engine !== 'elevenlabs' && status?.installed && html`<div class="hint">Local engine: ${status.engine === 'ready' ? 'ready' : status.engine === 'loading' ? 'loading the model…' : 'starts on first use (~20 s)'}</div>`}
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn primary" onClick=${() => A.addNarration()}><${Icon} n="plus" s=${14} /> Narration at playhead</button>
      <button class="btn" disabled=${!stale} title="Generate every narration clip on the timeline that is new or was changed"
        onClick=${() => A.generateNarration(ready.map(c => c.id))}>${stale ? `Generate ${stale} narration clip${stale > 1 ? 's' : ''}` : 'All narration generated'}</button>
    </div>
    ${blocked.length > 0 && html`<div class="notice warn" style="font-size:12px">
      ${blocked.length} narration clip${blocked.length > 1 ? 's' : ''} can't be generated yet:
      ${blocked.map(c => html`<div style="display:flex;gap:6px;align-items:center;margin-top:4px">
        <button class="btn small" onClick=${() => jump(c)}>${fmtT(c.start)}</button>
        <span>${!(c.tts.text || '').trim() ? 'no text yet — type what to say' : `voice “${c.tts.voice}” was deleted — pick another`}</span>
        <button class="btn ghost icon small danger" title="Delete this narration clip" onClick=${() => op('delete', { ids: [c.id] }, 'Delete Narration')}>×</button></div>`)}
    </div>`}
    ${running > 0 && html`<div class="hint" style="color:var(--accent)">Generating ${running} line${running > 1 ? 's' : ''}… (CPU, roughly 1–3× the speech length)</div>`}
    ${(() => {
      const timed = narr.filter(c => (c.tts.segs || []).length && c.tts.file);
      if (!timed.length) return '';
      const selc = timed.find(c => selIds.includes(c.id));
      return html`<div class="fx-group" style="padding:4px 0 0">Narration timing</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
          <button class="btn" disabled=${!selc} title="Place the sentences so they don't talk over people and start on shot changes"
            onClick=${() => set({ dialog: 'match', matchClip: selc.id })}><${Icon} n="wand" s=${14} /> Match to video…</button>
          <span class="hint">${selc ? '' : 'Select a narration clip first.'}</span></div>
        <div class="hint">Drag sentences inside a narration clip on the timeline to fix timing — no regenerating, no credits.</div>`;
    })()}

    <div class="fx-group" style="padding:4px 0 0">Voices</div>
    ${voices.length === 0 && html`<div class="hint">No voices yet. Create one below, then add 10–60 s of clean speech: right-click a clip on the timeline ▸ “Use as voice sample…”, or record with the mic.</div>`}
    ${voices.map(v => html`<div class="voice-card">
      <div class="vh"><${Icon} n="voice" s=${14} />${v.name}<span class="hint" style="margin-left:auto">${v.total}s</span>
        <button class="btn ghost icon small" title="Rename or delete this voice" onClick=${e => voiceMenu(e, v)}>⋯</button></div>
      <div style="display:flex;gap:4px;flex-wrap:wrap">${v.samples.map(s => html`<span class="chip" title=${`${s.name} — right-click: move to another voice, change mood, delete`} onContextMenu=${e => { e.preventDefault(); sampleMenu(e, v, s); }}>
        <button class="btn ghost icon small" style="width:16px;height:16px" onClick=${() => playFile(s.file)}><${Icon} n="play" s=${9} /></button>
        ${s.mood} ${s.dur ? `${s.dur}s` : ''}
        <button class="btn ghost icon small danger" style="width:16px;height:16px" onClick=${() => del(s.file)}><${Icon} n="x" s=${9} /></button></span>`)}</div>
      ${v.total < 10 && html`<div class="hint">Add at least 10 s of speech for a good clone.</div>`}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="btn small" onClick=${() => A.voiceSampleDialog(S.sel.clips[0], v.name)}>+ Add sample (from a clip or file)</button>
      </div>
    </div>`)}
    <div class="voice-card">
      <div class="vh">New voice</div>
      <input class="input" placeholder="Name, e.g. Ansell" value=${newName} onInput=${e => setNewName(e.target.value)} />
      <label class="check"><input type="checkbox" checked=${consent} onChange=${e => setConsent(e.target.checked)} />
        <span class="hint">This is my voice, or I have the speaker's permission to clone it.</span></label>
      <button class="btn small" disabled=${!newName.trim() || !consent} onClick=${create}>Create voice</button>
    </div>
    <div class="hint">Tip: tag samples by mood (cheerful, serious, curious…). When a narration line uses that tone, the matching sample is used as the reference, which gives the strongest emotional effect. Generated speech carries an inaudible AI watermark.</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn ghost small" onClick=${() => A.open('voices')}><${Icon} n="folder" s=${12} /> Open voices folder</button>
      ${voices.length > 0 && html`<button class="btn ghost small danger" title="Remove every voice and sample to train from scratch (backup kept in cache/trash)" onClick=${resetAll}><${Icon} n="trash" s=${12} /> Reset all voices…</button>`}
    </div>
  </div>`;
}

// ---------------------------------------------------------------- find speakers → pick one → make a voice
export function SpeakersDialog({ close, Dialog }) {
  const voices = useStore(s => s.voices || []);
  const init = S.speakersInit || {};
  const sources = voiceSources();
  const [assetId, setAssetId] = useState(init.asset || sources.find(s => !s.path.includes('_samples'))?.id || sources[0]?.id);
  const [n, setN] = useState(2);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [pick, setPick] = useState(null);
  const [name, setName] = useState('');
  const [consent, setConsent] = useState(false);
  const [mood, setMood] = useState('neutral');
  const [making, setMaking] = useState(false);
  const clip = init.clip ? S.project.clips.find(c => c.id === init.clip) : null;
  const detect = () => {
    setBusy(true); setJob(null); setPick(null);
    api('/api/voices/speakers', clip ? { clip: clip.id, n } : { asset: assetId, n })
      .then(j => { setJob(j); setPick(j.speakers[0]?.id); }).catch(e => toast(e.message, 'error')).finally(() => setBusy(false));
  };
  const exists = voices.some(v => v.name === name.trim());
  const make = () => {
    setMaking(true);
    api('/api/voices/from_speaker', { job: job.id, speaker: pick, voice: name.trim(), consent, mood, clean: true })
      .then(r => { set({ voices: r.voices }); toast(`Voice “${r.voice}” is ready — use it in Narration or the Try-it box`, 'ok'); close(); })
      .catch(e => toast(e.message, 'error')).finally(() => setMaking(false));
  };
  const label = id => `Person ${id.slice(1)}`;
  return html`<${Dialog} title="Find the speakers in a video" width=${640} footer=${job && html`<button class="btn ghost" onClick=${close}>Cancel</button>
      <button class="btn primary" disabled=${making || !pick || !name.trim() || (!exists && !consent)} onClick=${make}>
        ${making ? 'Making the voice…' : `Make voice from ${pick ? label(pick) : '…'}`}</button>`}>
    <div class="hint">Finds who is talking when, so you can clone just one person. Works best when people take turns (little talking over each other).</div>
    ${clip ? html`<div class="row2"><span>Clip</span><span>${S.assets[clip.asset]?.name} (${(clip.out - clip.in).toFixed(1)} s on the timeline)</span></div>`
      : html`<div class="row2"><span>Video / audio</span><select class="input" value=${assetId} onChange=${e => { setAssetId(e.target.value); setJob(null); }}>
          ${sources.length === 0 && html`<option value="">— put a video in this project's import/ folder first —</option>`}
          ${sources.map(a => html`<option value=${a.id}>${a.folder ? a.folder + '/' : ''}${a.name} (${a.meta?.dur ? a.meta.dur.toFixed(0) + ' s' : '…'})</option>`)}</select></div>`}
    <div class="row2"><span>How many people</span><div class="seg">${[[null, 'Auto'], [2, '2'], [3, '3'], [4, '4']].map(([v, l]) =>
      html`<button class=${n === v ? 'on' : ''} onClick=${() => setN(v)}>${l}</button>`)}</div></div>
    <div><button class="btn primary" disabled=${busy || (!clip && !assetId)} onClick=${detect}>${busy ? 'Listening… (a few seconds per minute of video)' : job ? 'Detect again' : 'Find speakers'}</button></div>
    ${job && html`
      <div class="spk-strip" title="Who speaks when">${job.turns.map(([s, e, k]) => html`<i style=${`left:${s / job.dur * 100}%;width:${Math.max(0.3, (e - s) / job.dur * 100)}%;background:${job.speakers.find(x => x.id === k)?.color}`} />`)}</div>
      <div class="spk-cards">${job.speakers.map(sp => html`<label class=${`spk-card ${pick === sp.id ? 'on' : ''}`} style=${`--c:${sp.color}`}>
        <input type="radio" name="spk" checked=${pick === sp.id} onChange=${() => setPick(sp.id)} />
        <div class="spk-h"><span class="dot" />${label(sp.id)}<span class="hint" style="margin-left:auto">${sp.seconds} s talking · ${sp.turns.length} turns</span></div>
        <div style="display:flex;gap:5px;flex-wrap:wrap">${sp.previews.map((p, i) => html`<button class="btn small" onClick=${e => { e.preventDefault(); playFile(p); }}><${Icon} n="play" s=${10} /> Listen ${i + 1}</button>`)}</div>
      </label>`)}</div>
      <div class="hint">Listen to each person and pick yourself. If two people got mixed into one, choose a different “How many people” and detect again.</div>
      <div class="row2"><span>Voice name</span><input class="input" list="voice-names" placeholder="e.g. Ansell" value=${name} onInput=${e => setName(e.target.value)} />
        <datalist id="voice-names">${voices.map(v => html`<option value=${v.name} />`)}</datalist></div>
      <div class="row2"><span>Mood of this speech</span><select class="input" value=${mood} onChange=${e => setMood(e.target.value)}>
        ${(S.ttsStatus?.moods || ['neutral', 'cheerful', 'calm', 'serious', 'curious', 'excited', 'warm', 'dramatic']).map(m => html`<option value=${m}>${m}</option>`)}</select></div>
      ${!exists && html`<label class="check"><input type="checkbox" checked=${consent} onChange=${e => setConsent(e.target.checked)} />
        <span class="hint">This is my voice, or I have this person's permission to clone it.</span></label>`}
      ${exists && html`<div class="hint">Adds this speech to the existing voice “${name.trim()}”.</div>`}`}
  </${Dialog}>`;
}

// ---------------------------------------------------------------- try a voice → MP3 (no timeline needed)
function TryIt() {
  const voices = useStore(s => s.voices || []);
  const results = useStore(s => s.quickTts || {});
  const tones = S.ttsStatus?.tones || {};
  const [text, setText] = useState('Hi! After a busy week in Taiwan, we are finally going to E-DA Theme Park!');
  const [voice, setVoice] = useState('');
  const [tone, setTone] = useState('cheerful');
  const [qid, setQid] = useState(null);
  const [pace, setPace] = useState({ rate: null, pause: 1, steady: true });
  const [fx, setFx] = useState(null);
  const res = qid && results[qid];
  const go = () => api('/api/tts/quick', { text, voice: voice || voices[0]?.name || null, tone, ...pace, fx }).then(r => setQid(r.id)).catch(e => toast(e.message, 'error'));
  return html`<div class="voice-card">
    <div class="vh"><${Icon} n="voice" s=${14} />Try it → MP3</div>
    <textarea class="input" rows="3" value=${text} onInput=${e => setText(e.target.value)} />
    <div style="display:flex;gap:6px">
      <select class="input" value=${voice || voices[0]?.name || ''} onChange=${e => setVoice(e.target.value)}>
        <option value="">Built-in voice</option>${voices.map(v => html`<option value=${v.name}>${v.name}</option>`)}</select>
      <select class="input" value=${tone} onChange=${e => setTone(e.target.value)} style="max-width:120px">
        ${Object.entries(tones).map(([k, v]) => html`<option value=${k}>${v.label}</option>`)}</select>
    </div>
    <${PaceControls} value=${pace} onChange=${setPace} compact=${true} />
    <details class="vfx-details"><summary class="hint" style="cursor:pointer">Voice effects${fx ? ' •' : ''} (filter, noise, space, distance)</summary>
      <${VoiceFxControls} value=${fx} onChange=${setFx} compact=${true} /></details>
    <button class="btn primary" disabled=${!!qid && !res} onClick=${go}>${qid && !res ? 'Generating… (~20–60 s)' : 'Generate'}</button>
    ${res?.error && html`<div class="hint" style="color:var(--danger)">${res.error}</div>`}
    ${res && !res.error && html`<audio controls src=${res.url} style="width:100%;height:32px" />
      <div style="display:flex;gap:6px;align-items:center"><a class="btn small primary" href=${res.url} download=${res.name}><${Icon} n="export" s=${12} /> Download MP3</a>
      <span class="hint">${res.engine === 'elevenlabs' ? 'ElevenLabs' : 'Local'} · ${res.dur?.toFixed(1)} s${res.wpm ? ` · ≈${res.wpm} wpm` : ''}${res.match != null ? ` · voice match ${Math.round(res.match)}%` : ''} · saved in exports/</span></div>`}
  </div>`;
}

export function VoiceSampleDialog({ close, Dialog }) {
  const voices = useStore(s => s.voices || []);
  const init = S.voiceSample || {};
  const c = clipById(init.clip);
  const hasIO = S.inPt != null && S.outPt != null && S.outPt > S.inPt;
  const [voice, setVoice] = useState(init.voice || voices[0]?.name || '');
  const [mood, setMood] = useState('neutral');
  const [range, setRange] = useState(hasIO ? 'io' : 'clip');
  const [clean, setClean] = useState(true);
  const [busy, setBusy] = useState(false);
  const sources = voiceSources();
  const [assetId, setAssetId] = useState(init.asset || (S.sel.asset && sources.some(s => s.id === S.sel.asset) ? S.sel.asset : sources[0]?.id));
  const asset = S.assets[assetId];
  const [t0, setT0] = useState(0);
  const [t1, setT1] = useState(Math.min(asset?.meta?.dur || 30, 30));
  const moods = S.ttsStatus?.moods || ['neutral', 'cheerful', 'excited', 'curious', 'warm', 'calm', 'serious', 'dramatic'];
  const preview = () => {
    if (!asset) return;
    if (!audioEl) audioEl = new Audio();
    audioEl.src = `/files/${asset.path.split('/').map(encodeURIComponent).join('/')}#t=${t0},${t1}`;
    audioEl.play().catch(() => {});
  };
  const go = () => {
    if (!voice) return toast('Create a voice first (AI Voice tab)', 'error');
    const body = { voice, mood, clean };
    if (c) { body.clip = c.id; if (range === 'io') { body.t0 = S.inPt; body.t1 = S.outPt; } }
    else if (asset) { body.asset = asset.id; body.t0 = t0; body.t1 = t1; }
    else return toast("Put a video or audio file with the voice in this project's import/ folder first", 'error');
    setBusy(true);
    api('/api/voices/sample', body).then(r => { set({ voices: r.voices }); toast(`Added sample ${r.file.split('/').pop()}`, 'ok'); close(); })
      .catch(e => toast(e.message, 'error')).finally(() => setBusy(false));
  };
  return html`<${Dialog} title="Use as voice sample" width=${520} footer=${html`<button class="btn ghost" onClick=${close}>Cancel</button>
      <button class="btn primary" disabled=${busy} onClick=${go}>${busy ? 'Extracting…' : 'Add sample'}</button>`}>
    <div class="hint">${c ? `From clip “${S.assets[c.asset]?.name || c.id}” on ${c.track}.` : 'From a file in your assets folder.'}
      Pick a part where only this person talks (no music), 10–30 s is ideal.</div>
    ${!c && html`
      <div class="row2"><span>File</span><select class="input" value=${assetId} onChange=${e => { setAssetId(e.target.value); setT0(0); setT1(Math.min(S.assets[e.target.value]?.meta?.dur || 30, 30)); }}>
        ${sources.length === 0 && html`<option value="">— no video/audio with sound in this project yet —</option>`}
        ${sources.map(a => html`<option value=${a.id}>${a.folder ? a.folder + '/' : ''}${a.name}</option>`)}</select></div>
      <div class="row2"><span>From → to (s)</span><div style="display:flex;gap:6px;align-items:center">
        <input class="input" type="number" min="0" step="0.5" value=${t0} style="width:80px" onInput=${e => setT0(Math.max(0, +e.target.value))} />→
        <input class="input" type="number" min="0" step="0.5" value=${t1} style="width:80px" onInput=${e => setT1(+e.target.value)} />
        <span class="hint">of ${asset?.meta?.dur?.toFixed(1) || '?'} s</span>
        <button class="btn small" onClick=${preview}><${Icon} n="play" s=${10} /> Listen</button></div></div>`}
    <div class="row2"><span>Voice</span>${voices.length ? html`<select class="input" value=${voice} onChange=${e => setVoice(e.target.value)}>
      ${voices.map(v => html`<option value=${v.name}>${v.name}</option>`)}</select>` : html`<span class="hint">Create a voice in Effects ▸ AI Voice first.</span>`}</div>
    <div class="row2"><span>Mood of this sample</span><select class="input" value=${mood} onChange=${e => setMood(e.target.value)}>
      ${moods.map(m => html`<option value=${m}>${m}</option>`)}</select></div>
    ${c && html`<div class="row2"><span>Range</span><div class="seg">
      <button class=${range === 'clip' ? 'on' : ''} onClick=${() => setRange('clip')}>Whole clip (max 90 s)</button>
      <button class=${range === 'io' ? 'on' : ''} disabled=${!hasIO} onClick=${() => setRange('io')}>In → Out${hasIO ? ` (${(S.outPt - S.inPt).toFixed(1)} s)` : ''}</button></div></div>`}
    <label class="check"><input type="checkbox" checked=${clean} onChange=${e => setClean(e.target.checked)} /> Clean up background noise</label>
    <div class="hint">Set In (I) and Out (O) on the timeline to grab just one sentence.</div>
  </${Dialog}>`;
}
