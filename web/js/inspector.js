import { html, useState, useEffect, useRef } from '../vendor/preact-htm.js';
import { S, set, useStore, clipById, trackById, fps, toast } from './store.js';
import { op, api } from './api.js';
import { A } from './actions.js';
import { player } from './player.js';
import { clipDur, prop } from './evaluate.js';
import { livePatch, commitPatch, liveProps, commitProps } from './edit.js';
import { Icon, tc, dur, bytes, kindColor } from './util.js';
import { playFile } from './voicePanel.js';
import { PaceControls, estimateSecs } from './paceControls.js';
import { VoiceFxControls } from './voiceFxControls.js';
import { hasSentences, sentenceTimes, moved, overlapsTalk, applyTimes, resetTiming } from './sentences.js';

// ---------------------------------------------------------------- live preview + commit
const live = livePatch;
const commit = commitPatch;
const nest = (path, v) => path.split('.').reverse().reduce((acc, k) => ({ [k]: acc }), v);

// ---------------------------------------------------------------- controls
function KeyButtons({ anim }) {
  if (!anim) return null;
  return html`<span class="kf">
    ${anim.on && html`<button class="kf-nav" title="Previous keyframe" onClick=${anim.prev}>‹</button>`}
    <button class=${`kf-btn ${anim.on ? 'on' : ''} ${anim.here ? 'here' : ''}`}
      title=${anim.on ? (anim.here ? 'Keyframe here (click the stopwatch off to stop animating — right-click removes this key)' : 'Add keyframe here') : 'Animate this property (keyframes)'}
      onClick=${anim.on && !anim.here ? anim.add : anim.toggle} onContextMenu=${e => { e.preventDefault(); anim.here && anim.remove(); }}>◆</button>
    ${anim.on && html`<button class="kf-nav" title="Next keyframe" onClick=${anim.next}>›</button>`}
    ${anim.on && html`<button class="kf-nav off" title="Stop animating (keep current value)" onClick=${anim.toggle}>✕</button>`}
  </span>`;
}

function Slider({ label, value, min, max, step = 0.01, scale = 1, unit = '', digits = 2, onLive, onCommit, reset, anim }) {
  const fill = ((value - min) / (max - min)) * 100;
  const shown = +(value * scale).toFixed(digits);
  return html`<div class=${`field ${anim ? 'animatable' : ''}`}>
    <label title=${label} onDblClick=${() => reset != null && onCommit(reset)}>${label}<${KeyButtons} anim=${anim} /></label>
    <input type="range" min=${min} max=${max} step=${step} value=${value} style=${`--fill:${fill}%`}
      onInput=${e => onLive(+e.target.value)} onChange=${e => onCommit(+e.target.value)} onDblClick=${() => reset != null && onCommit(reset)} />
    <input class="num" value=${`${shown}${unit}`} onChange=${e => { const v = parseFloat(e.target.value); if (!isNaN(v)) onCommit(v / scale); }} />
  </div>`;
}
function Section({ title, children, actions, start = true, id }) {
  const [open, setOpen] = useState(start);
  return html`<div class=${`section ${open ? '' : 'closed'}`} data-section=${id}>
    <div class="section-head" onClick=${() => setOpen(!open)}><span class="chev"><${Icon} n="chev" s=${14} /></span>${title}
      ${actions && html`<span class="actions" onClick=${e => e.stopPropagation()}>${actions}</span>`}</div>
    <div class="section-body">${children}</div>
  </div>`;
}
function Seg({ value, options, onChange }) {
  return html`<div class="seg">${options.map(([v, l]) => html`<button class=${value === v ? 'on' : ''} onClick=${() => onChange(v)}>${l}</button>`)}</div>`;
}
const bind = (ids, c, path, label) => {
  const get = path.split('.').reduce((o, k) => o?.[k], c);
  return { value: get, onLive: v => live(ids, nest(path, v)), onCommit: v => commit(ids, nest(path, v), label) };
};
/** Keyframe-aware binding: value at the playhead, edits auto-key when animated, ◆ controls. */
const bindAnim = (ids, c, path, label) => {
  const ks = c.keys?.[path] || [];
  const rel = S.t - c.start, half = 0.5 / fps();
  const seekKey = dir => {
    const k = dir < 0 ? [...ks].reverse().find(x => x.t < rel - half) : ks.find(x => x.t > rel + half);
    if (k) player.seek(c.start + k.t);
  };
  return {
    value: prop(c, path, S.t) ?? 0,
    onLive: v => liveProps(ids, { [path]: v }),
    onCommit: v => commitProps(ids, { [path]: v }, label),
    anim: {
      on: ks.length > 0, here: ks.some(k => Math.abs(k.t - rel) <= half),
      toggle: () => op('toggle_anim', { id: c.id, path, t: S.t }, ks.length ? 'Stop Animating' : 'Animate'),
      add: () => op('set_key', { id: c.id, path, t: S.t }, 'Add Keyframe'),
      remove: () => op('remove_key', { id: c.id, path, t: S.t }, 'Remove Keyframe'),
      prev: () => seekKey(-1), next: () => seekKey(1),
    },
  };
};

