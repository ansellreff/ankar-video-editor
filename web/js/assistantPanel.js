// AI Editor: the built-in Claude chat (ribbon tab "AI Editor"). It only edits this project's video, follows the
// 9-stage workflow, and NOTHING that changes the video runs before you press Approve (enforced on the server).
import { html, useState, useEffect, useRef } from '../vendor/preact-htm.js';
import { S, set, useStore, toast } from './store.js';
import { api } from './api.js';
import { Icon } from './util.js';

const openKeys = () => window.open('/keys', 'vs-keys');            // API keys: their own password-protected page

// ---------------------------------------------------------------- live events (called from api.js)
export function onAssistantEvent(d) {
  if (d.project && d.project !== S.projectName) return;
  const ai = S.ai;
  if (!ai) return;
  if (d.op === 'busy') {
    if (d.busy && ai.chat?.id !== d.chat) return loadAssistant(d.chat);   // follow the chat the AI is working in
    return set({ ai: { ...ai, status: { ...(ai.status || {}), busy: d.busy, chat: d.chat } } });
  }
  if (d.op === 'workflow') return set({ ai: { ...ai, workflow: d.workflow } });
  if (!ai.chat || ai.chat.id !== d.chat) {                       // another chat of this project got an item
    if (d.op === 'item' && !ai.chat) loadAssistant(d.chat);
    return;
  }
  const items = ai.chat.display.slice();
  if (d.op === 'item') items[d.item.i] = d.item;
  else if (d.op === 'update' && items[d.i]) items[d.i] = { ...items[d.i], ...d.patch };
  else if (d.op === 'delta' && items[d.i]) items[d.i] = { ...items[d.i], text: (items[d.i].text || '') + d.text };
  const usage = d.op === 'item' && d.item.kind === 'usage' ? { ...ai.usage, cost: d.item.project_cost } : ai.usage;
  set({ ai: { ...ai, usage, chat: { ...ai.chat, display: items } } });
}

export async function loadAssistant(chatId) {
  try {
    const [st, cfg] = await Promise.all([api('/api/assistant/state' + (chatId ? `?chat=${encodeURIComponent(chatId)}` : '')),
                                         api('/api/assistant/config')]);
    set({ ai: { ...st, config: cfg } });
  } catch (e) { toast(e.message, 'error'); }
}

// ---------------------------------------------------------------- tiny, safe markdown (escape first)
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function md(text) {
  const lines = esc(text).split('\n');
  let out = '', inList = false, inCode = false;
  for (let ln of lines) {
    if (ln.trim().startsWith('```')) { out += inCode ? '</pre>' : '<pre>'; inCode = !inCode; continue; }
    if (inCode) { out += ln + '\n'; continue; }
    ln = ln.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>')
           .replace(/(docs\/[\w\-./ ]+?\.(md|txt))/g, '<a class="ai-doc" data-doc="$1">$1</a>');
    const li = ln.match(/^\s*[-•*]\s+(.*)/) || ln.match(/^\s*\d+[.)]\s+(.*)/);
    if (li) { if (!inList) { out += '<ul>'; inList = true; } out += `<li>${li[1]}</li>`; continue; }
    if (inList) { out += '</ul>'; inList = false; }
    out += ln.startsWith('#') ? `<div class="ai-h">${ln.replace(/^#+\s*/, '')}</div>` : (ln ? `<div>${ln}</div>` : '<div class="ai-gap"></div>');
  }
  if (inList) out += '</ul>';
  if (inCode) out += '</pre>';
  return out;
}

// ---------------------------------------------------------------- pieces
function Stepper({ wf }) {
  if (!wf) return null;
  return html`<div class="ai-steps">${wf.stages.map((s, k) => html`<div class=${`ai-step ${s.current ? 'cur' : ''} ${s.approved ? 'ok' : ''} ${s.needs_update ? 'upd' : ''}`}
    title=${`${k + 1}. ${s.label}${s.approved ? ' — approved' : ''}${s.needs_update ? ' — needs update' : ''}${s.current ? ' — current stage' : ''}`}>
    <i>${s.approved && !s.needs_update ? '✓' : k + 1}</i><span>${s.label}</span></div>`)}</div>`;
}

const answer = (pid, action, value) => api('/api/assistant/answer', { pid, action, value }).catch(e => toast(e.message, 'error'));

