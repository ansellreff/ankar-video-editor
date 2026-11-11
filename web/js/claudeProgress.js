// "Claude is editing" pop-up: what Claude is doing right now while it edits for you (server: app/claude_progress.py).
// Open = the panel · Minimize = back to the round icon (bottom-left, % ring; hover shows the current step) · Close =
// hidden until View ▸ Claude Progress (or a new job starts). Sections Now / Up next / Done / Earlier work can each be expanded or collapsed (remembered).
import { html, useState, useEffect, useRef } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';

const LS = 'vs-claude-progress';
function load() { try { return JSON.parse(localStorage.getItem(LS) || '{}'); } catch (e) { return {}; } }
function save(p) { try { localStorage.setItem(LS, JSON.stringify({ ...load(), ...p })); } catch (e) { /* storage blocked */ } }

export async function loadClaudeProgress() {
  try { const r = await fetch('/api/claude/progress').then(x => x.json()); set({ claudeProg: r, claudeProgAt: Date.now() }); } catch (e) { /* server older */ }
}
export function onClaudeProgress(data) {
  const prev = S.claudeProg?.job;
  set({ claudeProg: data, claudeProgAt: Date.now() });
  if (data.job && (!prev || prev.id !== data.job.id) && S.claudeView === 'closed') setView('open');   // a new job pops it open
}
export function setView(v) { set({ claudeView: v }); save({ view: v }); }
export function toggleClaudeProgress() { setView(S.claudeView === 'open' ? 'closed' : 'open'); }

// ---------------------------------------------------------------- position (draggable, remembered; anchored bottom-left)
const DEF_POS = { left: 16, bottom: 16 };
function getPos() { return S.claudePos || load().pos || DEF_POS; }
// pos = where the round icon sits (its bottom-left corner); the panel opens from there
const ICON_PX = 52;
const PANEL_W = 380;
let panelH = 520;                     // the open panel's real height (measured after each render)
const ph = () => Math.min(panelH, window.innerHeight - 16);
function clampPos(p, w = ICON_PX, h = ICON_PX) {
  return { left: Math.round(Math.min(Math.max(8, p.left), window.innerWidth - w - 8)),
           bottom: Math.round(Math.min(Math.max(8, p.bottom), window.innerHeight - h - 8)) };
}
// The panel's bottom lines up with the icon's bottom; its top is always kept ≥ 8 px inside the window, so the title
// bar can never leave the screen (whatever position was saved, whatever the window size).
function panelBox(pos) {
  const H = window.innerHeight, h = ph();
  const top = Math.min(Math.max(8, H - pos.bottom - h), Math.max(8, H - h - 8));
  const left = Math.min(Math.max(8, pos.left), window.innerWidth - PANEL_W - 8);
  return { top, left, maxH: H - top - 8 };
}
function panelStyle(pos) {
  const b = panelBox(pos);
  return `left:${b.left}px;top:${b.top}px;bottom:auto;max-height:${b.maxH}px`;
}
export function resetClaudePosition() { set({ claudePos: DEF_POS }); save({ pos: DEF_POS }); if (S.claudeView === 'closed') setView('launcher'); }
// drag the pop-up / icon; calls done(moved) on release (a click that didn't move still opens / works normally)
function startDrag(e, el, done, isPanel = false) {
  if (e.button !== 0) return;
  const r = { width: isPanel ? PANEL_W : ICON_PX, height: isPanel ? ph() : ICON_PX };
  const x0 = e.clientX, y0 = e.clientY;
  let p0 = getPos();
  if (isPanel) {                                   // start from where the panel really is (it may have been pushed in)
    const b = panelBox(p0);
    p0 = { left: b.left, bottom: window.innerHeight - b.top - r.height };
  }
  let moved = false;
  const mv = ev => {
    const dx = ev.clientX - x0, dy = ev.clientY - y0;
    if (!moved && Math.hypot(dx, dy) < 4) return;
    if (!moved) { moved = true; el.classList.add('cp-dragging'); }
    set({ claudePos: clampPos({ left: p0.left + dx, bottom: p0.bottom - dy }, r.width, r.height) });
  };
  const up = () => {
    window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up);
    el.classList.remove('cp-dragging');
    if (moved) save({ pos: S.claudePos });
    done && done(moved);
  };
  window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
}