// ---------------------------------------------------------------- sections
function MotionSection({ ids, c }) {
  const m = c.motion;
  return html`<${Section} title="Motion" actions=${html`<button class="btn ghost icon small" title="Reset" onClick=${A.resetMotion}><${Icon} n="reset" s=${13} /></button>`}>
    <div class="field wide"><label>Fit</label><${Seg} value=${m.fit} options=${[['fit', 'Fit'], ['fill', 'Fill'], ['none', '100%']]}
      onChange=${v => commit(ids, { motion: { fit: v } }, 'Fit')} /></div>
    <${Slider} label="Position X" min=${-1080} max=${1080} step=${1} digits=${0} unit="px" reset=${0} ...${bindAnim(ids, c, 'motion.x', 'Position')} />
    <${Slider} label="Position Y" min=${-1920} max=${1920} step=${1} digits=${0} unit="px" reset=${0} ...${bindAnim(ids, c, 'motion.y', 'Position')} />
    <${Slider} label="Scale" min=${0.1} max=${4} step=${0.01} scale=${100} digits=${0} unit="%" reset=${1} ...${bindAnim(ids, c, 'motion.scale', 'Scale')} />
    <${Slider} label="Rotation" min=${-180} max=${180} step=${0.5} digits=${1} unit="°" reset=${0} ...${bindAnim(ids, c, 'motion.rot', 'Rotation')} />
    <${Slider} label="Opacity" min=${0} max=${1} step=${0.01} scale=${100} digits=${0} unit="%" reset=${1} ...${bindAnim(ids, c, 'motion.opacity', 'Opacity')} />
    <div class="hint">Tip: drag, scale (corners) and rotate (top knob) right in the monitor. ◆ animates a property with keyframes.</div>
  </${Section}>`;
}
function CropSection({ ids, c }) {
  return html`<${Section} title="Crop" start=${Object.values(c.crop || {}).some(v => v > 0)}>
    ${[['l', 'Left'], ['r', 'Right'], ['t', 'Top'], ['b', 'Bottom']].map(([k, l]) => html`<${Slider} label=${l} min=${0} max=${0.9} step=${0.005} scale=${100} digits=${1} unit="%" reset=${0} ...${bindAnim(ids, c, `crop.${k}`, 'Crop')} />`)}
    <div class="hint">Or drag the square handles on the box edges in the monitor.</div>
  </${Section}>`;
}
function SpeedSection({ ids, c }) {
  const frozen = c.hold != null;
  return html`<${Section} title=${frozen ? 'Freeze frame & Fades' : 'Speed & Fades'}>
    ${frozen && html`<div class="hint" style="display:flex;gap:6px;align-items:center"><${Icon} n="snow" s=${13} />Holds the frame at ${c.hold.toFixed(2)} s of the source. Drag its edge on the timeline to change how long.</div>`}
    ${c.type === 'media' && !c.still && !frozen && html`
      <${Slider} label="Speed" min=${0.25} max=${4} step=${0.05} scale=${100} digits=${0} unit="%" reset=${1}
        value=${c.speed} onLive=${() => {}} onCommit=${v => op('set_speed', { ids, speed: v }, 'Speed')} />
      <div class="field wide"><label>Options</label><div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class=${`btn small ${c.reverse ? 'on' : ''}`} onClick=${() => op('set_speed', { ids, reverse: !c.reverse }, 'Reverse')}>Reverse</button>
        <button class=${`btn small ${c.keep_pitch !== false ? 'on' : ''}`} title="Keep the voice pitch when speeding up / slowing down" onClick=${() => op('set_speed', { ids, keep_pitch: c.keep_pitch === false }, 'Keep Pitch')}>Keep pitch</button>
        <button class="btn small" onClick=${A.speedDialog}>Speed/Duration…</button>
        <button class="btn small" title="Insert a 2 s freeze frame at the playhead" onClick=${() => A.freeze('insert', 2)}><${Icon} n="snow" s=${12} /> Freeze</button>
      </div></div>`}
    <${Slider} label="Fade in" min=${0} max=${5} step=${0.05} digits=${2} unit="s" reset=${0} ...${bind(ids, c, 'fade_in', 'Fade in')} />
    <${Slider} label="Fade out" min=${0} max=${5} step=${0.05} digits=${2} unit="s" reset=${0} ...${bind(ids, c, 'fade_out', 'Fade out')} />
  </${Section}>`;
}
function ColorSection({ ids, c }) {
  const def = S.presets.color.params;
  const changed = Object.keys(c.color || {}).length > 0;
  return html`<${Section} title="Color" start=${changed}
      actions=${html`<button class="btn ghost small" title="Save this clip's color + LUT + filters as one of ★ My looks" onClick=${() => A.saveLook(c.id)}>★ Save look</button>
        <button class="btn ghost icon small" title="Reset color" onClick=${() => commit(ids, { color: Object.fromEntries(Object.entries(def).map(([k, d]) => [k, d.default])) }, 'Reset Color')}><${Icon} n="reset" s=${13} /></button>`}>
    ${Object.entries(def).map(([k, d]) => html`<${Slider} label=${d.label} min=${d.min} max=${d.max} step=${d.step} reset=${d.default}
      value=${c.color?.[k] ?? d.default} onLive=${v => live(ids, { color: { [k]: v } })} onCommit=${v => commit(ids, { color: { [k]: v } }, d.label)} />`)}
  </${Section}>`;
}
function FiltersSection({ ids, c }) {
  const defs = Object.fromEntries(S.presets.filters.map(f => [f.id, f]));
  const fl = c.filters || [];
  const setF = (i, patch, label, isLive) => {
    const next = fl.map((f, j) => j === i ? { ...f, ...patch } : f);
    isLive ? live(ids, { filters: next }) : commit(ids, { filters: next }, label);
  };
  const move = (i, d) => { const n = [...fl]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); commit(ids, { filters: n }, 'Reorder Filters'); };
  return html`<${Section} title=${`Filters${fl.length ? ` (${fl.length})` : ''}`}>
    ${fl.length === 0 && html`<div class="hint">No filters. Click a Look or Effect in the Effects panel, or drag one onto the clip.</div>`}
    ${fl.map((f, i) => { const d = defs[f.type]; if (!d) return null; return html`<div class="filter-card">
      <div class="top"><span class="name" style=${f.enabled === false ? 'opacity:.5' : ''}>${d.lut ? `LUT · ${(S.luts || []).find(l => l.file === f.file)?.name || (f.file || 'none').split('/').pop()}` : d.name}</span>
        <button class="btn ghost icon small" title="Move up" disabled=${i === 0} onClick=${() => move(i, -1)}><${Icon} n="up" s=${13} /></button>
        <button class="btn ghost icon small" title="Move down" disabled=${i === fl.length - 1} onClick=${() => move(i, 1)}><${Icon} n="down" s=${13} /></button>
        <button class="btn ghost icon small" title=${f.enabled === false ? 'Enable' : 'Bypass'} onClick=${() => setF(i, { enabled: f.enabled === false }, 'Toggle Filter')}><${Icon} n=${f.enabled === false ? 'eyeoff' : 'eye'} s=${13} /></button>
        <button class="btn ghost icon small danger" title="Remove" onClick=${() => commit(ids, { filters: fl.filter((_, j) => j !== i) }, 'Remove Filter')}><${Icon} n="x" s=${13} /></button></div>
      ${d.lut && html`<div class="field wide"><label>LUT file</label><select class="input" value=${f.file} onChange=${e => setF(i, { file: e.target.value }, 'Change LUT')}>
        ${!(S.luts || []).some(l => l.file === f.file) && html`<option value=${f.file}>${(f.file || 'missing').split('/').pop()} (missing)</option>`}
        ${(S.luts || []).filter(l => !l.error).map(l => html`<option value=${l.file}>${l.name}</option>`)}</select></div>`}
      ${Object.entries(d.params).map(([k, p]) => p.options
        ? html`<div class="field wide"><label>${p.label}</label><select class="input" value=${f[k] ?? p.default} onChange=${e => setF(i, { [k]: +e.target.value }, d.name)}>
            ${p.options.map((o, j) => html`<option value=${p.min + j * (p.step || 1)}>${o}</option>`)}</select></div>`
        : html`<${Slider} label=${p.label} min=${p.min} max=${p.max} step=${p.step} reset=${p.default}
        value=${f[k] ?? p.default} onLive=${v => setF(i, { [k]: v }, '', true)} onCommit=${v => setF(i, { [k]: v }, d.name)} />`)}
    </div>`; })}
  </${Section}>`;
}
function AudioSection({ ids, c, linked = false }) {
  // linked = the sound of a selected video clip (A1): no Speed here — the video's Speed section moves both together
  return html`<${Section} title=${linked ? `Sound (${c.track}, linked)` : 'Audio'}>
    <${Slider} label="Volume" min=${-40} max=${12} step=${0.5} digits=${1} unit=" dB" reset=${0} ...${bindAnim(ids, c, 'volume_db', 'Volume')} />
    <${Slider} label="Fade in" min=${0} max=${5} step=${0.05} digits=${2} unit="s" reset=${0} ...${bind(ids, c, 'fade_in', 'Fade in')} />
    <${Slider} label="Fade out" min=${0} max=${5} step=${0.05} digits=${2} unit="s" reset=${0} ...${bind(ids, c, 'fade_out', 'Fade out')} />
    ${!linked && c.type === 'media' && !c.still && html`<${Slider} label="Speed" min=${0.25} max=${4} step=${0.05} scale=${100} digits=${0} unit="%" reset=${1}
      value=${c.speed} onLive=${() => {}} onCommit=${v => commit(ids, { speed: v }, 'Speed')} />`}
    ${linked && html`<div class="hint">This clip's own sound. For a whole track (all footage sound, all music) click an empty spot of the timeline → Audio mix, or use Audio ▸ Audio Mix…</div>`}
  </${Section}>`;
}
function TextSection({ ids, c }) {
  const s = c.text.style, an = c.text.anim;
  const [draft, setDraft] = useState(null);
  const [orig, setOrig] = useState(null);
  const ta = useRef();
  useEffect(() => {                                   // double-click text in the monitor → edit here
    const f = () => { ta.current?.focus(); ta.current?.select(); };
    window.addEventListener('vs-edit-text', f);
    return () => window.removeEventListener('vs-edit-text', f);
  }, []);
  const m = c.meta;
  return html`
  <${Section} title="Text">
    ${m?.lang && html`<div class="hint">Subtitle · spoken in ${({ en: 'English', id: 'Indonesian', zh: 'Mandarin' })[m.lang] || m.lang}${m.original ? html`<br/>Original: “${m.original}”` : ''}</div>`}
    <textarea class="input" rows="3" ref=${ta} value=${draft ?? c.text.content}
      onFocus=${() => setOrig(c.text.content)}
      onInput=${e => { setDraft(e.target.value); live(ids, { text: { content: e.target.value } }); }}
      onBlur=${e => { setDraft(null); if (e.target.value !== orig) commit(ids, { text: { content: e.target.value } }, 'Edit Text'); }} />
    <div class="field wide"><label>Weight</label><${Seg} value=${s.weight} options=${[[400, 'Regular'], [500, 'Medium'], [700, 'Bold']]} onChange=${v => commit(ids, { text: { style: { weight: v } } }, 'Font Weight')} /></div>
    <${Slider} label="Size" min=${16} max=${240} step=${1} digits=${0} unit="px" ...${bind(ids, c, 'text.style.size', 'Font Size')} />
    <div class="field wide"><label>Color</label><input type="color" class="color-input" value=${s.color.slice(0, 7)} onInput=${e => live(ids, { text: { style: { color: e.target.value } } })} onChange=${e => commit(ids, { text: { style: { color: e.target.value.toUpperCase() } } }, 'Text Color')} /></div>
    <${Slider} label="Outline" min=${0} max=${16} step=${1} digits=${0} unit="px" reset=${0} ...${bind(ids, c, 'text.style.outline', 'Outline')} />
    <div class="field wide"><label>Outline color</label><input type="color" class="color-input" value=${(s.outline_color || '#000000').slice(0, 7)} onChange=${e => commit(ids, { text: { style: { outline_color: e.target.value.toUpperCase() } } }, 'Outline Color')} /></div>
    <${Slider} label="Shadow" min=${0} max=${30} step=${1} digits=${0} unit="px" reset=${0} ...${bind(ids, c, 'text.style.shadow', 'Shadow')} />
    <div class="field wide"><label>Background</label><${Seg} value=${!!s.box} options=${[[false, 'None'], [true, 'Box']]} onChange=${v => commit(ids, { text: { style: { box: v } } }, 'Text Box')} /></div>
    <div class="field wide"><label>Align</label><${Seg} value=${s.align} options=${[['left', 'Left'], ['center', 'Center'], ['right', 'Right']]} onChange=${v => commit(ids, { text: { style: { align: v } } }, 'Align')} /></div>
    <${Slider} label="Letter spacing" min=${-5} max=${30} step=${0.5} digits=${1} reset=${0} ...${bind(ids, c, 'text.style.spacing', 'Spacing')} />
    <${Slider} label="Position X" min=${-0.5} max=${1.5} step=${0.001} scale=${100} digits=${1} unit="%" ...${bindAnim(ids, c, 'text.x', 'Text Position')} />
    <${Slider} label="Position Y" min=${-0.5} max=${1.5} step=${0.001} scale=${100} digits=${1} unit="%" ...${bindAnim(ids, c, 'text.y', 'Text Position')} />
    <${Slider} label="Scale" min=${0.1} max=${4} step=${0.01} scale=${100} digits=${0} unit="%" reset=${1} ...${bindAnim(ids, c, 'motion.scale', 'Scale')} />
    <${Slider} label="Rotation" min=${-180} max=${180} step=${0.5} digits=${1} unit="°" reset=${0} ...${bindAnim(ids, c, 'motion.rot', 'Rotation')} />
  </${Section}>
  <${Section} title="Animation">
    <div class="field wide"><label>In</label><select class="input" value=${an.in} onChange=${e => commit(ids, { text: { anim: { in: e.target.value } } }, 'Text Animation')}>
      ${S.presets.text_animations.map(a => html`<option value=${a}>${a.replace('_', ' ')}</option>`)}</select></div>
    <${Slider} label="In duration" min=${0} max=${4} step=${0.05} digits=${2} unit="s" ...${bind(ids, c, 'text.anim.in_dur', 'Animation')} />
    <div class="field wide"><label>Out</label><${Seg} value=${an.out} options=${[['none', 'None'], ['fade', 'Fade']]} onChange=${v => commit(ids, { text: { anim: { out: v } } }, 'Text Animation')} /></div>
    <${Slider} label="Out duration" min=${0} max=${4} step=${0.05} digits=${2} unit="s" ...${bind(ids, c, 'text.anim.out_dur', 'Animation')} />
    <${Slider} label="Duration" min=${0.3} max=${30} step=${0.1} digits=${1} unit="s" value=${c.dur} onLive=${() => {}}
      onCommit=${v => op('trim', { id: c.id, edge: 'end', t: c.start + v }, 'Text Duration')} />
    ${c.text.times && html`<div class="hint">Typed with per-letter timing (from the Typed Intro generator).</div>`}
  </${Section}>`;
}
// ---------------------------------------------------------------- captions (word-timed, templated)
const FONTS = () => [...new Set(S.presets.fonts.map(f => f.family))];
function CaptionSection({ ids, c }) {
  const cap = c.text.caption, s = cap.style || {}, m = c.meta || {};
  const [draft, setDraft] = useState(null);
  const ta = useRef();
  useEffect(() => {
    const f = () => { ta.current?.focus(); ta.current?.select(); };
    window.addEventListener('vs-edit-text', f);
    return () => window.removeEventListener('vs-edit-text', f);
  }, []);
  const tpls = S.presets.caption_templates || [];
  const restyle = (overrides, label) => op('restyle_captions', { ids, overrides }, label);
  const words = cap.words || [];
  const needs = m.review?.length && !m.review_ok;
  const editText = () => words.map(w => w.emph ? `*${w.w}*` : w.w).join(' ');
  const rel = S.t - c.start;
  const weights = S.presets.fonts.filter(f => f.family === s.font).map(f => f.weight);
  return html`
  <${Section} title="Caption">
    ${m.lang && html`<div class="hint">Spoken in ${({ en: 'English', id: 'Indonesian', zh: 'Mandarin' })[m.lang] || m.lang}${m.original ? html`<br/>Original: “${m.original}”` : ''}</div>`}
    ${needs ? html`<div class="review-box"><b>Please check:</b> ${m.review.join(' · ')}
        <div style="display:flex;gap:6px;margin-top:6px"><button class="btn small" onClick=${() => { player.seek(c.start); player.play(); setTimeout(() => player.pause(), (c.dur + 0.3) * 1000); }}><${Icon} n="play" s=${12} /> Listen</button>
        <button class="btn small primary" onClick=${() => op('set_review', { ids: [c.id], ok: true }, 'Caption checked')}>✓ Looks right</button></div></div>` : ''}
    <div class="cap-words" title="Word timing — the highlighted word is the one at the playhead; dotted = Whisper wasn't sure">
      ${words.map(w => html`<span class=${`cw ${rel >= w.t0 && rel < w.t1 + 0.05 ? 'now' : ''} ${(w.conf ?? 1) < 0.4 ? 'low' : ''} ${w.emph ? 'em' : ''}`}
        onClick=${() => player.seek(c.start + w.t0 + 0.01)}>${w.w}</span>`)}
    </div>
    <textarea class="input" rows="2" ref=${ta} value=${draft ?? editText()}
      onInput=${e => setDraft(e.target.value)}
      onBlur=${e => { const v = e.target.value; setDraft(null); if (v !== editText()) op('update', { ids: [c.id], patch: { text: { content: v } } }, 'Edit Caption'); }} />
    <div class="hint">Fix words here — timing is kept. Wrap a word in *stars* to highlight it.</div>
    <div class="field wide"><label>Template</label><select class="input" value=${cap.template}
      onChange=${e => op('restyle_captions', { ids, template: e.target.value }, 'Caption Template')}>
      ${tpls.map(t => html`<option value=${t.id}>${t.user ? '★ ' : ''}${t.name}</option>`)}</select></div>
    <div class="field wide"><label>Font</label><select class="input" value=${s.font}
      onChange=${e => { const fam = e.target.value; const ws = S.presets.fonts.filter(f => f.family === fam).map(f => f.weight);
        restyle({ font: fam, weight: ws.reduce((a, b) => Math.abs(b - s.weight) < Math.abs(a - s.weight) ? b : a, ws[0]) }, 'Caption Font'); }}>
      ${FONTS().map(f => html`<option value=${f}>${f}</option>`)}</select></div>
    ${weights.length > 1 && html`<div class="field wide"><label>Weight</label><select class="input" value=${s.weight} onChange=${e => restyle({ weight: +e.target.value }, 'Caption Weight')}>
      ${weights.map(w => html`<option value=${w}>${({ 400: 'Regular', 500: 'Medium', 600: 'Semibold', 700: 'Bold', 800: 'Extra bold', 900: 'Black' })[w] || w}</option>`)}</select></div>`}
    <${Slider} label="Size" min=${20} max=${200} step=${1} digits=${0} unit="px" value=${s.size ?? 64} onLive=${v => live(ids, { text: { caption: { style: { size: v } } } })} onCommit=${v => restyle({ size: v }, 'Caption Size')} />
    <div class="field wide"><label>Text color</label><input type="color" class="color-input" value=${(s.color || '#FFFFFF').slice(0, 7)} onChange=${e => restyle({ color: e.target.value.toUpperCase(), gradient: null }, 'Caption Color')} /></div>
    ${!['none', 'reveal', 'typewriter'].includes(s.mode) && html`<div class="field wide"><label>Highlight</label><input type="color" class="color-input" value=${(s.active?.color || '#FFD84D').slice(0, 7)} onChange=${e => restyle({ active: { color: e.target.value.toUpperCase() } }, 'Highlight Color')} /></div>`}
    ${s.mode === 'karaoke_box' && html`<div class="field wide"><label>Pill color</label><input type="color" class="color-input" value=${(s.active?.box || '#7C4DFF').slice(0, 7)} onChange=${e => restyle({ active: { box: e.target.value.toUpperCase() + 'FF' } }, 'Pill Color')} /></div>`}
    <div class="field wide"><label>Word effect</label><select class="input" value=${s.mode} onChange=${e => restyle({ mode: e.target.value }, 'Word Effect')}>
      ${[['none', 'None (whole line)'], ['karaoke', 'Karaoke highlight'], ['karaoke_box', 'Highlight pill'], ['pop', 'Pop in'], ['bounce', 'Bounce'], ['reveal', 'Fade in word by word'], ['typewriter', 'Typewriter']]
        .map(([v, l]) => html`<option value=${v}>${l}</option>`)}</select></div>
    <${Slider} label="Outline" min=${0} max=${16} step=${1} digits=${0} unit="px" value=${s.outline ?? 0} onLive=${v => live(ids, { text: { caption: { style: { outline: v } } } })} onCommit=${v => restyle({ outline: v }, 'Outline')} />
    <${Slider} label="Shadow" min=${0} max=${30} step=${1} digits=${0} unit="px" value=${s.shadow ?? 0} onLive=${v => live(ids, { text: { caption: { style: { shadow: v } } } })} onCommit=${v => restyle({ shadow: v }, 'Shadow')} />
    <div class="field wide"><label>Case</label><${Seg} value=${s.case || 'none'} options=${[['none', 'As typed'], ['upper', 'UPPERCASE']]} onChange=${v => restyle({ case: v }, 'Caption Case')} /></div>
    <div class="field wide"><label>Position</label><${Seg} value=${c.text.y > 0.62 ? 'b' : c.text.y < 0.38 ? 't' : 'm'} options=${[['t', 'Top'], ['m', 'Middle'], ['b', 'Bottom']]}
      onChange=${v => commit(ids, { text: { y: { t: 0.2, m: 0.5, b: 0.76 }[v] } }, 'Caption Position')} /></div>
    <${Slider} label="Position Y" min=${0} max=${1} step=${0.001} scale=${100} digits=${1} unit="%" ...${bindAnim(ids, c, 'text.y', 'Caption Position')} />
    <div class="field wide"><label>Apply</label><div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small" title="Give every caption this exact look" onClick=${() => op('restyle_captions', { ids: 'all', overrides: s, template: null }, 'Style all captions like this')}>Style all like this</button>
      <button class="btn small" title="Save this look under ★ My presets" onClick=${() => { const n = prompt('Name for this caption style', 'My style'); if (n) A.saveCaptionPreset(c.id, n); }}>★ Save as preset</button>
    </div></div>
  </${Section}>
  <${Section} title="Timing" start=${false}>
    <${Slider} label="Duration" min=${0.3} max=${30} step=${0.1} digits=${1} unit="s" value=${c.dur} onLive=${() => {}}
      onCommit=${v => op('trim', { id: c.id, edge: 'end', t: c.start + v }, 'Caption Duration')} />
    <div class="hint">Split a caption with the razor (C) — words go to the side they're spoken on.</div>
  </${Section}>`;
}

function VoiceFxSection({ ids, c }) {
  const fx = c.voice_fx || null;
  const n = Object.values(fx || {}).filter(Boolean).length;
  return html`<${Section} title=${`Voice effects${fx ? ' •' : ''}`} start=${!!fx}>
    <${VoiceFxControls} value=${fx} onChange=${v => op('update', { ids, patch: { voice_fx: v } }, 'Voice Effects')} />
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small" onClick=${() => { player.seek(c.start + 0.01); player.play(); }}><${Icon} n="play" s=${11} /> Preview</button>
      ${fx && c.type === 'tts' && html`<button class="btn small" title="Give every narration clip these effects" onClick=${() => op('apply_voice_fx', { fx, role: 'narration' }, 'Effects on all narration')}>Copy to all narration</button>`}
      ${fx && html`<button class="btn small ghost" onClick=${() => op('update', { ids, patch: { voice_fx: null } }, 'Remove Voice Effects')}>Remove all</button>`}
    </div>
    <div class="hint">Like a recording made somewhere else: phone or radio <b>Filter</b>, café / city / rain <b>Noise</b>, room <b>Space</b>, mic <b>Distance</b>. Non-destructive — the export uses the same effects.</div>
  </${Section}>`;
}

function NarrationSection({ c }) {
  const tt = c.tts;
  const voices = useStore(s => s.voices || []);
  const job = useStore(s => s.ttsJobs?.[c.id]);
  const tones = S.ttsStatus?.tones || {};
  const [draft, setDraft] = useState(null);
  const ta = useRef();
  useEffect(() => {
    const f = () => ta.current?.focus();
    window.addEventListener('vs-edit-narration', f);
    return () => window.removeEventListener('vs-edit-narration', f);
  }, []);
  const set1 = (patch, label) => op('update', { ids: [c.id], patch: { tts: patch } }, label);
  const words = (draft ?? tt.text).trim().split(/\s+/).filter(Boolean).length;
  const est = estimateSecs(draft ?? tt.text, tt.rate, tt.pause ?? 1);
  const running = job && (job.state === 'running' || job.state === 'queued');
  return html`<${Section} title="AI Narration">
    <textarea class="input" rows="4" ref=${ta} placeholder="Type what the narrator says…" value=${draft ?? tt.text}
      onInput=${e => setDraft(e.target.value)} onBlur=${e => { if (draft != null && draft !== tt.text) set1({ text: e.target.value }, 'Narration Text'); setDraft(null); }} />
    <div class="hint">${words} words ≈ ${est.toFixed(1)} s spoken · clip is ${c.dur.toFixed(1)} s${tt.fit && words && (est / c.dur > 1.33 || est / c.dur < 0.75) ? ' — too different to fit; the clip will be resized' : ''}</div>
    <div class="field wide"><label>Voice</label><select class="input" value=${tt.voice || ''} onChange=${e => set1({ voice: e.target.value || null }, 'Narration Voice')}>
      <option value="">Built-in voice</option>${voices.map(v => html`<option value=${v.name}>${v.name}</option>`)}</select></div>
    <div class="field wide"><label>Tone</label><div style="display:flex;gap:4px;flex-wrap:wrap">
      ${Object.entries(tones).map(([k, v]) => html`<button class=${`chip ${tt.tone === k ? 'on' : ''}`} style="border:0;cursor:pointer" onClick=${() => set1({ tone: k }, 'Narration Tone')}>${v.label}</button>`)}</div></div>
    <label class="check" title="ElevenLabs Eleven v4 performs the line in one go (no sentence splitting or speed evening) — sounds the most human. Needs the ElevenLabs engine and a cloned voice.">
      <input type="checkbox" checked=${tt.mode === 'dialogue'} onChange=${e => set1(e.target.checked ? { mode: 'dialogue', model: 'eleven_v4' } : { mode: null, model: null }, 'Natural Conversation Voice')} />
      Natural conversation voice (ElevenLabs v4)</label>
    <${Slider} label="Emotion" min=${0} max=${1} step=${0.05} scale=${100} digits=${0} unit="%" reset=${tt.mode === 'dialogue' ? 0.2 : 0.5}
      value=${tt.intensity ?? 0.5} onLive=${() => {}} onCommit=${v => set1({ intensity: v }, 'Narration Emotion')} />
    ${tt.mode === 'dialogue' && html`<div class="hint">Emotion ${Math.round((tt.intensity ?? 0.2) * 100)}%: ${(tt.intensity ?? 0.2) < 0.1 ? 'plain, no delivery cue' : (tt.intensity ?? 0.2) < 0.35 ? `a light touch (“slightly ${tt.tone}”)` : (tt.intensity ?? 0.2) < 0.7 ? `clearly ${tt.tone}` : `very ${tt.tone}`} — press Regenerate to hear it. Only this line changes.</div>`}
    ${tt.mode !== 'dialogue' && html`<${PaceControls} value=${{ rate: tt.rate ?? null, pause: tt.pause ?? 1, steady: tt.steady !== false }}
      onChange=${v => set1({ rate: v.rate, pause: v.pause, steady: v.steady, pace: 1 }, 'Narration Pace')} />`}
    <label class="check"><input type="checkbox" checked=${tt.fit} onChange=${e => set1({ fit: e.target.checked }, 'Fit Narration')} /> Fit speech to the clip length (pauses adjust first, then speed ±12%)</label>
    <label class="check"><input type="checkbox" checked=${tt.caption} onChange=${e => set1({ caption: e.target.checked }, 'Narration Caption')} /> Also show as on-screen caption</label>
    <div style="display:flex;gap:6px;align-items:center">
      <button class="btn primary" disabled=${running || !(draft ?? tt.text).trim()} onClick=${() => A.generateNarration([c.id])}>
        <${Icon} n="voice" s=${14} /> ${running ? (job.state === 'queued' ? 'Queued…' : 'Generating…') : tt.file && !tt.stale ? 'Regenerate' : 'Generate voice'}</button>
      ${tt.file && html`<button class="btn" onClick=${() => playFile(tt.file)}><${Icon} n="play" s=${11} /> Listen</button>
        <button class="btn" title="Same text and settings, a fresh performance (if one sentence sounds odd)" disabled=${running}
          onClick=${() => op('update', { ids: [c.id], patch: { tts: { take: (tt.take || 0) + 1 } } }, 'New Take').then(() => A.generateNarration([c.id]))}>New take</button>
        <button class="btn" title="Save this narration as an MP3 (exports/<project>/voice)" onClick=${() => A.narrationMp3(c.id)}><${Icon} n="export" s=${11} /> MP3</button>`}
    </div>
    ${tt.stale && tt.file && !running && html`<div class="hint" style="color:var(--accent)">Settings changed — regenerate to hear them.</div>`}
    ${job?.state === 'done' && job.engine && html`<div class="hint">Made with ${job.engine === 'elevenlabs' ? 'ElevenLabs' : 'the local engine'}${job.secs ? ` in ${job.secs}s` : ''}.</div>`}
    ${tt.file && !tt.stale && tt.match != null && html`<div class=${`match ${tt.match >= 84 ? 'good' : tt.match >= 76 ? 'ok' : 'low'}`}
      title="How much this line sounds like the voice's samples (speaker-recognition model). Same person ≈ 80–95%, a different person ≈ 60–70%.">
      Voice match <b>${Math.round(tt.match)}%</b> ${tt.match >= 84 ? '— sounds like them' : tt.match >= 76 ? '— close' : '— not very close: rebuild the voice from a clean recording of them'}</div>`}
    ${tt.file && !tt.stale && tt.wpm && html`<div class="hint">Spoken at <b>≈${tt.wpm} words/min</b>${tt.pieces > 1 ? `, ${tt.pieces} sentences evened out` : ''}${tt.take ? ` · take ${tt.take + 1}` : ''}.${tt.limited ? ' This voice couldn’t reach the chosen speed without sounding processed — press Regenerate once more (it now knows the voice’s pace) or pick a closer speed.' : ''}</div>`}
    <div class="hint">Engine: <b>${S.ttsStatus?.config?.engine === 'elevenlabs' ? 'ElevenLabs' : 'Local'}</b> — switch in Effects ▸ AI Voice.</div>
    ${job?.state === 'error' && html`<div class="hint" style="color:var(--danger)">${job.error}</div>`}
    <div class="hint">Drag the clip's edges on the Narration track to set how long it should last; with “Fit” on, the voice is timed to match.</div>
  </${Section}>`;
}

function SentencesSection({ c }) {
  const sent = useStore(s => s.sent);
  const ctx = useStore(s => s.narrCtx);
  const pending = useStore(s => s.sentPending);
  const [edit, setEdit] = useState(null);                   // {i, v} while typing a start time
  if (!hasSentences(c)) {
    return html`<${Section} title="Sentence timing">
      <div class="hint">${c.tts.steady === false ? 'Turn on Steady pace and regenerate to move sentences one by one.'
        : 'Regenerate this narration once to move its sentences one by one (it reuses the saved sentences — normally no new credits).'}</div></${Section}>`;
  }
  const times = pending?.clip === c.id ? pending.times : sentenceTimes(c);
  const upd = (i, patch, label) => {
    let t = times.map(x => ({ ...x }));
    if (patch.speed != null) t[i] = { ...t[i], speed: patch.speed, t1: t[i].t0 + (t[i].t1 - t[i].t0) * t[i].speed / patch.speed };
    if (patch.t0 != null) t = moved(c, t, i, patch.t0, false);
    applyTimes(c.id, t, label);
  };
  return html`<${Section} title="Sentence timing">
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="btn small primary" onClick=${() => set({ dialog: 'match', matchClip: c.id })}><${Icon} n="wand" s=${12} /> Match to video…</button>
      ${c.tts.layout && html`<button class="btn small" onClick=${() => resetTiming(c.id)}><${Icon} n="reset" s=${12} /> Reset timing</button>`}
    </div>
    <div class="sent-list">
      ${times.map(sp => {
        const talk = overlapsTalk(sp, ctx?.speech);
        return html`<div class=${`sent-row ${sent?.clip === c.id && sent.i === sp.i ? 'on' : ''}`} onClick=${() => { set({ sent: { clip: c.id, i: sp.i } }); player.seek(sp.t0); }}>
          <span class=${talk ? 'warn' : 'hint'} title=${talk ? 'Talks over someone in the video' : `Sentence ${sp.i + 1}`}>${talk ? '⚠' : sp.i + 1}</span>
          <span class="tx" title=${sp.text}>${sp.text}</span>
          <input class="input" title="Starts at (seconds on the timeline)" value=${edit?.i === sp.i ? edit.v : sp.t0.toFixed(2)}
            onClick=${e => e.stopPropagation()} onInput=${e => setEdit({ i: sp.i, v: e.target.value })}
            onKeyDown=${e => { if (e.key === 'Enter') e.target.blur(); }}
            onBlur=${e => { const v = parseFloat(e.target.value); setEdit(null); if (Number.isFinite(v) && Math.abs(v - sp.t0) > 0.005) upd(sp.i, { t0: v }, 'Move Sentence'); }} />
          <select class="input" title="Speed of this sentence" value=${String(Math.round(sp.speed * 100) / 100)} onClick=${e => e.stopPropagation()}
            onChange=${e => upd(sp.i, { speed: +e.target.value }, 'Sentence Speed')}>
            ${[0.88, 0.9, 0.95, 1, 1.05, 1.1, 1.12].map(v => html`<option value=${String(v)}>${v.toFixed(2)}×</option>`)}
            ${![0.88, 0.9, 0.95, 1, 1.05, 1.1, 1.12].some(v => Math.abs(v - sp.speed) < 0.005) && html`<option value=${String(Math.round(sp.speed * 100) / 100)}>${sp.speed.toFixed(2)}×</option>`}
          </select></div>`;
      })}
    </div>
    <div class="hint">On the timeline: drag a sentence to move it (Shift = it and the rest), ←/→ nudges 0.1 s (Shift = 1 frame), right-click for snap / gap / speed. Striped areas = people talking in the video.</div>
  </${Section}>`;
}

function TransitionInspector({ x }) {
  const list = S.presets.transitions;
  const td = list.find(t => t.id === x.type);
  return html`<div>
    <div class="insp-title"><div class="sw" style="background:var(--accent)" /><div style="min-width:0"><div class="t">${td?.name || x.type}</div><div class="s">Transition · ${x.a && x.b ? 'between two clips' : x.b ? 'in from nothing' : 'out to nothing'}</div></div></div>
    <${Section} title="Transition">
      <div class="field wide"><label>Type</label><select class="input" value=${x.type} onChange=${e => op('update_transition', { id: x.id, patch: { type: e.target.value } }, 'Change Transition')}>
        ${list.map(t => html`<option value=${t.id}>${t.category} · ${t.name}</option>`)}</select></div>
      <${Slider} label="Duration" min=${0.1} max=${3} step=${0.05} digits=${2} unit="s" value=${x.dur} onLive=${() => {}}
        onCommit=${v => op('update_transition', { id: x.id, patch: { dur: v } }, 'Transition Duration')} />
      <button class="btn danger" onClick=${() => A.del()}><${Icon} n="trash" s=${14} /> Remove transition</button>
    </${Section}>
  </div>`;
}
function AssetInfo({ a }) {
  const m = a.meta || {};
  const rows = [['File', a.path], ['Type', a.kind], m.w && ['Size', `${m.w} × ${m.h}`], m.fps && ['Frame rate', `${m.fps.toFixed(3)} fps`],
    m.dur && ['Duration', dur(m.dur)], m.vcodec && ['Video codec', m.vcodec], m.acodec && ['Audio', `${m.acodec} ${m.sr ? m.sr / 1000 + ' kHz' : ''}`],
    ['File size', bytes(a.size)], ['Status', a.status + (a.error ? ` — ${a.error}` : '')]].filter(Boolean);
  return html`<div>
    <div class="insp-title"><div class="sw" style=${`background:${kindColor(a.kind === 'audio' ? 'audio' : 'video')}`} /><div style="min-width:0"><div class="t">${a.name}</div><div class="s">${a.folder}</div></div></div>
    <div class="section-body" style="padding-top:12px">
      ${rows.map(([k, v]) => html`<div class="field wide"><label>${k}</label><span style="font-size:12px;word-break:break-all">${v}</span></div>`)}
      <button class="btn" onClick=${() => A.addAsset(a.id)}><${Icon} n="plus" s=${14} /> Add at playhead</button>
    </div>
  </div>`;
}
export const FORMAT_OPTS = [['reels', 'Instagram Reels · 1080×1920 · 30 fps'], ['9:16', '9:16 vertical · 29.97 fps'],
  ['16:9', '16:9 YouTube · 1920×1080'], ['1:1', '1:1 square · 1080×1080'], ['4:5', '4:5 portrait · 1080×1350']];

function BrandSection() {
  const br = S.project.settings.brand || {};
  const assets = useStore(s => s.assets);
  const images = Object.values(assets).filter(a => a.kind === 'image' && a.scope !== 'library')
    .sort((a, b) => (b.folder.startsWith('brand') ? 1 : 0) - (a.folder.startsWith('brand') ? 1 : 0) || a.name.localeCompare(b.name));
  const set1 = (patch, label) => op('set_brand', patch, label);
  const others = (S.projects || []).filter(x => !x.current).map(x => x.name);
  return html`<${Section} title=${`Watermark / logo${br.enabled ? ' •' : ''}`} start=${!!br.enabled}>
    ${images.length === 0 ? html`<div class="hint">Put a transparent PNG in this project's <b>assets/brand/logo</b> or <b>brand/watermark</b> folder
        (or drop a file named “…logo…png” / “…watermark…png” into import/).
        <div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap"><button class="btn small" onClick=${() => A.open('brand')}>Open brand folder</button>
        ${others.length > 0 && html`<select class="input" style="width:auto" onChange=${e => e.target.value && api('/api/projects/copy_assets', { from: e.target.value }).then(r => toast(r.copied.length ? `Copied ${r.copied.length} file(s) from ${e.target.value}` : 'That project has no brand files', r.copied.length ? 'ok' : 'error'))}>
          <option value="">Copy from another project…</option>${others.map(n => html`<option value=${n}>${n}</option>`)}</select>`}</div></div>`
    : html`
      <div class="field wide"><label>Image</label><select class="input" value=${br.asset || ''} onChange=${e => set1(e.target.value ? { asset: e.target.value } : { enabled: false }, 'Watermark Image')}>
        <option value="">— none —</option>${images.map(a => html`<option value=${a.id}>${a.folder ? a.folder + '/' : ''}${a.name}</option>`)}</select></div>
      <div class="field wide"><label>Show</label><${Seg} value=${!!br.enabled} options=${[[true, 'On'], [false, 'Off']]} onChange=${v => set1({ enabled: v }, 'Watermark On/Off')} /></div>
      <div class="field wide"><label>Position</label><${Seg} value=${br.position} options=${[['tl', '↖'], ['tr', '↗'], ['center', '•'], ['bl', '↙'], ['br', '↘']]} onChange=${v => set1({ position: v }, 'Watermark Position')} /></div>
      <${Slider} label="Size" min=${0.05} max=${0.6} step=${0.01} scale=${100} digits=${0} unit="%" reset=${0.18} value=${br.size ?? 0.18} onLive=${() => {}} onCommit=${v => set1({ size: v }, 'Watermark Size')} />
      <${Slider} label="Opacity" min=${0.1} max=${1} step=${0.01} scale=${100} digits=${0} unit="%" reset=${0.85} value=${br.opacity ?? 0.85} onLive=${() => {}} onCommit=${v => set1({ opacity: v }, 'Watermark Opacity')} />
      <${Slider} label="Margin" min=${0} max=${0.15} step=${0.005} scale=${100} digits=${1} unit="%" reset=${0.04} value=${br.margin ?? 0.04} onLive=${() => {}} onCommit=${v => set1({ margin: v }, 'Watermark Margin')} />
      <div class="hint">Shown on every frame of the video (preview and export) — it follows your edits automatically. Safe area for Reels: keep it out of the bottom ~20% (captions/buttons).</div>`}
  </${Section}>`;
}

function ProjectSettings() {
  const p = S.project;
  const st = p.settings;
  const aTracks = p.tracks.filter(t => t.kind === 'audio');
  return html`<div>
    <div class="insp-title"><div class="sw" style="background:var(--accent)" /><div><div class="t">${S.projectName || 'Project'}</div><div class="s">${S.projectPath}</div></div></div>
    <${Section} title="Sequence">
      <div class="field wide"><label>Format</label><select class="input" value=${p.format.preset} onChange=${e => A.format(e.target.value)}>
        ${FORMAT_OPTS.map(([v, l]) => html`<option value=${v}>${l}</option>`)}</select></div>
      <div class="field wide"><label>Size</label><span>${p.format.w}×${p.format.h} · ${fps().toFixed(fps() % 1 ? 3 : 0)} fps</span></div>
    </${Section}>
    <${BrandSection} />
    <${Section} title="Audio mix" id="audio-mix">
      <${Slider} label="Loudness (LUFS)" min=${-24} max=${-9} step=${0.5} digits=${1} value=${st.normalize_lufs ?? -14} onLive=${() => {}}
        onCommit=${v => op('set_settings', { patch: { normalize_lufs: v } }, 'Loudness Target')} />
      <${Slider} label="Duck music" min=${-30} max=${0} step=${1} digits=${0} unit=" dB" value=${st.duck_db} onLive=${() => {}}
        onCommit=${v => op('set_settings', { patch: { duck_db: v } }, 'Ducking')} />
      ${aTracks.map(t => html`<${Slider} label=${`${t.id} ${t.name}`} min=${-30} max=${12} step=${0.5} digits=${1} unit=" dB" reset=${0} value=${t.volume_db}
        onLive=${() => {}} onCommit=${v => A.track(t.id, { volume_db: v }, 'Track Volume')} />`)}
      <div class="hint">A1 Dialogue = the video clips' own sound · A2 Music (and Music 2) = background music. Each slider changes the whole track; one clip's sound: select the clip → Sound. Tracks marked "duck" (Music by default) dip automatically while someone speaks on A1. Export normalizes to the loudness target (−14 LUFS suits YouTube/Instagram).</div>
    </${Section}>
    <div class="section-body" style="padding-top:12px"><div class="hint">Select a clip, transition or asset to edit it here.</div></div>
  </div>`;
}

export function Inspector() {
  const sel = useStore(s => s.sel);
  useStore(s => s.project);
  useStore(s => s.assets);
  // values follow the playhead only when the selected clip is animated (avoids re-rendering every frame otherwise)
  useStore(s => (s.sel.clips.some(id => Object.keys(clipById(id)?.keys || {}).length) ? s.t : 0));
  if (!S.project || !S.presets) return html`<div class="panel" />`;
  let body;
  const x = sel.transition && S.project.transitions.find(t => t.id === sel.transition);
  const clips = sel.clips.map(clipById).filter(Boolean);
  if (x) body = html`<${TransitionInspector} x=${x} />`;
  else if (clips.length) {
    const kindOf = c => trackById(c.track)?.kind;
    const primary = clips.find(c => kindOf(c) !== 'audio') || clips[0];
    const kind = kindOf(primary);
    const ids = clips.filter(c => kindOf(c) === kind).map(c => c.id);
    // a video clip is selected together with its linked sound (A1) → show that sound's volume too
    const sound = kind === 'video' ? clips.filter(c => kindOf(c) === 'audio') : [];
    const a = S.assets[primary.asset];
    const name = primary.label || (primary.type === 'text' ? primary.text.content.split('\n')[0]
      : primary.type === 'tts' ? `Narration${primary.tts.text ? ': ' + primary.tts.text.slice(0, 40) : ''}`
      : a?.name || S.project.assets[primary.asset]?.path?.split('/').pop() || 'Missing media');
    body = html`<div>
      <div class="insp-title"><div class="sw" style=${`background:${kindColor(kind)}`} /><div style="min-width:0">
        <div class="t">${name}${ids.length > 1 ? ` + ${ids.length - 1} more` : ''}</div>
        <div class="s">${primary.track} · ${tc(primary.start, fps())} · ${dur(clipDur(primary))}</div></div></div>
      ${kind === 'video' && html`<${MotionSection} ids=${ids} c=${primary} /><${CropSection} ids=${ids} c=${primary} /><${SpeedSection} ids=${ids} c=${primary} />
        ${sound.length > 0 && html`<${AudioSection} ids=${sound.map(c => c.id)} c=${sound[0]} linked=${true} />`}
        <${ColorSection} ids=${ids} c=${primary} /><${FiltersSection} ids=${ids} c=${primary} />`}
      ${kind === 'audio' && primary.type === 'tts' && html`<${NarrationSection} c=${primary} />`}
      ${kind === 'audio' && primary.type === 'tts' && primary.tts?.file && html`<${SentencesSection} c=${primary} />`}
      ${kind === 'audio' && html`<${AudioSection} ids=${ids} c=${primary} /><${VoiceFxSection} ids=${ids} c=${primary} />`}
      ${kind === 'text' && html`${primary.text.caption ? html`<${CaptionSection} ids=${ids} c=${primary} />` : html`<${TextSection} ids=${ids} c=${primary} />`}<${Section} title="Opacity & Fades" start=${false}>
        <${Slider} label="Opacity" min=${0} max=${1} scale=${100} digits=${0} unit="%" reset=${1} ...${bindAnim(ids, primary, 'motion.opacity', 'Opacity')} /></${Section}>`}
    </div>`;
  } else if (sel.asset && S.assets[sel.asset]) body = html`<${AssetInfo} a=${S.assets[sel.asset]} />`;
  else body = html`<${ProjectSettings} />`;
  return html`<div class="panel">
    <div class="panel-head"><span class="panel-title">Inspector</span></div>
    <div class="panel-body">${body}</div>
  </div>`;
}