function Proposal({ it }) {
  const [note, setNote] = useState(null);
  const [open, setOpen] = useState(false);
  const pend = it.status === 'pending';
  const chip = { approved: 'Approved', declined: 'Declined', change: 'Changes requested', stopped: 'Stopped', expired: 'Expired' }[it.status];
  return html`<div class=${`ai-card prop ${it.status}`}>
    <div class="ai-card-h"><${Icon} n=${it.pkind === 'export' ? 'export' : it.pkind === 'stage' ? 'check' : 'sparkle'} s=${15} />
      <b>${it.title}</b>${chip && html`<span class=${`ai-chip ${it.status}`}>${chip}</span>`}</div>
    ${it.summary && html`<div class="ai-card-b" dangerouslySetInnerHTML=${{ __html: md(it.summary) }} />`}
    ${(it.cost || it.length) && html`<div class="ai-meta">${it.cost && html`<span>💳 ${it.cost}</span>`}${it.length && html`<span>⏱ ${it.length}</span>`}</div>`}
    ${it.details?.length > 0 && html`<div class="ai-det"><button class="btn ghost small" onClick=${() => setOpen(!open)}>${open ? 'Hide' : 'Show'} the ${it.details.length} change${it.details.length > 1 ? 's' : ''}</button>
      ${open && html`<ol>${it.details.map(x => html`<li>${x}</li>`)}</ol>`}</div>`}
    ${it.note && !pend && html`<div class="hint">Your note: ${it.note}</div>`}
    ${pend && note === null && html`<div class="ai-acts">
      ${it.actions.includes('approve') && html`<button class="btn primary small" onClick=${() => answer(it.pid, 'approve')}>Approve</button>`}
      ${it.actions.includes('decline') && html`<button class="btn small" onClick=${() => answer(it.pid, 'decline')}>Decline</button>`}
      ${it.actions.includes('change') && html`<button class="btn ghost small" onClick=${() => setNote('')}>Change it…</button>`}</div>`}
    ${pend && note !== null && html`<div class="ai-acts col"><textarea class="input" rows="2" placeholder="What should be different?" value=${note} onInput=${e => setNote(e.target.value)} />
      <div><button class="btn primary small" disabled=${!note.trim()} onClick=${() => answer(it.pid, 'change', note.trim())}>Send</button>
      <button class="btn ghost small" onClick=${() => setNote(null)}>Cancel</button></div></div>`}
  </div>`;
}

function Question({ it }) {
  const [txt, setTxt] = useState('');
  const pend = it.status === 'pending';
  return html`<div class=${`ai-card q ${it.status}`}>
    <div class="ai-card-b" dangerouslySetInnerHTML=${{ __html: md(it.question) }} />
    ${pend ? html`<div class="ai-opts">${(it.options || []).map(o => html`<button class="btn small" onClick=${() => answer(it.pid, 'answer', o)}>${o}</button>`)}</div>
      ${it.allow_text !== false && html`<div class="ai-acts"><input class="input" placeholder="Or type your answer" value=${txt} onInput=${e => setTxt(e.target.value)}
        onKeyDown=${e => { if (e.key === 'Enter' && txt.trim()) answer(it.pid, 'answer', txt.trim()); }} />
        <button class="btn small" disabled=${!txt.trim()} onClick=${() => answer(it.pid, 'answer', txt.trim())}>Send</button></div>`}`
      : html`<div class="hint">→ ${String(it.answer ?? it.status)}</div>`}
  </div>`;
}

