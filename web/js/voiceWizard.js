// "Voice from Video" — one guided window: upload a video → extract the human voices → learn one → narrate your text.
import { html, useState, useRef, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore, toast, snapT } from './store.js';
import { api } from './api.js';
import { Icon } from './util.js';
import { playFile, voiceSources } from './voicePanel.js';
import { Progress } from './progress.js';
import { PaceControls, estimateSecs } from './paceControls.js';

const STEPS = ['Upload video', 'Extract voices', 'Learn voice', 'Narrate'];

function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/upload?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = e => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => { const j = JSON.parse(xhr.responseText || '{}'); xhr.status < 300 ? resolve(j) : reject(new Error(j.detail || 'upload failed')); };
    xhr.onerror = () => reject(new Error('upload failed'));
    xhr.send(file);
  });
}

/** How much speech the AI has to learn from. */
function Quality({ seconds }) {
  const s = seconds || 0;
  const [label, color, tip] = s < 15 ? ['Too little speech', '#ff6b6b', 'The clone will sound generic. Add more speech (another video) — 30 s+ helps a lot.']
    : s < 45 ? ['OK', '#f5a524', 'Usable. 45–120 s of clear speech makes it sound much more like the person.']
    : ['Good', '#3ccf91', 'Enough clean speech for a convincing clone.'];
  return html`<div class="quality" title=${tip}>
    <span style="white-space:nowrap"><b>${Math.round(s)} s</b> of speech</span>
    <div class="meter"><i style=${`width:${Math.min(100, s / 90 * 100)}%;background:${color}`} /></div>
    <span style=${`color:${color};font-weight:600;white-space:nowrap`}>${label}</span>
  </div>`;
}

/** Engine switch + ElevenLabs readiness, inside the wizard. */
function EnginePicker() {
  const cfg = useStore(s => s.ttsStatus?.config) || {};
  const caps = useStore(s => s.elCaps);
  const [checking, setChecking] = useState(false);
  const el = cfg.engine === 'elevenlabs';
  const save = patch => api('/api/tts/config', patch).then(c => set(s => ({ ttsStatus: { ...(s.ttsStatus || {}), config: c } })));
  const check = () => { setChecking(true); api('/api/tts/elevenlabs/check', {}).then(c => set({ elCaps: c })).catch(e => set({ elCaps: { problems: [e.message] } })).finally(() => setChecking(false)); };
  useEffect(() => { if (el && cfg.key_set && !caps) check(); }, [el]);
  return html`<div style="display:grid;gap:8px">
    <div class="row2"><span>Voice engine</span><div class="seg">
      <button class=${!el ? 'on' : ''} onClick=${() => save({ engine: 'local' })}>Local (free)</button>
      <button class=${el ? 'on' : ''} onClick=${() => save({ engine: 'elevenlabs' })}>ElevenLabs (best quality)</button></div></div>
    ${el && !cfg.key_set && html`<div class="notice warn">No ElevenLabs API key saved yet — add it in Effects ▸ AI Voice ▸ Voice engine.</div>`}
    ${el && cfg.key_set && checking && html`<div class="hint">Checking your ElevenLabs account…</div>`}
    ${el && cfg.key_set && caps && !checking && (caps.problems?.length
      ? html`<div class="notice warn"><b>ElevenLabs can't clone this voice yet:</b><ul style="margin:6px 0 0 16px;padding:0">${caps.problems.map(p => html`<li>${p}</li>`)}</ul>
          <div style="margin-top:6px">Until then, lines are made with the local voice (fallback). <button class="btn small" onClick=${check}>Check again</button></div></div>`
      : html`<div class="notice ok">ElevenLabs is ready${caps.credits ? ` · ${caps.credits.left.toLocaleString()} credits left (${caps.credits.tier})` : ''}.</div>`)}
    ${!el && html`<div class="hint">Local runs free on your PC (~20–60 s per line). For the most natural, closest-sounding voice use ElevenLabs.</div>`}
  </div>`;
}

