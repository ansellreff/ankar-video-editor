// Speaking pace controls shared by the Narration inspector, "Try it" and the Voice from Video wizard.
// value = {rate: null|'slow'|'relaxed'|'natural'|'brisk'|'fast'|number(wpm), pause: 0.5..2, steady: bool}
import { html } from '../vendor/preact-htm.js';

export const RATES = [['slow', 'Slow', 140], ['relaxed', 'Relaxed', 160], ['natural', 'Natural', 180], ['brisk', 'Brisk', 200], ['fast', 'Fast', 220]];   // = app/tts/pacing.py RATES
const wpmOf = r => typeof r === 'number' ? r : (RATES.find(x => x[0] === r) || [])[2] || null;

/** Rough spoken length (s) of `text` at these settings — mirrors app/tts/pacing.estimate. */
export function estimateSecs(text, rate, pause = 1) {
  const t = (text || '').trim();
  if (!t) return 0;
  const w = (t.match(/[A-Za-z0-9']+/g) || []).length;
  const sentences = Math.max(1, (t.match(/[.!?]+(\s|$)/g) || []).length);
  const paras = (t.match(/\n/g) || []).length;
  const manual = [...t.matchAll(/\[\s*pause(?:\s+([\d.]+))?\s*s?\s*\]/gi)].reduce((a, m) => a + (m[1] ? +m[1] : 0.6), 0);
  const wpm = wpmOf(rate) || 180;
  return w / (wpm / 60) + (Math.max(0, sentences - 1) * 0.42 + paras * 0.33) * pause + manual + 0.1;
}

export function PaceControls({ value, onChange, compact = false }) {
  const v = { rate: null, pause: 1, steady: true, ...(value || {}) };
  const wpm = wpmOf(v.rate);
  const set = patch => onChange({ ...v, ...patch });
  return html`<div class="pace">
    <div class="pace-row stack"><span class="pace-l" title="How fast the narrator talks (words per minute)">Speed</span>
      <div class="seg pace-seg">
        <button class=${v.rate == null ? 'on' : ''} title="The voice's own natural pace, evened out" onClick=${() => set({ rate: null })}>Auto</button>
        ${RATES.map(([id, label, n]) => html`<button class=${v.rate === id || (typeof v.rate === 'number' && Math.abs(v.rate - n) < 4) ? 'on' : ''} title=${`${label} ≈ ${n} words/min`} onClick=${() => set({ rate: id })}>${label}</button>`)}
      </div></div>
    ${!compact && html`<div class="pace-row"><span class="pace-l">Exact</span>
      <input type="range" min="110" max="250" step="5" value=${wpm || 180} disabled=${v.rate == null} style=${`--fill:${((wpm || 180) - 110) / 140 * 100}%`}
        onChange=${e => set({ rate: +e.target.value })} />
      <span class="pace-n">${wpm ? `${wpm} wpm` : 'auto'}</span></div>`}
    <div class="pace-row"><span class="pace-l" title="Silence between sentences and phrases">Pauses</span>
      <input type="range" min="0.5" max="2" step="0.1" value=${v.pause} style=${`--fill:${(v.pause - 0.5) / 1.5 * 100}%`} onChange=${e => set({ pause: +e.target.value })} />
      <span class="pace-n" title=${v.pause < 0.8 ? 'short' : v.pause > 1.25 ? 'long' : 'natural'}>${v.pause.toFixed(1)}×</span></div>
    <label class="check" title="Speaks sentence by sentence, then evens out the speed and pauses so the rhythm is predictable">
      <input type="checkbox" checked=${v.steady} onChange=${e => set({ steady: e.target.checked })} /> Steady pace (evens out rushed or dragging parts)</label>
    ${!compact && html`<div class="hint">Tip: add a pause anywhere with <b>[pause]</b> or <b>[pause 1.5]</b>; “...” is a short hesitation; a new line is a longer break.</div>`}
  </div>`;
}
