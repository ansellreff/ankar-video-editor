import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';
import { A } from './actions.js';
import { Icon } from './util.js';
import { toggleClaudeProgress, resetClaudePosition } from './claudeProgress.js';

/** API keys live on their own page (/keys): key handling stays apart from the editor's scripts. */
export const openKeysPage = () => window.open('/keys', 'vs-keys');

const sep = { sep: true };

function menus() {
  const h = S.history || {};
  const fmt = S.project?.format.preset;
  const hasSel = S.sel.clips.length > 0;
  return [
    ['File', [
      { label: 'New Project…', kbd: 'Ctrl+Alt+N', run: A.newProject },
      { label: 'Open Project…', kbd: 'Ctrl+O', run: () => A.openProject('open') },
      ...((S.projects || []).filter(p => !p.current).sort((a, b) => a.recent - b.recent).slice(0, 5)
        .map(p => ({ label: `   ${p.name}`, run: () => A.switchProject(p.name) }))),
      sep,
      { label: 'Save Checkpoint', kbd: 'Ctrl+S', run: A.save },
      { label: 'Save As…', kbd: 'Ctrl+Shift+S', run: A.saveAs },
      { label: 'Rename Project…', run: A.renameProject },
      { label: 'Revert to Checkpoint…', run: () => A.openProject('checkpoints'), off: !(S.checkpoints || []).length },
      sep,
      { label: 'Open Assets Folder', run: () => A.open('assets') },
      { label: 'Open Import Drop Folder', run: () => A.open('import') },
      { label: 'Open Exports Folder', run: () => A.open('exports') },
      { label: 'Rescan Assets', kbd: 'F5', run: A.rescan },
      sep,
      { label: 'Export Video…', kbd: 'Ctrl+E', run: () => A.dialog('export') },
      { label: 'Versions…', run: () => A.dialog('export') },
    ]],
    ['Edit', [
      { label: h.undo ? `Undo ${h.undo}` : 'Undo', kbd: 'Ctrl+Z', run: A.undo, off: !h.undo },
      { label: h.redo ? `Redo ${h.redo}` : 'Redo', kbd: 'Ctrl+Shift+Z', run: A.redo, off: !h.redo },
      sep,
      { label: 'Cut', kbd: 'Ctrl+X', run: A.cut, off: !hasSel },
      { label: 'Copy', kbd: 'Ctrl+C', run: A.copy, off: !hasSel },
      { label: 'Paste at Playhead', kbd: 'Ctrl+V', run: A.paste, off: !S.clipboard },
      { label: 'Delete', kbd: 'Del', run: () => A.del(false), off: !hasSel && !S.sel.transition },
      { label: 'Ripple Delete', kbd: 'Shift+Del', run: () => A.del(true), off: !hasSel },
      sep,
      { label: 'Feedback & Change Log…', run: () => A.dialog('changelog') },
      { label: 'AI Editor Settings…', run: () => A.dialog('aiSettings') },
      sep,
      { label: 'Select All', kbd: 'Ctrl+A', run: A.selectAll },
      { label: 'Deselect All', kbd: 'Esc', run: A.deselect },
    ]],
    ['Clip', [
      { label: 'Split at Playhead', kbd: 'Ctrl+K', run: A.split },
      { label: 'Add Edit to All Tracks', kbd: 'Ctrl+Shift+K', run: A.splitAll },
      { label: 'Speed / Duration…', kbd: 'Ctrl+R', run: A.speedDialog, off: !hasSel },
      { label: 'Insert Frame Hold (2 s)', kbd: 'Shift+F', run: () => A.freeze('insert', 2) },
      { label: 'Freeze Rest of Clip', run: () => A.freeze('rest') },
      { label: 'Rename Clip…', run: A.renameClip, off: !hasSel },
      { label: 'Match Frame (show source)', kbd: 'F', run: A.matchFrame, off: !hasSel },
      { label: 'Enable / Disable', kbd: 'Shift+E', run: A.toggleEnabled, off: !hasSel },
      { label: 'Unlink Audio & Video', kbd: 'Ctrl+L', run: A.unlink, off: !hasSel },
      { label: 'Link Selected', run: A.link, off: S.sel.clips.length < 2 },
      sep,
      { label: 'Speed 50%', run: () => A.speed(0.5), off: !hasSel },
      { label: 'Speed 100%', run: () => A.speed(1), off: !hasSel },
      { label: 'Speed 200%', run: () => A.speed(2), off: !hasSel },
      sep,
      { label: 'Add Fade In & Out (0.5 s)', run: () => A.fades(0.5), off: !hasSel },
      { label: 'Reset Motion & Crop', run: A.resetMotion, off: !hasSel },
    ]],
    ['Sequence', [
      { label: 'Add Video Track', run: () => A.addTrack('video') },
      { label: 'Add Audio Track', run: () => A.addTrack('audio') },
      { label: 'Add Text Track', run: () => A.addTrack('text') },
      sep,
      ...[['reels', 'Instagram Reels (1080×1920, 30 fps)'], ['9:16', '9:16 vertical (29.97 fps)'], ['16:9', '16:9 YouTube'], ['1:1', '1:1 square'], ['4:5', '4:5 portrait']].map(([p, l]) => ({ label: `Format: ${l}`, check: fmt === p, run: () => A.format(p) })),
      sep,
      { label: 'Add Marker', kbd: 'M', run: A.marker },
      { label: 'Set In Point', kbd: 'I', run: A.setIn },
      { label: 'Set Out Point', kbd: 'O', run: A.setOut },
      { label: 'Clear In / Out', kbd: 'Alt+X', run: A.clearInOut },
      { label: 'Loop Playback In→Out', check: S.loop, run: A.toggleLoop },
    ]],
    ['Effects', [
      { label: 'Add Cross Dissolve', kbd: 'Ctrl+D', run: () => A.applyTransition('cross_dissolve') },
      { label: 'Transitions…', run: () => set({ fxTab: 'transitions' }) },
      sep,
      { label: 'Effects & Looks…', run: () => set({ fxTab: 'filters' }) },
      { label: 'Color LUTs…', run: () => set({ fxTab: 'luts' }) },
      { label: 'Layouts (split screen, PiP)…', run: () => set({ fxTab: 'layouts' }) },
      { label: 'Motion Presets…', run: () => set({ fxTab: 'motion' }) },
    ]],
    ['Text', [
      { label: 'Add Title at Playhead', kbd: 'Ctrl+T', run: () => A.addText('title') },
      { label: 'Add Lower Third', run: () => A.addText('lower_third') },
      { label: 'Add Text Caption', run: () => A.addText('caption') },
      { label: 'Add Typed Intro (keyboard sound)…', run: () => A.dialog('intro') },
      sep,
      { label: 'Auto Captions…', kbd: 'Ctrl+Shift+C', run: A.autoCaptions },
      { label: 'Caption Styles & Review', run: () => set({ fxTab: 'captions' }) },
    ]],
    ['Audio', [
      { label: 'Voice from Video (clone a voice)…', run: () => A.voiceWizard() },
      { label: 'Add AI Narration at Playhead', kbd: 'Ctrl+Shift+N', run: () => A.addNarration?.() },
      { label: 'AI Voice Settings', run: () => set({ fxTab: 'voice' }) },
      sep,
      // track volumes (footage sound, music …) live in the Inspector's project view → show it and scroll there
      { label: 'Audio Mix (track volumes)…', run: () => {
        A.deselect();
        setTimeout(() => document.querySelector('[data-section="audio-mix"]')?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 60);
      } },
      sep,
      { label: 'Record Voiceover', run: A.recordVoiceover },
    ]],
    ['View', [
      { label: 'Zoom In', kbd: '=', run: () => A.zoom(1.4) },
      { label: 'Zoom Out', kbd: '-', run: () => A.zoom(1 / 1.4) },
      { label: 'Zoom to Fit', kbd: '\\', run: A.zoomFit },
      { label: 'Go to Playhead', kbd: 'P', run: A.goToPlayhead },
      sep,
      { label: 'Snapping', kbd: 'S', check: S.snap !== false, run: A.toggleSnap },
      { label: 'Safe Areas', check: S.safe, run: A.toggleSafe },
      { label: 'Claude Progress', check: S.claudeView === 'open', run: toggleClaudeProgress },
      { label: 'Reset Claude Progress Position', run: resetClaudePosition },
      sep,
      { label: 'Selection Tool', kbd: 'V', check: S.tool === 'select', run: () => A.tool('select') },
      { label: 'Razor Tool', kbd: 'C', check: S.tool === 'razor', run: () => A.tool('razor') },
      { label: 'Rate Stretch Tool', kbd: 'R', check: S.tool === 'rate', run: () => A.tool('rate') },
      sep,
      ...['fit', 0.25, 0.5, 1].map(z => ({ label: `Monitor ${z === 'fit' ? 'Fit' : z * 100 + '%'}`, check: (S.monZoom ?? 'fit') === z, run: () => set({ monZoom: z }) })),
    ]],
    ['Help', [
      { label: S.update?.newer ? `What's new — ${S.update.latest} available ●` : "What's new", run: () => A.dialog('whatsnew') },
      sep,
      { label: 'Keyboard Shortcuts', kbd: '?', run: () => A.dialog('shortcuts') },
      { label: 'How this project works', run: () => A.dialog('about') },
      { label: `About AnKar Video Editor${S.update?.current ? ' ' + S.update.current : ''}`, run: () => A.dialog('whatsnew') },
    ]],
  ];
}

