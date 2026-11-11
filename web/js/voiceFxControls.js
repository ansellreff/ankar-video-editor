// Voice effects editor (ElevenLabs-style rows): Filter · Noise · Space · Distance · Pan — each added once, removable.
// value = clip.voice_fx-like object (or null); onChange(next | null)
import { html, useState } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';

const KINDS = [
  ['filter', 'Filter', 'Phone, radio, megaphone, robot…'],
  ['noise', 'Noise', 'Background bed: café, city, rain…'],
  ['space', 'Space', 'Room reverb: small room … church, forest'],
  ['distance', 'Distance', 'Near · Medium · Far from the microphone'],
  ['pan', 'Pan', 'Left / right'],
];
const has = (v, k) => v && (k === 'distance' ? (v.distance || 0) > 0.001 : k === 'pan' ? Math.abs(v.pan || 0) > 0.001 : !!v[k]);

export function VoiceFxControls({ value, onChange, compact = false }) {
  const vf = useStore(s => s.presets?.voice_fx) || { filters: [], spaces: [] };
  const beds = useStore(s => s.ambience || []);
  const [adding, setAdding] = useState([]);                  // rows added but not set yet (e.g. pan at 0)
  const v = value || {};
  const put = patch => { const n = { ...v, ...patch }; onChange(n); };
  const remove = k => {
    setAdding(a => a.filter(x => x !== k));
    const n = { ...v };
    if (k === 'filter') { n.filter = null; n.filter_mix = 1; }
    if (k === 'noise') n.noise = null;
    if (k === 'space') { n.space = null; n.space_mix = null; }
    if (k === 'distance') n.distance = 0;
    if (k === 'pan') n.pan = 0;
    onChange(Object.values(n).some(x => x) ? n : null);
  };
  const shown = KINDS.filter(([k]) => has(v, k) || adding.includes(k));
  const free = KINDS.filter(([k]) => !shown.some(s => s[0] === k));
  const add = k => {
    setAdding(a => [...a, k]);
    if (k === 'filter') put({ filter: vf.filters[0]?.id, filter_mix: 1 });
    if (k === 'noise') put({ noise: beds[0]?.id, noise_db: v.noise_db ?? -24 });
    if (k === 'space') put({ space: vf.spaces[0]?.id, space_mix: null });
    if (k === 'distance') put({ distance: 0.5 });
  };
  const sp = vf.spaces.find(s => s.id === v.space);
  const dist = v.distance || 0;
  const row = (k, label, body) => html`<div class="vfx-row"><span class="pace-l">${label}</span><div class="vfx-body">${body}</div>
    <button class="btn ghost icon small" title=${`Remove ${label}`} onClick=${() => remove(k)}>×</button></div>`;
  return html`<div class="vfx">
    ${shown.map(([k, label]) => k === 'filter' ? row(k, label, html`
        <select class="input" value=${v.filter || ''} onChange=${e => put({ filter: e.target.value })}>
          ${vf.filters.map(f => html`<option value=${f.id} title=${f.desc}>${f.name}</option>`)}</select>
        ${!compact && html`<div class="vfx-sub"><span class="hint">Strength</span><input type="range" min="0" max="1" step="0.05" value=${v.filter_mix ?? 1}
          style=${`--fill:${(v.filter_mix ?? 1) * 100}%`} onChange=${e => put({ filter_mix: +e.target.value })} /><span class="pace-n">${Math.round((v.filter_mix ?? 1) * 100)}%</span></div>`}`)
      : k === 'noise' ? row(k, label, html`
        <select class="input" value=${v.noise || ''} onChange=${e => put({ noise: e.target.value })}>
          ${beds.map(b => html`<option value=${b.id}>${b.user ? '★ ' : ''}${b.name}</option>`)}</select>
        <div class="vfx-sub"><span class="hint">Level</span><input type="range" min="-48" max="-6" step="1" value=${v.noise_db ?? -24}
          style=${`--fill:${((v.noise_db ?? -24) + 48) / 42 * 100}%`} onChange=${e => put({ noise_db: +e.target.value })} /><span class="pace-n">${v.noise_db ?? -24} dB</span></div>`)
      : k === 'space' ? row(k, label, html`
        <select class="input" value=${v.space || ''} onChange=${e => put({ space: e.target.value, space_mix: null })}>
          ${vf.spaces.map(s => html`<option value=${s.id}>${s.name}</option>`)}</select>
        <div class="vfx-sub"><span class="hint">Amount</span><input type="range" min="0" max="1" step="0.05" value=${v.space_mix ?? sp?.mix ?? 0.35}
          style=${`--fill:${(v.space_mix ?? sp?.mix ?? 0.35) * 100}%`} onChange=${e => put({ space_mix: +e.target.value })} /><span class="pace-n">${Math.round((v.space_mix ?? sp?.mix ?? 0.35) * 100)}%</span></div>`)
      : k === 'distance' ? row(k, label, html`
        <div class="seg pace-seg">${[['Near', 0.15], ['Medium', 0.5], ['Far', 1]].map(([l, d]) => html`<button class=${Math.abs(dist - d) < 0.08 ? 'on' : ''} onClick=${() => put({ distance: d })}>${l}</button>`)}</div>
        ${!compact && html`<div class="vfx-sub"><span class="hint">Exact</span><input type="range" min="0" max="1" step="0.05" value=${dist}
          style=${`--fill:${dist * 100}%`} onChange=${e => put({ distance: +e.target.value })} /><span class="pace-n">${Math.round(dist * 100)}%</span></div>`}`)
      : row(k, label, html`<div class="vfx-sub"><span class="hint">L</span><input type="range" min="-1" max="1" step="0.05" value=${v.pan || 0}
          style=${`--fill:${((v.pan || 0) + 1) * 50}%`} onChange=${e => put({ pan: +e.target.value })} /><span class="hint">R</span><span class="pace-n">${(v.pan || 0) === 0 ? 'center' : `${Math.round(Math.abs(v.pan) * 100)}% ${v.pan < 0 ? 'L' : 'R'}`}</span></div>`))}
    ${free.length > 0 && html`<div class="vfx-add">${free.map(([k, label, tip]) => html`<button class="chip" title=${tip} onClick=${() => add(k)}>+ ${label}</button>`)}</div>`}
  </div>`;
}