export function VoiceWizard({ close, Dialog }) {
  const init = S.wizardInit || {};
  const voices = useStore(s => s.voices || []);
  const quick = useStore(s => s.quickTts || {});
  const jobs = useStore(s => s.ttsJobs || {});
  const task = useStore(s => s.task);
  const assets = useStore(s => s.assets);
  const tones = S.ttsStatus?.tones || {};
  const [step, setStep] = useState(init.rebuild ? 0 : init.voice ? 3 : init.asset ? 1 : 0);
  const [assetId, setAssetId] = useState(init.asset || null);
  const [up, setUp] = useState(null);
  const [isolate, setIsolate] = useState(true);
  const [n, setN] = useState(init.rebuild ? 1 : 2);
  const [busy, setBusy] = useState(false);
  const [busySince, setBusySince] = useState(null);
  const [job, setJob] = useState(null);
  const [pick, setPick] = useState(null);
  const [name, setName] = useState(init.rebuild || init.addTo || '');
  const [consent, setConsent] = useState(false);
  const [replace, setReplace] = useState(true);
  const [voice, setVoice] = useState(init.voice || null);
  const [text, setText] = useState('');
  const [tone, setTone] = useState('neutral');
  const [intensity, setIntensity] = useState(0.5);
  const [pace, setPace] = useState({ rate: null, pause: 1, steady: true });
  const [qid, setQid] = useState(null);
  const fileRef = useRef();
  const sources = voiceSources();
  const asset = assets[assetId];
  const res = qid && quick[qid];
  const qjob = qid && jobs[qid];
  const vinfo = voices.find(v => v.name === (voice || name.trim()));
  const picked = job?.speakers.find(s => s.id === pick);

  const onFile = async f => {
    if (!f) return;
    setUp(0);
    try {
      const r = await upload(f, setUp);
      setAssetId(r.asset); setUp(null); setJob(null);
      toast(`Uploaded ${r.name}`, 'ok');
      setStep(1);
    } catch (e) { setUp(null); toast(e.message, 'error'); }
  };
  const extract = () => {
    setBusy(true); setBusySince(Date.now()); setJob(null); setPick(null); set({ task: null });
    api('/api/voices/speakers', { asset: assetId, n, isolate })
      .then(j => { setJob(j); setPick(j.speakers[0]?.id); }).catch(e => toast(e.message, 'error')).finally(() => setBusy(false));
  };
  const learn = () => {
    setBusy(true); setBusySince(Date.now());
    api('/api/voices/from_speaker', { job: job.id, speaker: pick, voice: name.trim(), consent, mood: 'neutral', clean: false, replace: exists && replace })
      .then(r => { set({ voices: r.voices }); setVoice(r.voice); setStep(3); toast(`Voice “${r.voice}” learned`, 'ok'); })
      .catch(e => toast(e.message, 'error')).finally(() => setBusy(false));
  };
  const narrate = () => api('/api/tts/quick', { text, voice, tone, intensity, ...pace }).then(r => setQid(r.id)).catch(e => toast(e.message, 'error'));
  const place = () => api('/api/tts/place', { file: res.file, start: snapT(S.t), text, voice, tone, intensity, ...pace })
    .then(r => { set({ project: r.project, history: r.history }); toast('Narration added to the Narration track at the playhead', 'ok'); })
    .catch(e => toast(e.message, 'error'));
  const addMore = () => { setName(voice); setJob(null); setPick(null); setAssetId(null); setStep(0); };
  const exists = voices.some(v => v.name === name.trim());
  const pName = id => `Person ${id.slice(1)}`;
  const generating = qid && !res;

  const footer = html`
    ${step > 0 && !busy && !generating && html`<button class="btn ghost" onClick=${() => setStep(step - 1)}>Back</button>`}
    <span style="flex:1" />
    ${step === 0 && html`<button class="btn primary" disabled=${!assetId || up != null} onClick=${() => setStep(1)}>Next: extract voices</button>`}
    ${step === 1 && html`<button class="btn primary" disabled=${!pick || busy} onClick=${() => setStep(2)}>Next: use ${pick ? pName(pick) : '…'}</button>`}
    ${step === 2 && html`<button class="btn primary" disabled=${busy || !name.trim() || (!exists && !consent)} onClick=${learn}>${busy ? 'Learning…' : exists ? (replace ? `Rebuild “${name.trim()}”` : `Add to “${name.trim()}”`) : 'Learn this voice'}</button>`}
    ${step === 3 && html`<button class="btn" onClick=${close}>Done</button>`}`;

  return html`<${Dialog} title="Voice from Video" width=${720} footer=${footer}>
    <div class="wiz-steps">${STEPS.map((s, i) => html`<div class=${`wiz-step ${i === step ? 'on' : i < step ? 'done' : ''}`}><b>${i < step ? '✓' : i + 1}</b>${s}</div>`)}</div>

    ${step === 0 && html`
      ${init.addTo || name ? html`<div class="notice ok">Adding more speech to the voice “${name || init.addTo}”. Upload another video where this person talks.</div>` : ''}
      ${up == null ? html`<div class="wiz-drop" onClick=${() => fileRef.current.click()}
          onDragOver=${e => e.preventDefault()} onDrop=${e => { e.preventDefault(); onFile(e.dataTransfer.files[0]); }}>
        <${Icon} n="export" s=${30} />
        <div style="font-size:14px"><b>Upload a video</b> with the voice you want</div>
        <div class="hint">Click to choose, or drag the file here · mp4, mov, m4a, mp3, wav… · saved in this project's assets/video</div>
        <input type="file" ref=${fileRef} accept="video/*,audio/*" style="display:none" onChange=${e => onFile(e.target.files[0])} />
      </div>` : html`<${Progress} value=${up} stage="Uploading the video" />`}
      ${sources.length > 0 && up == null && html`<div class="row2"><span>Or use a video already in the project</span>
        <select class="input" value=${assetId || ''} onChange=${e => { setAssetId(e.target.value || null); setJob(null); if (e.target.value) setStep(1); }}>
          <option value="">— choose —</option>${sources.map(a => html`<option value=${a.id}>${a.folder ? a.folder + '/' : ''}${a.name}${a.meta?.dur ? ` (${Math.round(a.meta.dur)} s)` : ''}</option>`)}</select></div>`}`}

    ${step === 1 && html`
      <div class="hint">Video: <b>${asset?.name}</b>${asset?.meta?.dur ? ` (${Math.round(asset.meta.dur)} s)` : ''}. The AI separates the human voices from music and background sound, then works out who speaks when.</div>
      ${!busy && !job && html`
        <label class="check"><input type="checkbox" checked=${isolate} onChange=${e => setIsolate(e.target.checked)} /> Remove music & background sound (recommended)</label>
        <div class="row2"><span>People talking</span><div class="seg">${[[1, '1'], [2, '2'], [3, '3'], [4, '4'], [null, 'Auto']].map(([v, l]) =>
          html`<button class=${n === v ? 'on' : ''} onClick=${() => setN(v)}>${l}</button>`)}</div></div>
        <div><button class="btn primary" style="height:40px;padding:0 20px;font-size:14px" onClick=${extract}><${Icon} n="voice" s=${16} /> Extract voices</button></div>`}
      ${busy && html`<${Progress} value=${task?.name === 'Extracting voices' ? task.value : 0.01} stage=${task?.stage || 'Starting…'} since=${busySince} />`}
      ${job && !busy && html`
        <div class="spk-strip" title="Who speaks when">${job.turns.map(([s, e, k]) => html`<i style=${`left:${s / job.dur * 100}%;width:${Math.max(0.3, (e - s) / job.dur * 100)}%;background:${job.speakers.find(x => x.id === k)?.color}`} />`)}</div>
        <div class="spk-cards">${job.speakers.map(sp => html`<label class=${`spk-card ${pick === sp.id ? 'on' : ''}`} style=${`--c:${sp.color}`}>
          <input type="radio" name="wspk" checked=${pick === sp.id} onChange=${() => setPick(sp.id)} />
          <div class="spk-h"><span class="dot" />${pName(sp.id)}<span class="hint" style="margin-left:auto">${sp.seconds} s of speech</span></div>
          <div style="display:flex;gap:5px;flex-wrap:wrap">${sp.previews.map((p, i) => html`<button class="btn small" onClick=${e => { e.preventDefault(); playFile(p); }}><${Icon} n="play" s=${10} /> Listen ${i + 1}</button>`)}</div>
        </label>`)}</div>
        <div style="display:flex;gap:8px;align-items:center"><span class="hint" style="flex:1">Listen and pick the person you want. Mixed up? Change the number of people and extract again.</span>
          <button class="btn small" onClick=${() => setJob(null)}>Extract again</button></div>`}`}

    ${step === 2 && html`
      <div class="hint">The AI learns ${pick ? pName(pick) : 'the voice'} from their clean speech (up to 2 minutes).</div>
      ${picked && html`<${Quality} seconds=${picked.seconds + (exists ? (voices.find(v => v.name === name.trim())?.total || 0) : 0)} />`}
      <div class="row2"><span>Name this voice</span><input class="input" list="wiz-voices" placeholder="e.g. Ansell" value=${name} onInput=${e => setName(e.target.value)} />
        <datalist id="wiz-voices">${voices.map(v => html`<option value=${v.name} />`)}</datalist></div>
      ${!exists ? html`<label class="check"><input type="checkbox" checked=${consent} onChange=${e => setConsent(e.target.checked)} />
          <span class="hint">This is my voice, or I have this person's permission to clone it.</span></label>`
        : html`<label class="check"><input type="checkbox" checked=${replace} onChange=${e => setReplace(e.target.checked)} />
            <span class="hint"><b>Rebuild “${name.trim()}” from this recording</b> (replace its old samples — best when the old ones were noisy, enhanced or the wrong person). Untick to add this speech to it instead.</span></label>`}
      <div class="hint">Tip: use the <b>original</b> recording of the person. "Enhanced" or AI-cleaned versions change how the voice sounds, and the clone copies that.</div>
      ${busy && html`<${Progress} stage="Cutting out the clean speech and learning the voice" since=${busySince} estimate=${4} />`}`}

    ${step === 3 && html`
      <div style="display:flex;gap:10px;align-items:center"><span>Voice: <b>${voice}</b></span><span style="flex:1"><${Quality} seconds=${vinfo?.total} /></span>
        <button class="btn small" title="Upload another video of this person to improve the likeness" onClick=${addMore}>+ Add more speech</button></div>
      <${EnginePicker} />
      <textarea class="input" rows="4" placeholder="Type what the voice should say, e.g. After a challenging week as engineers in Taiwan, we're finally heading to E-DA Theme Park!" value=${text} onInput=${e => setText(e.target.value)} />
      <div style="display:flex;gap:4px;flex-wrap:wrap">${Object.entries(tones).map(([k, v]) => html`<button class=${`chip ${tone === k ? 'on' : ''}`} style="border:0;cursor:pointer" onClick=${() => setTone(k)}>${v.label}</button>`)}</div>
      <div class="row2"><span>Emotion ${Math.round(intensity * 100)}%</span><input type="range" min="0" max="1" step="0.05" value=${intensity} style=${`--fill:${intensity * 100}%`} onInput=${e => setIntensity(+e.target.value)} /></div>
      <${PaceControls} value=${pace} onChange=${setPace} />
      <div class="hint">≈ ${estimateSecs(text, pace.rate, pace.pause).toFixed(1)} s spoken</div>
      ${!generating && html`<div><button class="btn primary" style="height:40px;padding:0 20px;font-size:14px" disabled=${!text.trim()} onClick=${narrate}>
        <${Icon} n="voice" s=${16} /> ${res ? 'Generate again' : 'Generate narration'}</button></div>`}
      ${generating && html`<${Progress} stage=${qjob?.stage || 'Waiting in the queue'} since=${qjob?.stage_t ? qjob.stage_t * 1000 : null} estimate=${qjob?.estimate || 30} />`}
      ${res?.error && html`<div class="notice warn">${res.error}</div>`}
      ${res && !res.error && !generating && html`<div class="result-card">
        <div style="display:flex;justify-content:space-between;font-size:12.5px"><b>Your narration is ready</b>
          <span class="hint">${res.engine === 'elevenlabs' ? 'Made with ElevenLabs' : 'Made with the local engine'} · ${res.dur?.toFixed(1)} s</span></div>
        <audio controls autoplay src=${res.url} style="width:100%;height:36px" />
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <a class="btn primary" href=${res.url} download=${res.name}><${Icon} n="export" s=${13} /> Download MP3</a>
          <button class="btn" onClick=${place}><${Icon} n="plus" s=${13} /> Add to timeline at playhead</button></div>
      </div>`}`}
  </${Dialog}>`;
}
