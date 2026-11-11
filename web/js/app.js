import { html, render, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore, fps, toast } from './store.js';
import { loadState, connectEvents } from './api.js';
import { A } from './actions.js';
import { player } from './player.js';
import { MenuBar } from './menubar.js';
import { Ribbon } from './ribbon.js';
import { ProjectPanel } from './projectPanel.js';
import { Monitor } from './monitor.js';
import { EffectsPanel } from './effectsPanel.js';
import { Inspector } from './inspector.js';
import { Timeline } from './timeline.js';
import { Dialogs, ContextMenu, Toasts } from './dialogs.js';
import { nudge } from './gizmo.js';
import { nudge as nudgeSentence } from './sentences.js';
import { ClaudeProgress, loadClaudeProgress } from './claudeProgress.js';
import { UpdateBanner, startUpdateChecks } from './updates.js';

// ---------------------------------------------------------------- panel sizes (remembered per browser)
const SIZES = { '--left-w': [300, 200, 560], '--fx-w': [250, 190, 760], '--insp-w': [320, 240, 520], '--tl-h': [340, 180, 720] };
function loadSizes() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('vs-sizes') || '{}'); } catch (e) { /* storage blocked */ }
  for (const [k, [def]] of Object.entries(SIZES)) document.documentElement.style.setProperty(k, (saved[k] ?? def) + 'px');
}
function saveSize(k, v) {
  try { const s = JSON.parse(localStorage.getItem('vs-sizes') || '{}'); s[k] = v; localStorage.setItem('vs-sizes', JSON.stringify(s)); } catch (e) { /* ignore */ }
}
function Resizer({ v, dir = 1, row = false }) {
  const down = e => {
    e.preventDefault();
    const el = e.currentTarget; el.classList.add('active');
    const start = row ? e.clientY : e.clientX;
    const base = parseFloat(getComputedStyle(document.documentElement).getPropertyValue(v));
    const [, lo, hi] = SIZES[v];
    let val = base;
    const mv = ev => { val = Math.min(hi, Math.max(lo, base + dir * ((row ? ev.clientY : ev.clientX) - start))); document.documentElement.style.setProperty(v, val + 'px'); player.invalidate(); };
    const up = () => { el.classList.remove('active'); window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); saveSize(v, val); };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
  };
  return html`<div class=${`resizer ${row ? 'row' : ''}`} onPointerDown=${down} />`;
}