export function MenuBar() {
  const [open, setOpen] = useState(null);
  useStore(s => [s.history, s.sel, s.clipboard, s.snap, s.safe, s.tool, s.loop, s.project?.format.preset, s.projects, s.checkpoints, s.monZoom, s.claudeView, s.update]);
  const hasUpdate = useStore(s => !!s.update?.newer);
  const connected = useStore(s => s.connected);
  const job = useStore(s => s.exportJob);
  const name = useStore(s => s.projectName);
  const task = useStore(s => s.task);
  useEffect(() => {
    const close = e => { if (!e.target.closest?.('.menu')) setOpen(null); };
    window.addEventListener('pointerdown', close);
    return () => window.removeEventListener('pointerdown', close);
  }, []);
  return html`<div class="menubar">
    <div class="brand"><span class="logo"><${Icon} n="play" s=${11} /></span>AnKar Video Editor</div>
    ${menus().map(([name, items]) => html`
      <div class=${`menu ${open === name ? 'open' : ''}`} onMouseEnter=${() => open && setOpen(name)}>
        <button onClick=${() => setOpen(open === name ? null : name)}>${name}${name === 'Help' && hasUpdate && html`<span class="dot-new" title="A new version is available" />`}</button>
        ${open === name && html`<div class="dropdown">${items.map(it => it.sep ? html`<div class="sep" />` : html`
          <button class="item" disabled=${it.off} onClick=${() => { setOpen(null); it.run(); }}>
            <span class="check">${it.check ? '✓' : ''}</span><span class="label">${it.label}</span>${it.kbd && html`<span class="kbd">${it.kbd}</span>`}
          </button>`)}</div>`}
      </div>`)}
    <div class="menu"><button title="Your own API keys for the AI Editor and AI Voice (password protected, opens its own page)"
      onClick=${() => { setOpen(null); openKeysPage(); }}>API Keys</button></div>
    <button class="proj-name" title="Open, create or manage projects" onClick=${() => A.openProject('open')}>
      <${Icon} n="folder" s=${13} /><span>${name}</span><span class="saved">All changes saved</span></button>
    <div class="right">
      ${task && html`<span class="pill">${task.name} ${Math.round(task.value * 100)}%</span>`}
      ${job && html`<span class="pill">Exporting ${job.stage} ${Math.round(job.value * 100)}%</span>`}
      <span class=${`pill ${connected ? 'live' : 'off'}`} title="Live link to the server (edits by Claude appear instantly)">${connected ? 'Live' : 'Offline'}</span>
    </div>
  </div>`;
}