function StyleRound({ it }) {
  const recs = it.recommendations || {};
  const [vals, setVals] = useState(() => Object.fromEntries(it.round.fields.map(f => [f.id, recs[f.id]?.value ?? ''])));
  const [note, setNote] = useState('');
  const pend = it.status === 'pending';
  const done = !pend && it.answer?.values;
  return html`<div class=${`ai-card style ${it.status}`}>
    <div class="ai-card-h"><${Icon} n="palette" s=${15} /><b>${it.round.title}</b>
      ${!pend && html`<span class=${`ai-chip ${it.status === 'answered' ? 'approved' : it.status}`}>${it.status === 'answered' ? 'Answered' : it.status}</span>`}</div>
    ${pend && html`<div class="hint" style="margin:2px 0 6px">My suggestion is filled in for each choice, with the reason. Change only what you disagree with.</div>`}
    ${it.round.fields.map(f => {
      const r = recs[f.id] || {};
      const v = done ? it.answer.values[f.id] : vals[f.id];
      const changed = String(v ?? '').trim() !== String(r.value ?? '').trim();
      return html`<div class="ai-field">
        <label>${f.label}${r.from_brief && html` <span class="ai-tag">from your brief</span>`}${changed && html` <span class="ai-tag you">your choice</span>`}</label>
        ${pend ? html`${(r.options || []).length > 0 && html`<div class="ai-opts">${[r.value, ...r.options.filter(o => o !== r.value)].map(o =>
            html`<button class=${`btn small ${vals[f.id] === o ? 'on' : ''}`} onClick=${() => setVals({ ...vals, [f.id]: o })}>${o}</button>`)}</div>`}
          <textarea class="input" rows=${String(v || '').length > 70 ? 3 : 1} value=${v} onInput=${e => setVals({ ...vals, [f.id]: e.target.value })} />`
          : html`<div class="ai-val">${v}</div>`}
        ${r.reason && html`<div class="hint">💡 ${r.reason}</div>`}
        ${it.samples?.[f.id] && html`<div class="hint">🎨 ${it.samples[f.id]}</div>`}
      </div>`; })}
    ${pend && html`<textarea class="input" rows="2" placeholder="Anything else for this round? (optional)" value=${note} onInput=${e => setNote(e.target.value)} />
      <div class="ai-acts"><button class="btn primary small" onClick=${() => answer(it.pid, 'answer', { values: vals, note })}>Confirm this round</button></div>`}
  </div>`;
}

function Item({ it, openDoc }) {
  const click = e => { const a = e.target.closest?.('.ai-doc'); if (a) { e.preventDefault(); openDoc(a.dataset.doc); } };
  if (it.kind === 'user') return html`<div class="ai-msg user"><div class="ai-bub">${it.text}${it.attach && html`<div class="hint">📎 ${it.attach}</div>`}</div></div>`;
  if (it.kind === 'text') return it.text ? html`<div class="ai-msg bot" onClick=${click}><div class="ai-bub" dangerouslySetInnerHTML=${{ __html: md(it.text) }} /></div>` : null;
  if (it.kind === 'activity') return html`<div class="ai-act">${it.text}${it.link && html` <a class="ai-doc" onClick=${() => openDoc(it.link)}>open</a>`}</div>`;
  if (it.kind === 'image') return html`<div class="ai-img"><a href=${it.url} target="_blank" title="Open full size"><img src=${it.url} loading="lazy" /></a>${it.caption && html`<div class="hint">${it.caption}</div>`}</div>`;
  if (it.kind === 'proposal') return html`<${Proposal} it=${it} />`;
  if (it.kind === 'question') return html`<${Question} it=${it} />`;
  if (it.kind === 'style_round') return html`<${StyleRound} it=${it} />`;
  if (it.kind === 'error') return html`<div class="ai-err">⚠ ${it.text}</div>`;
  if (it.kind === 'usage') return html`<div class="ai-use" title="Claude API cost (your own key)">this reply $${it.cost.toFixed(3)} · ${Math.round(it.tokens_in / 1000)}k in / ${(it.tokens_out / 1000).toFixed(1)}k out · project total $${it.project_cost.toFixed(2)}</div>`;
  return null;
}

function DocEditor({ path, close }) {
  const [text, setText] = useState(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { api('/api/assistant/doc', { path }).then(r => setText(r.text)).catch(e => { toast(e.message, 'error'); close(); }); }, [path]);
  const save = () => api('/api/assistant/doc', { path, text }).then(() => { setDirty(false); toast(`Saved ${path} — tell the AI Editor when you're done`, 'ok'); })
    .catch(e => toast(e.message, 'error'));
  return html`<div class="scrim" onPointerDown=${e => e.target === e.currentTarget && !dirty && close()}>
    <div class="dialog" style="width:min(900px, calc(100vw - 32px))">
      <div class="dh"><h2>📝 ${path}</h2><span style="flex:1" /><button class="btn ghost icon" onClick=${() => (!dirty || confirm('Close without saving?')) && close()}><${Icon} n="x" /></button></div>
      <div class="db">${text === null ? html`<div class="hint">Loading…</div>`
        : html`<textarea class="input ai-doc-ta" spellcheck="true" value=${text} onInput=${e => { setText(e.target.value); setDirty(true); }} />`}
        <div class="hint" style="margin-top:6px">Your edits win: the AI Editor re-reads this file and treats your version as the source of truth.</div></div>
      <div class="df"><button class="btn" onClick=${() => (!dirty || confirm('Close without saving?')) && close()}>Close</button>
        <button class="btn primary" disabled=${!dirty} onClick=${save}>Save</button></div>
    </div></div>`;
}