const fmt = s => {
  if (s == null) return '—';
  s = Math.max(0, Math.round(s));
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  return `${s}s`;
};
const clock = t => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function Ring({ pct, size = 44, stroke = 4, busy }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r;
  return html`<svg class=${`cp-ring ${busy ? 'busy' : ''}`} width=${size} height=${size} viewBox=${`0 0 ${size} ${size}`}>
    <circle cx=${size / 2} cy=${size / 2} r=${r} class="trk" stroke-width=${stroke} />
    <circle cx=${size / 2} cy=${size / 2} r=${r} class="val" stroke-width=${stroke}
      stroke-dasharray=${c} stroke-dashoffset=${c * (1 - Math.min(1, pct || 0))} transform=${`rotate(-90 ${size / 2} ${size / 2})`} />
  </svg>`;
}

const ICON = { done: '✓', active: '', pending: '', skipped: '–', error: '!' };

function Step({ s, now }) {
  const [open, setOpen] = useState(s.status === 'active');
  useEffect(() => { if (s.status === 'active') setOpen(true); }, [s.status]);
  const took = s.started ? ((s.ended || now) - s.started) : null;
  const time = s.status === 'done' || s.status === 'error' ? fmt(took) : s.status === 'active' ? `${fmt(took)} / ~${fmt(s.est)}` : `~${fmt(s.est)}`;
  const hasMore = (s.log && s.log.length) || s.detail;
  return html`<div class=${`cp-step ${s.status}`}>
    <button class="cp-step-row" onClick=${() => hasMore && setOpen(!open)}>
      <span class="cp-dot">${s.status === 'active' ? html`<span class="spinner" />` : ICON[s.status]}</span>
      <span class="cp-step-title">${s.title}</span>
      <span class="cp-step-time">${time}</span>
      ${hasMore ? html`<span class=${`cp-chev ${open ? 'open' : ''}`}>›</span>` : html`<span class="cp-chev" />`}
    </button>
    ${open && hasMore ? html`<div class="cp-step-more">
      ${s.detail ? html`<div class="cp-detail">${s.detail}</div>` : null}
      ${(s.log || []).slice().reverse().map(l => html`<div class="cp-log"><span>${clock(l.t)}</span>${l.text}</div>`)}
    </div>` : null}
  </div>`;
}

function Section({ id, title, count, children, def = true }) {
  const [open, setOpen] = useState(() => load().sec?.[id] ?? def);
  const flip = () => { const v = !open; setOpen(v); save({ sec: { ...(load().sec || {}), [id]: v } }); };
  if (!count) return null;
  return html`<div class="cp-sec">
    <button class="cp-sec-head" onClick=${flip}><span class=${`cp-chev ${open ? 'open' : ''}`}>›</span>${title}<span class="cp-count">${count}</span></button>
    ${open ? html`<div class="cp-sec-body">${children}</div>` : null}
  </div>`;
}

