// Progress bar with stage text, percentage, elapsed and remaining time.
// value (0–1) when the server knows it; otherwise it advances smoothly from `since` + `estimate` (seconds).
import { html, useState, useEffect } from '../vendor/preact-htm.js';

const fmt = s => s >= 60 ? `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s` : `${Math.max(0, Math.round(s))}s`;

export function Progress({ value = null, stage = 'Working…', since = null, estimate = null }) {
  const [now, setNow] = useState(Date.now());
  const [t0] = useState(() => since || Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  const start = since || t0;
  const elapsed = (now - start) / 1000;
  let v = value, remain = null;
  if (v == null && estimate) {
    v = 1 - Math.exp(-1.6 * elapsed / estimate);          // eases toward 100% around the estimate, never stalls at 0
    v = Math.min(0.97, v);
    remain = Math.max(1, estimate - elapsed);
  } else if (v != null && v > 0.04) {
    remain = elapsed * (1 - v) / v;
  }
  const pct = v == null ? null : Math.round(v * 100);
  return html`<div class="prog">
    <div class="prog-top"><span class="prog-stage"><span class="spinner" />${stage}</span>
      <span class="prog-num">${pct != null ? `${pct}%` : ''} · ${fmt(elapsed)}${remain != null ? ` · about ${fmt(remain)} left` : ''}</span></div>
    <div class=${`bar ${pct == null ? 'indeterminate' : ''}`}><i style=${`width:${pct ?? 30}%`} /></div>
  </div>`;
}