// ---------------------------------------------------------------- keyboard
function onKey(e) {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
  if (S.dialog && e.key !== 'Escape') return;
  const ctrl = e.ctrlKey || e.metaKey, k = e.key;
  const run = (f, ...a) => { e.preventDefault(); f(...a); };
  if (ctrl) {
    const kl = k.toLowerCase();
    if (k.startsWith('Arrow')) {                              // nudge the selected layer in the monitor
      const st = e.shiftKey ? 10 : 1;
      const [dx, dy] = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st] }[k];
      if (nudge(dx, dy)) e.preventDefault();
      return;
    }
    if (kl === 'k' && e.shiftKey) return run(A.splitAll);
    if (kl === 'c' && e.shiftKey) return run(A.autoCaptions);
    if (kl === 'm') return run(() => A.dialog('export'));      // Premiere's Export shortcut (Ctrl+E also works)
    if (kl === 's' && e.shiftKey) return run(A.saveAs);
    if (kl === 'n' && e.altKey) return run(A.newProject);
    if (kl === 'n' && e.shiftKey) return run(() => A.addNarration?.());
    if (kl === 'o') return run(() => A.openProject('open'));
    if (kl === 'r') return run(A.speedDialog);
    if (kl === 'z' && e.shiftKey) return run(A.redo);
    if (kl === 'z') return run(A.undo);
    if (kl === 'y') return run(A.redo);
    if (kl === 'k') return run(A.split);
    if (kl === 'c') return run(A.copy);
    if (kl === 'x') return run(A.cut);
    if (kl === 'v') return run(A.paste);
    if (kl === 'a') return run(A.selectAll);
    if (kl === 'd') return run(() => A.applyTransition('cross_dissolve'));
    if (kl === 't') return run(() => A.addText('title'));
    if (kl === 'l') return run(A.unlink);
    if (kl === 'e') return run(() => A.dialog('export'));
    if (kl === 's') return run(A.save);
    return;
  }
  if (e.altKey && k.toLowerCase() === 'x') return run(A.clearInOut);
  if (S.sent && (k === 'ArrowLeft' || k === 'ArrowRight')) {          // a narration sentence is selected: nudge it
    if (nudgeSentence(k === 'ArrowLeft' ? -1 : 1, e.shiftKey)) return e.preventDefault();
  }
  if (S.sent && k === 'Escape') return run(() => set({ sent: null }));
  switch (k) {
    case ' ': return run(A.play);
    case 'ArrowLeft': return run(A.step, e.shiftKey ? -Math.round(fps()) : -1);
    case 'ArrowRight': return run(A.step, e.shiftKey ? Math.round(fps()) : 1);
    case 'ArrowUp': return run(A.jumpEdit, -1);
    case 'ArrowDown': return run(A.jumpEdit, 1);
    case 'Home': return run(A.goStart);
    case 'End': return run(A.goEnd);
    case 'Delete': case 'Backspace': return run(A.del, e.shiftKey);
    case 'Escape': return run(A.deselect);
    case 'F5': return run(A.rescan);
    case '=': case '+': return run(A.zoom, 1.4);
    case '-': case '_': return run(A.zoom, 1 / 1.4);
    case '\\': return run(A.zoomFit);
    case '?': return run(A.dialog, 'shortcuts');
  }
  switch (k.toLowerCase()) {
    case 'j': return run(() => { player.pause(); player.seek(S.t - 1); });
    case 'k': return run(() => player.pause());
    case 'l': return run(() => player.play());
    case 'v': return run(A.tool, 'select');
    case 'c': return run(A.tool, 'razor');
    case 'r': return run(A.tool, 'rate');
    case 'f': if (e.shiftKey) return run(A.freeze, 'insert', 2); return run(A.matchFrame);
    case 's': return run(A.toggleSnap);
    case 'm': return run(A.marker);
    case 'p': return run(A.goToPlayhead);
    case 'i': return run(A.setIn);
    case 'o': return run(A.setOut);
    case 'e': if (e.shiftKey) return run(A.toggleEnabled); break;
  }
}

function App() {
  const ready = useStore(s => !!s.project && !!s.presets);
  useEffect(() => { window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey); }, []);
  if (!ready) return html`<div class="boot">Loading AnKar Video Editor…</div>`;
  return html`<div class="shell">
    <${MenuBar} />
    <${UpdateBanner} />
    <${Ribbon} />
    <div class="workspace">
      <${ProjectPanel} />
      <${Resizer} v="--left-w" />
      <${Monitor} />
      <${Resizer} v="--fx-w" dir=${-1} />
      <${EffectsPanel} />
      <${Resizer} v="--insp-w" dir=${-1} />
      <${Inspector} />
    </div>
    <${Resizer} v="--tl-h" dir=${-1} row=${true} />
    <${Timeline} />
    <${Dialogs} /><${ContextMenu} /><${Toasts} /><${ClaudeProgress} />
  </div>`;
}

loadSizes();
loadState().then(() => {
  render(html`<${App} />`, document.getElementById('app'));
  connectEvents();
  loadClaudeProgress();
  startUpdateChecks();
  setTimeout(() => A.zoomFit(), 300);
}).catch(e => {
  document.getElementById('app').innerHTML = `<div class="boot">Could not reach the AnKar Video Editor server: ${e.message}</div>`;
});
window.__vs = { S, set, A, player, toast };   // handy for debugging in the browser console
