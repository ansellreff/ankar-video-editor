// Update reminder (Help ▸ What's new, red dot on Help, banner). The server asks the website once a day — anonymously:
// nothing about you or your projects is sent. Download opens the AnKar website (sign in there to download).
import { html, useState } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';
import { api } from './api.js';
import { Icon } from './util.js';

export async function loadUpdate(force = false) {
  try { set({ update: await api('/api/update' + (force ? '?force=1' : '')) }); }
  catch (e) { /* offline: no reminder */ }
  return S.update;
}

export function startUpdateChecks() {
  setTimeout(() => loadUpdate(), 4000);                       // after start-up work
  setInterval(() => loadUpdate(), 6 * 3600 * 1000);           // the server only really asks once a day
}

function openDownload() {
  const u = S.update?.download_page;
  if (u && /^https?:\/\//.test(u)) window.open(u, '_blank', 'noopener,noreferrer');
}

const dismissedKey = 'vs-update-dismissed';
function dismissed(v) { try { return localStorage.getItem(dismissedKey) === v; } catch (e) { return false; } }

export function UpdateBanner() {
  const u = useStore(s => s.update);
  const [, force] = useState(0);
  if (!u?.newer || dismissed(u.latest)) return html`<div class="update-slot" />`;   // keeps the shell's grid rows
  const hide = () => { try { localStorage.setItem(dismissedKey, u.latest); } catch (e) { /* ignore */ } force(x => x + 1); };
  return html`<div class="update-banner" role="status">
    <${Icon} n="sparkle" s=${14} /><span><b>AnKar Video Editor ${u.latest}</b> is available (you have ${u.current}).</span>
    <button class="btn small" onClick=${() => set({ dialog: 'whatsnew' })}>What's new</button>
    <button class="btn small primary" onClick=${openDownload}>Download</button>
    <span style="flex:1" /><button class="btn ghost icon small" title="Hide until the next version" onClick=${hide}><${Icon} n="x" s=${12} /></button>
  </div>`;
}

function Notes({ rel }) {
  return html`<div class="wn-rel"><div class="wn-head"><b>${rel.version}</b><span class="hint">${rel.date}</span></div>
    <ul>${rel.notes.map(n => html`<li>${n}</li>`)}</ul></div>`;
}

export function WhatsNewDialog({ close, Dialog }) {
  const u = useStore(s => s.update);
  const [busy, setBusy] = useState(false);
  const check = async () => { setBusy(true); await loadUpdate(true); setBusy(false); };
  const local = u?.local_notes || [];
  const status = !u ? 'Checking…'
    : u.disabled ? 'Update checks are turned off (ANKAR_UPDATE_CHECK=0).'
    : u.newer ? `Version ${u.latest} is available.`
    : u.latest ? `You have the latest version (${u.current}).`
    : 'Could not reach the AnKar website (offline?). Your version still works normally.';
  return html`<${Dialog} title="What's new" width=${620} footer=${html`
      <span class="hint">You have version <b>${u?.current || '…'}</b>. Checking sends nothing about you or your projects.</span>
      <span style="flex:1" />
      <button class="btn" disabled=${busy} onClick=${check}>${busy ? 'Checking…' : 'Check now'}</button>
      ${u?.newer && html`<button class="btn primary" onClick=${openDownload}>Download ${u.latest}</button>`}`}>
    <div class=${`wn-status ${u?.newer ? 'new' : ''}`}>${status}</div>
    ${u?.newer && html`<p class="hint">Download the new zip from the website, close this editor, then drag the zip onto
      <b>Update AnKar Video Editor.bat</b> in your AnKar folder (or just double-click it — it finds the newest zip in Downloads).
      Your projects, voices and keys stay.</p>
      <h3 class="wn-h">New since your version</h3>${u.notes.map(r => html`<${Notes} rel=${r} />`)}`}
    ${local.length > 0 && html`<h3 class="wn-h">${u?.newer ? 'Your version and earlier' : 'This version and earlier'}</h3>
      ${local.slice(0, 8).map(r => html`<${Notes} rel=${r} />`)}`}
  </${Dialog}>`;
}