// ---------------------------------------------------------------- the panel
export function AssistantPanel() {
  const ai = useStore(s => s.ai);
  const proj = useStore(s => s.projectName);
  const [text, setText] = useState('');
  const [attach, setAttach] = useState(null);
  const [doc, setDoc] = useState(null);
  const listRef = useRef();
  const fileRef = useRef();
  useEffect(() => { loadAssistant(); }, [proj]);
  useEffect(() => {                                                  // a chat needs room: widen the tool panel while open
    const root = document.documentElement;
    const prev = getComputedStyle(root).getPropertyValue('--fx-w');
    if (parseFloat(prev) < 440) root.style.setProperty('--fx-w', '440px');
    return () => root.style.setProperty('--fx-w', prev);
  }, []);
  const n = ai?.chat?.display?.length || 0;
  const last = ai?.chat?.display?.[n - 1];
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [n, last?.text?.length, last?.status]);
  if (!ai) return html`<div class="hint" style="padding:12px">Loading the AI Editor…</div>`;
  const busy = ai.status?.busy;
  const cfg = ai.config || {};
  const send = async () => {
    const t = text.trim();
    if ((!t && !attach) || busy) return;
    try {
      const r = await api('/api/assistant/send', { text: t, chat: ai.chat?.id, attach });
      setText(''); setAttach(null);
      if (!ai.chat || ai.chat.id !== r.chat) loadAssistant(r.chat);
    } catch (e) { toast(e.message, 'error'); }
  };
  const pick = async e => {
    const f = e.target.files?.[0]; e.target.value = '';
    if (!f) return;
    if (f.size > 400000) return toast('Please attach a text file under 400 KB (.md / .txt)', 'error');
    setAttach({ name: f.name, text: await f.text() });
  };
  const newChat = () => api('/api/assistant/new', {}).then(r => set({ ai: { ...ai, chat: r.chat, chats: r.chats } }));
  return html`<div class="ai-panel">
    <div class="ai-top">
      <select class="input ai-chats" value=${ai.chat?.id || ''} onChange=${e => loadAssistant(e.target.value)} title="Chats of this project">
        ${!ai.chat && html`<option value="">No chat yet</option>`}
        ${ai.chats.map(c => html`<option value=${c.id}>${c.title || c.id}</option>`)}
      </select>
      <button class="btn ghost icon" title="New chat" onClick=${newChat}><${Icon} n="plus" s=${15} /></button>
      <span class="ai-cost" title="Claude API cost of this project so far (your own key)">$${(ai.usage?.cost || 0).toFixed(2)}</span>
      <button class="btn ghost icon" title="AI Editor settings (key, model, budget)" onClick=${() => set({ dialog: 'aiSettings' })}><${Icon} n="sliders" s=${15} /></button>
    </div>
    <${Stepper} wf=${ai.workflow} />
    <div class="ai-list" ref=${listRef}>
      ${!cfg.key_set && html`<div class="ai-card"><div class="ai-card-h"><${Icon} n="sparkle" s=${15} /><b>Add your Anthropic API key</b></div>
        <div class="ai-card-b">The AI Editor uses <b>your own</b> Claude API key. A typical 2–5 min video costs about $3–4 on ${cfg.models?.[cfg.model] || 'Claude Opus 5.5'}.
        Add it on the <b>API Keys</b> page (menu bar): it is encrypted on this computer, protected by your password, and never shown again.</div>
        <div class="ai-acts"><button class="btn primary small" onClick=${openKeys}>Open API Keys</button></div></div>`}
      ${cfg.key_set && n === 0 && html`<div class="ai-hello">
        <div class="ai-h">Hi! I edit the video in this project with you.</div>
        <div>Start by sending your <b>original script draft or idea</b> (type it or attach a .md / .txt). I'll look at all your footage and write an
        updated complete script into an editable file for you to review. Then we decide the <b>style and duration</b> together, test it, plan, and build.</div>
        <div class="hint" style="margin-top:6px">I never change the video before you press <b>Approve</b>. I only do video editing for this project.</div></div>`}
      ${(ai.chat?.display || []).map(it => html`<${Item} key=${it.i} it=${it} openDoc=${setDoc} />`)}
      ${busy && ai.status?.chat === ai.chat?.id && html`<div class="ai-act ai-working"><span class="ai-dot" /> working…</div>`}
    </div>
    <div class="ai-input">
      ${attach && html`<div class="ai-attach">📎 ${attach.name} <button class="btn ghost small" onClick=${() => setAttach(null)}>remove</button></div>`}
      <textarea class="input" rows="3" placeholder=${cfg.key_set ? 'Message the AI Editor… (Enter to send, Shift+Enter for a new line)' : 'Add your API key first'}
        disabled=${!cfg.key_set} value=${text} onInput=${e => setText(e.target.value)}
        onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
      <div class="ai-input-row">
        <input type="file" accept=".md,.txt,text/plain,text/markdown" ref=${fileRef} style="display:none" onChange=${pick} />
        <button class="btn ghost small" title="Attach your script / idea (.md or .txt)" disabled=${!cfg.key_set} onClick=${() => fileRef.current.click()}>📎 Attach</button>
        <span style="flex:1" />
        ${busy ? html`<button class="btn small danger" onClick=${() => api('/api/assistant/stop', {})}>⏹ Stop</button>`
               : html`<button class="btn primary small" disabled=${!cfg.key_set || (!text.trim() && !attach)} onClick=${send}>Send</button>`}
      </div>
    </div>
    ${doc && html`<${DocEditor} path=${doc} close=${() => setDoc(null)} />`}
  </div>`;
}