export function ClaudeProgress() {
  const prog = useStore(s => s.claudeProg);
  const at = useStore(s => s.claudeProgAt);
  const view = useStore(s => s.claudeView);
  const pos = useStore(s => s.claudePos) || getPos();
  const [now, setNow] = useState(Date.now() / 1000);
  const dragged = useRef(false);                             // a drag must not also count as a click (open)
  const panelRef = useRef(null);
  const [, bump] = useState(0);
  useEffect(() => {                                          // learn the panel's real height → keep its title bar on screen
    const el = panelRef.current;
    if (el && Math.abs(el.offsetHeight - panelH) > 4) { panelH = el.offsetHeight; bump(x => x + 1); }
  });
  useEffect(() => {                                          // …also when a section inside is expanded / collapsed
    const el = panelRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      const lists = el.querySelector('.cp-lists');
      const natural = el.offsetHeight - (lists ? lists.clientHeight - lists.scrollHeight : 0);   // height it wants
      if (Math.abs(natural - panelH) > 4) { panelH = natural; bump(x => x + 1); }
    });
    ro.observe(el);
    const lists = el.querySelector('.cp-lists');
    if (lists) [...lists.children].forEach(c => ro.observe(c));
    return () => ro.disconnect();
  }, [view, prog?.job?.id]);
  useEffect(() => {                                          // keep it on screen when the window is resized
    const f = () => set({ claudePos: clampPos(getPos()) });
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, [view]);
  const job = prog?.job, hist = prog?.history || [];
  const running = !!job && !job.ended;
  useEffect(() => {
    if (S.claudeView == null) set({ claudeView: ['open', 'closed'].includes(load().view) ? load().view : 'launcher' });
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    const p = setInterval(() => { if (S.claudeProg?.job && !S.claudeProg.job.ended) loadClaudeProgress(); }, 4000);
    return () => { clearInterval(t); clearInterval(p); };
  }, []);
  if (view === 'closed' || (!job && !hist.length)) return null;
  const since = at ? (Date.now() - at) / 1000 : 0;
  const eta = running && job.eta != null ? Math.max(0, job.eta - since) : null;
  const pct = job ? job.pct : 0;
  const P = Math.round(pct * 100);
  const steps = job?.steps || [];
  const doneS = steps.filter(s => s.status === 'done' || s.status === 'skipped' || s.status === 'error');
  const nowS = steps.filter(s => s.status === 'active');
  const nextS = steps.filter(s => s.status === 'pending');
  const headline = running ? (job.current || 'Getting ready…') : job ? 'All done ✓' : 'No editing right now';

  const place = `left:${pos.left}px;bottom:${pos.bottom}px`;
  if (view !== 'open') {                                    // minimized = the round icon (hover shows what Claude is doing)
    const right = pos.left > window.innerWidth / 2;          // near the right edge: the hover card goes to the left
    return html`<div class=${`cp-dock ${right ? 'flip' : ''}`} style=${place}>
      <button class=${`cp-launch ${running ? 'running' : ''}`} aria-label="Open Claude editing progress" title="Click to open · drag to move"
        onPointerDown=${e => { dragged.current = false; startDrag(e, e.currentTarget.parentElement, moved => { dragged.current = moved; }); }}
        onClick=${() => { if (dragged.current) { dragged.current = false; return; } setView('open'); }}>
        <${Ring} pct=${pct} busy=${running} />
        <span class="cp-launch-in">${running ? `${P}%` : job ? '✓' : 'C'}</span>
      </button>
      <div class="cp-tip"><b>${running ? `${P}% · ${headline}` : headline}</b>
        <span>${running ? (eta != null ? `about ${fmt(eta)} left · click to open` : 'click to open') : 'click to see the steps'}</span></div>
    </div>`;
  }
  const stop = f => e => { e.preventDefault(); e.stopPropagation(); f(); };
  const grab = e => { if (!e.target.closest('button')) startDrag(e, panelRef.current, null, true); };
  return html`<div class="cp-panel" ref=${panelRef} style=${panelStyle(pos)} onPointerDown=${e => e.stopPropagation()}>
    <div class="cp-head" title="Drag to move" onPointerDown=${grab}>
      <div class="cp-badge">C</div>
      <div class="cp-head-txt"><b>Claude is editing</b><span>${job ? job.title : 'History'}</span></div>
      <button type="button" class="cp-ibtn" title="Minimize to icon" aria-label="Minimize" onClick=${stop(() => setView('launcher'))}>
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M2 6h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
      <button type="button" class="cp-ibtn" title="Close (View ▸ Claude Progress to reopen)" aria-label="Close" onClick=${stop(() => setView('closed'))}>
        <svg width="12" height="12" viewBox="0 0 12 12"><path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
    </div>
    ${job ? html`<div class="cp-hero" title="Drag to move" onPointerDown=${grab}>
      <div class="cp-big"><span class="cp-pct">${P}<small>%</small></span>
        <div class="cp-times"><div><span>Elapsed</span><b>${fmt(running ? job.elapsed + since : job.elapsed)}</b></div>
          <div><span>Time left</span><b>${running ? (eta != null ? `~${fmt(eta)}` : '—') : 'done'}</b></div></div></div>
      <div class=${`bar cp-bar ${running ? 'live' : ''}`}><i style=${`width:${Math.max(2, P)}%`} /></div>
      <div class="cp-now">${running ? html`<span class="spinner" />` : html`<span class="cp-ok">✓</span>`}<div><b>${headline}</b>
        ${running && job.current_detail ? html`<span>${job.current_detail}</span>` : null}${!running && job.note ? html`<span>${job.note}</span>` : null}</div></div>
    </div>` : null}
    <div class="cp-lists">
      <${Section} id="now" title="Now" count=${nowS.length}>${nowS.map(s => html`<${Step} key=${s.id} s=${s} now=${now} />`)}<//>
      <${Section} id="next" title="Up next" count=${nextS.length}>${nextS.map(s => html`<${Step} key=${s.id} s=${s} now=${now} />`)}<//>
      <${Section} id="done" title="Done" count=${doneS.length} def=${false}>${doneS.slice().reverse().map(s => html`<${Step} key=${s.id} s=${s} now=${now} />`)}<//>
      <${Section} id="hist" title="Earlier work" count=${hist.length} def=${false}>${hist.map(h => html`<div class="cp-hist">
        <div class="cp-hist-top"><b>${h.title}</b><span>${new Date(h.started * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' })} ${clock(h.started)} · ${fmt(h.ended - h.started)}</span></div>
        <div class="cp-hist-sub">${h.done}/${h.total} steps${h.note ? ` · ${h.note}` : ''}</div></div>`)}<//>
    </div>
  </div>`;
}
