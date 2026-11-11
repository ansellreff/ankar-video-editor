// Tool ribbon (CapCut / Premiere style): one tab per feature area. A tab switches the tool panel next to the monitor;
// Export opens the export window. Feature buttons live inside their tab, not loose in the title bar.
import { html } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';
import { A } from './actions.js';
import { Icon } from './util.js';

export const TOOL_TABS = [
  ['assistant', 'AI Editor', 'sparkle', 'Edit this video by chatting with Claude (script → style → plan → build); nothing changes before you approve'],
  ['captions', 'Captions', 'cc', 'Auto captions, caption styles, check unclear words'],
  ['text', 'Text', 'type', 'Titles, lower thirds, typed intro'],
  ['transitions', 'Transitions', 'trans', 'Transitions between clips'],
  ['filters', 'Effects', 'wand', 'Looks and effects'],
  ['luts', 'Color', 'palette', 'Look presets and LUTs (color grading)'],
  ['layouts', 'Layouts', 'grid', 'Split screen and picture-in-picture'],
  ['motion', 'Motion', 'move', 'Animation presets (keyframes)'],
  ['voice', 'AI Voice', 'voice', 'Clone a voice from a video, AI narration'],
];
export const tabName = id => (TOOL_TABS.find(t => t[0] === id) || [])[1] || 'Effects';

export function Ribbon() {
  const tab = useStore(s => s.fxTab || 'captions');
  const job = useStore(s => s.exportJob);
  const review = useStore(s => (s.project?.clips || []).filter(c => c.meta?.review?.length && !c.meta.review_ok).length
    + (s.project?.markers || []).filter(m => m.kind === 'unclear').length);
  return html`<div class="ribbon">
    ${TOOL_TABS.map(([id, label, icon, tip]) => html`<button class=${`rtab ${tab === id ? 'on' : ''}`} title=${tip} onClick=${() => set({ fxTab: id })}>
      <${Icon} n=${icon} s=${18} /><span>${label}</span>${id === 'captions' && review > 0 ? html`<i class="rbadge" title=${`${review} caption spot(s) to check`}>${review}</i>` : ''}</button>`)}
    <span class="rsep" />
    <button class=${`rtab export ${S.dialog === 'export' ? 'on' : ''}`} title="Export the video (Ctrl+M)" onClick=${() => A.dialog('export')}>
      <${Icon} n="export" s=${18} /><span>${job ? `Exporting ${Math.round(job.value * 100)}%` : 'Export'}</span></button>
  </div>`;
}