// ---------------------------------------------------------------- settings dialog (Edit ▸ AI Editor Settings…)
export function AssistantSettingsDialog({ close, Dialog }) {
  const [cfg, setCfg] = useState(null);
  const [msg, setMsg] = useState('');
  useEffect(() => { api('/api/assistant/config').then(setCfg); }, []);
  if (!cfg) return null;
  const save = async patch => {
    try { const r = await api('/api/assistant/config', patch); setCfg(r); if (S.ai) set({ ai: { ...S.ai, config: r } }); return r; }
    catch (e) { toast(e.message, 'error'); }
  };
  const test = () => api('/api/assistant/test_key', {}).then(r => setMsg((r.ok ? '✅ ' : '⚠ ') + r.message)).catch(e => setMsg('⚠ ' + e.message));
  return html`<${Dialog} title="AI Editor settings" width=${520} footer=${html`<button class="btn primary" onClick=${close}>Done</button>`}>
    <div class="field wide"><label>Claude API key</label>
      <div style="display:flex;gap:6px;flex:1;align-items:center"><span>${cfg.key_set ? `Saved ${cfg.key_masked} (${cfg.key_source})` : 'Not set'}</span><span style="flex:1" />
        <button class="btn" onClick=${openKeys}>Manage API keys…</button>
        <button class="btn" disabled=${!cfg.key_set} onClick=${test}>Test</button></div></div>
    <div class="hint">Keys are added, changed and removed only on the API Keys page, with your password. They are encrypted on this computer and never shown again.</div>
    ${msg && html`<div style="margin:6px 0">${msg}</div>`}
    <div class="field wide"><label>Model</label><select class="input" value=${cfg.model} onChange=${e => save({ model: e.target.value })}>
      ${Object.entries(cfg.models).map(([id, name]) => html`<option value=${id}>${name}${id === 'claude-opus-5-5' ? ' — best judgement (≈$3–4 / video)' : ' — faster, about half the cost'}</option>`)}</select></div>
    <div class="field wide"><label>Thinking effort</label><select class="input" value=${cfg.effort} onChange=${e => save({ effort: e.target.value })}>
      ${cfg.efforts.map(x => html`<option value=${x}>${x}${x === 'medium' ? ' (default)' : ''}</option>`)}</select></div>
    <div class="field wide"><label>Budget per project ($)</label><input class="input" type="number" min="0" step="0.5" placeholder="no limit" value=${cfg.budget_usd ?? ''}
      onChange=${e => save({ budget_usd: e.target.value })} /></div>
    <div class="hint">The AI Editor stops before a request once a project's spending reaches the budget.</div>
  </${Dialog}>`;
}
