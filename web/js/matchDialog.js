// "Match to video": place a narration's sentences in the video so they don't talk over people and start on shot
// changes; shows a preview of the plan before applying (server: /api/tts/match, app/tts/placement.py).
import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, toast, clipById } from './store.js';
import { api } from './api.js';
import { Icon } from './util.js';
import { claudeRequest } from './sentences.js';

export function MatchDialog({ Dialog, Seg, close }) {
  const c = clipById(S.matchClip);
  const hasIO = S.inPt != null && S.outPt != null && S.outPt > S.inPt;
  const [mode, setMode] = useState('under');
  const [avoid, setAvoid] = useState(true);
  const [snap, setSnap] = useState(true);
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const body = { clip: c?.id, mode: mode === 'io' ? 'range' : mode, range: mode === 'io' ? [S.inPt, S.outPt] : null, avoid, snap };
  useEffect(() => {
    if (!c) return;
    let live = true;
    setBusy(true); setErr(null);
    api('/api/tts/match', { ...body, dry_run: true })
      .then(r => { if (live) setRep(r); }).catch(e => { if (live) { setRep(null); setErr(e.message); } })
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [mode, avoid, snap]);
  if (!c) return null;
  const apply = () => {
    setBusy(true);
    api('/api/tts/match', body).then(r => {
      set({ project: r.project, history: r.history, sent: null });
      toast(r.report.fits ? 'Narration matched to the video' : `Placed — still ${r.report.over.toFixed(1)} s too long`, r.report.fits ? 'ok' : 'error');
      close();
    }).catch(e => { setErr(e.message); setBusy(false); });
  };
  const copy = () => navigator.clipboard.writeText(claudeRequest(c, rep)).then(() => toast('Copied — paste it to Claude in the chat', 'ok'));
  let viz = null;
  if (rep) {
    const [r0, r1] = rep.range, hi = Math.max(r1, rep.end), span = Math.max(0.1, hi - r0);
    const pc = t => `${((t - r0) / span) * 100}%`, wd = d => `${(d / span) * 100}%`;
    viz = html`<div class="match-viz" title="Grey lines = shot changes · striped = someone talks · orange = your sentences">
      ${rep.speech.map(([a, b]) => html`<i class="talk" style=${`left:${pc(Math.max(a, r0))};width:${wd(Math.min(b, hi) - Math.max(a, r0))}`} />`)}
      ${rep.cuts.map(k => html`<i class="cut" style=${`left:${pc(k)}`} />`)}
      ${rep.end > r1 && html`<i class="over" style=${`left:${pc(r1)};width:${wd(rep.end - r1)}`} />`}
      ${rep.starts.map((s, i) => html`<i class="sn" style=${`left:${pc(s)};width:${wd(rep.lens[i])}`} title=${rep.sentences[i]} />`)}
    </div>
    <div class="hint" style="display:flex;justify-content:space-between"><span>${r0.toFixed(1)} s</span><span>${rep.speech.length ? `${rep.speech.length} talking part${rep.speech.length > 1 ? 's' : ''}` : 'no talking found'} · ${rep.cuts.length} shot change${rep.cuts.length === 1 ? '' : 's'}</span><span>${r1.toFixed(1)} s</span></div>`;
  }
  const how = rep?.sources?.some(s => s.how === 'sound') ? 'Talking is detected from the sound; adding Auto Captions to those clips makes it more precise.' : '';
  return html`<${Dialog} title="Match narration to video" width=${560} footer=${html`
      ${rep && html`<button class="btn ghost" onClick=${copy} title="A ready-made request: paste it to Claude to reword the narration">
        <${Icon} n="copy" s=${14} /> ${!rep.fits ? 'Ask Claude to shorten' : rep.add_words ? 'Ask Claude for more words' : 'Copy request for Claude'}</button>`}
      <span style="flex:1" />
      <button class="btn" onClick=${close}>Cancel</button>
      <button class="btn primary" disabled=${!rep || busy} onClick=${apply}>Apply</button>`}>
    <div class="row2"><span>Fit into</span><${Seg} value=${mode} onChange=${setMode} options=${[['under', 'Video under it'], ...(hasIO ? [['io', 'In → Out']] : []),
      ['next', 'Until next clip'], ['clip', 'Current length']]} /></div>
    <label class="check"><input type="checkbox" checked=${avoid} onChange=${e => setAvoid(e.target.checked)} /> Don't talk over people in the video</label>
    <label class="check"><input type="checkbox" checked=${snap} onChange=${e => setSnap(e.target.checked)} /> Start sentences on shot changes</label>
    ${viz}
    ${busy && !rep && html`<div class="hint">Looking at the video (first time per clip takes a few seconds)…</div>`}
    ${err && html`<div class="match-res bad">${err}</div>`}
    ${rep && html`<div class=${`match-res ${rep.fits ? 'ok' : 'bad'}`}>
      ${rep.fits ? html`<b>Fits:</b> ${(rep.end - rep.range[0]).toFixed(1)} s of ${(rep.range[1] - rep.range[0]).toFixed(1)} s`
                 : html`<b>${rep.over.toFixed(1)} s too long</b> ≈ ${rep.words} word${rep.words === 1 ? '' : 's'} — ask Claude to shorten it, or pick a longer range`}
      ${rep.fits && Math.abs(rep.speed - 1) > 0.01 ? html` · speech ${Math.round((rep.speed - 1) * 100)}% faster` : ''}
      ${rep.fits && rep.gap_scale < 0.99 ? ' · shorter pauses' : ''}
      ${rep.fits && rep.add_words ? html`<div class="hint">${rep.spare.toFixed(1)} s left over — room for about ${rep.add_words} more words.</div>` : ''}
      ${rep.collisions ? html`<div class="hint" style="color:#ff8a8a">${rep.collisions} sentence${rep.collisions > 1 ? 's' : ''} still overlap someone talking.</div>` : ''}
    </div>`}
    <div class="hint">Moves sentences only — nothing is regenerated and no ElevenLabs credits are used. Undo with Ctrl+Z. ${how}</div>
  </${Dialog}>`;
}
