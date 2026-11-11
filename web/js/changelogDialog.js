// Feedback & Change Log (Edit ▸ Feedback & Change Log…): every review note, Claude's decision, what changed and when,
// with the checkpoint before each round (Restore = File ▸ Revert to Checkpoint). Server: app/changelog.py.
import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';
import { api } from './api.js';
import { A } from './actions.js';

const when = t => new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const STATUS = { todo: ['To do', '#80848e'], doing: ['Working', '#f5a524'], done: ['Done', '#3ccf91'], verified: ['Checked', '#38b6ff'] };
const DEC = { change: 'Change needed', correct: 'Already correct', partly: 'Partly changed' };

export async function loadChangelog(project) {
  const r = await api(`/api/changelog${project ? `?project=${encodeURIComponent(project)}` : ''}`);
  set({ changelog: r });
  return r;
}

export function ChangelogDialog({ close, Dialog }) {
  const log = useStore(s => s.changelog);
  const projects = useStore(s => s.projects || []);
  const current = useStore(s => s.projectName);
  const [proj, setProj] = useState(current);
  const [open, setOpen] = useState({});
  const [filter, setFilter] = useState('all');
  useEffect(() => { loadChangelog(proj); }, [proj]);
  const rounds = [...(log?.rounds || [])].reverse();
  const ents = log?.entries || [];
  const show = e => filter === 'all' || (filter === 'open' ? e.status !== 'done' && e.status !== 'verified' : e.status === filter);
  return html`<${Dialog} title="Feedback & Change Log" width=${820}>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      <select class="input" style="max-width:300px" value=${proj} onChange=${e => setProj(e.target.value)}>
        ${(projects.length ? projects : [{ name: current }]).map(p => html`<option value=${p.name}>${p.name}</option>`)}</select>
      ${['all', 'open', 'done', 'verified'].map(f => html`<button class=${`chip ${filter === f ? 'on' : ''}`} style="border:0;cursor:pointer" onClick=${() => setFilter(f)}>${{ all: 'All', open: 'Open', done: 'Done', verified: 'Checked' }[f]}</button>`)}
      <span style="flex:1" /><span class="hint">${ents.length} notes · ${ents.filter(e => e.status === 'done' || e.status === 'verified').length} done</span>
    </div>
    ${!rounds.length && html`<div class="empty">No feedback logged for this project yet.</div>`}
    ${rounds.map(r => html`<div class="cl-round">
      <div class="cl-round-head"><b>${r.title}</b><span>${when(r.created)}</span>
        ${r.checkpoint_before && html`<button class="btn" title="Go back to how the project was before this round" disabled=${proj !== current}
          onClick=${() => A.revert(r.checkpoint_before)}>Restore “before”</button>`}</div>
      ${ents.filter(e => e.round === r.id && show(e)).map(e => {
        const [lab, col] = STATUS[e.status] || STATUS.todo;
        const isOpen = open[e.id] ?? (e.status !== 'verified');
        return html`<div class="cl-entry">
          <button class="cl-entry-head" onClick=${() => setOpen({ ...open, [e.id]: !isOpen })}>
            <span class=${`cp-chev ${isOpen ? 'open' : ''}`}>›</span><span class="cl-id">${e.id}</span>
            <span class="cl-video">${e.video}</span><span class="cl-item">${e.item}</span>
            <span class="cl-status" style=${`color:${col};border-color:${col}`}>${lab}</span></button>
          ${isOpen && html`<div class="cl-body">
            <div><span class="cl-k">Your note</span>${e.item}</div>
            <div><span class="cl-k">Decision</span><b>${DEC[e.decision] || e.decision}</b>${e.reason ? ` · ${e.reason}` : ''}</div>
            ${e.changes?.length ? html`<div class="cl-changes">${e.changes.map(c => html`<div><span>${when(c.time)}</span>${c.text}</div>`)}</div>`
              : html`<div class="hint">Nothing changed yet.</div>`}
          </div>`}
        </div>`;
      })}
    </div>`)}
    <div class="hint" style="margin-top:8px">Also saved as <code>docs/changelog.md</code> in each project folder.</div>
  </${Dialog}>`;
}
