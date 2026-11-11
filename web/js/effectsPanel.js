import { html, useState, useEffect } from '../vendor/preact-htm.js';
import { S, set, useStore, toast } from './store.js';
import { A } from './actions.js';
import { api } from './api.js';
import { dragData } from './projectPanel.js';
import { Icon } from './util.js';
import { CaptionsPanel } from './captionsPanel.js';
import { tabName } from './ribbon.js';
import { VoicePanel } from './voicePanel.js';
import { AssistantPanel } from './assistantPanel.js';

const CA = '#3e63c9', CB = '#f5a524';
const TPREV = {
  cross_dissolve: `linear-gradient(90deg, ${CA}, ${CB})`,
  dip_black: `linear-gradient(90deg, ${CA}, #000 50%, ${CB})`,
  dip_white: `linear-gradient(90deg, ${CA}, #fff 50%, ${CB})`,
  blur_dissolve: `linear-gradient(90deg, ${CA} 10%, #8a86a0 50%, ${CB} 90%)`,
  flash: `radial-gradient(circle, #fff 0 18%, transparent 55%), linear-gradient(90deg, ${CA} 50%, ${CB} 50%)`,
  wipe_right: `linear-gradient(90deg, ${CB} 50%, ${CA} 50%)`,
  wipe_left: `linear-gradient(90deg, ${CA} 50%, ${CB} 50%)`,
  wipe_down: `linear-gradient(180deg, ${CB} 50%, ${CA} 50%)`,
  wipe_up: `linear-gradient(180deg, ${CA} 50%, ${CB} 50%)`,
  inward_wipe: `linear-gradient(90deg, ${CB} 25%, ${CA} 25% 75%, ${CB} 75%)`,
  barn_door: `linear-gradient(90deg, ${CA} 25%, ${CB} 25% 75%, ${CA} 75%)`,
  clock_wipe: `conic-gradient(${CB} 0 40%, ${CA} 40%)`,
  circle_iris: `radial-gradient(circle, ${CB} 0 34%, ${CA} 35%)`,
  push_left: `linear-gradient(90deg, ${CA} 40%, #111 40% 42%, ${CB} 42%)`,
  push_up: `linear-gradient(180deg, ${CA} 40%, #111 40% 42%, ${CB} 42%)`,
  whip_pan: `linear-gradient(90deg, ${CA}, ${CA} 20%, #9b8c7a 50%, ${CB} 80%)`,
  zoom_in: `radial-gradient(circle, ${CB} 0 20%, ${CA} 60%)`,
  glitch: `repeating-linear-gradient(180deg, ${CA} 0 5px, ${CB} 5px 8px, #e0457b 8px 10px)`,
  zoom_out: `radial-gradient(circle, ${CA} 0 22%, ${CB} 60%)`,
  spin: `conic-gradient(from 45deg, ${CA}, ${CB}, ${CA})`,
  squeeze: `linear-gradient(90deg, ${CA} 30%, ${CB} 30%)`,
  cube_rotate: `linear-gradient(100deg, ${CA} 0 45%, #111 45% 46%, ${CB} 46%)`,
  shake_cut: `linear-gradient(80deg, ${CA} 48%, ${CB} 52%)`,
  cross_warp: `linear-gradient(90deg, ${CA}, ${CA} 25%, ${CB} 75%)`,
  light_leak_flash: `radial-gradient(circle at 40% 55%, #fff4dc 0 12%, #ff9a3c 30%, transparent 60%), linear-gradient(90deg, ${CA} 50%, ${CB} 50%)`,
  diamond_wipe: `conic-gradient(from 45deg at 50% 50%, ${CB} 0 25%, ${CB} 25% 50%, ${CB} 50% 75%, ${CB} 75%) center / 40% 40% no-repeat, ${CA}`,
  grid_wipe: `repeating-conic-gradient(${CA} 0 25%, ${CB} 0 50%) 0 0 / 12px 12px`,
  split_doors: `linear-gradient(90deg, ${CA} 25%, ${CB} 25% 75%, ${CA} 75%)`,
  swirl: `conic-gradient(${CA}, ${CB}, ${CA}, ${CB}, ${CA})`,
  ripple: `repeating-radial-gradient(circle, ${CA} 0 4px, ${CB} 4px 8px)`,
  pixelize: `repeating-conic-gradient(${CA} 0 25%, #6c78a8 0 50%) 0 0 / 8px 8px`,
  film_burn: `radial-gradient(circle at 60% 45%, ${CB} 0 18%, #ffd27a 22%, #ff5a1a 30%, ${CA} 40%)`,
  rgb_split: `linear-gradient(90deg, #e33 0 33%, #3c3 33% 66%, #36f 66%)`,
};
const FX_ICON = { gaussian_blur: 'layers', sharpen: 'zap', vignette: 'safe', film_grain: 'sparkle', chromatic: 'sliders', pixelate: 'image',
  glow: 'sparkle', light_leak: 'sparkle', letterbox: 'film', vhs: 'film', old_film: 'film', duotone: 'palette', posterize: 'layers',
  halftone: 'grid', color_pop: 'palette', sketch: 'type', fisheye: 'safe', kaleidoscope: 'grid', tilt_shift: 'fit', camera_shake: 'move', zoom_pulse: 'zap' };

const LA = '#3e63c9', LB = '#f5a524';
const LAYOUTS = [
  ['split_lr', 'Split left | right', `linear-gradient(90deg, ${LA} 49%, #0f1013 49% 51%, ${LB} 51%)`],
  ['split_tb', 'Split top / bottom', `linear-gradient(180deg, ${LA} 48%, #0f1013 48% 52%, ${LB} 52%)`],
  ['left', 'Left half', `linear-gradient(90deg, ${LA} 50%, #0f1013 50%)`],
  ['right', 'Right half', `linear-gradient(90deg, #0f1013 50%, ${LB} 50%)`],
  ['top', 'Top half', `linear-gradient(180deg, ${LA} 50%, #0f1013 50%)`],
  ['full', 'Full frame (reset)', LA],
  ['pip_tl', 'PiP top-left', `linear-gradient(${LB},${LB}) 8% 12% / 38% 38% no-repeat, ${LA}`],
  ['pip_tr', 'PiP top-right', `linear-gradient(${LB},${LB}) 92% 12% / 38% 38% no-repeat, ${LA}`],
  ['pip_bl', 'PiP bottom-left', `linear-gradient(${LB},${LB}) 8% 88% / 38% 38% no-repeat, ${LA}`],
  ['pip_br', 'PiP bottom-right', `linear-gradient(${LB},${LB}) 92% 88% / 38% 38% no-repeat, ${LA}`],
];
const ANIMS = [
  ['ken_burns_in', 'Ken Burns zoom in', 'fit'], ['ken_burns_out', 'Ken Burns zoom out', 'fit'],
  ['zoom_punch', 'Zoom punch', 'zap'], ['slide_in_left', 'Slide in from left', 'next'], ['slide_in_right', 'Slide in from right', 'prev'],
  ['pop_in', 'Pop in', 'sparkle'], ['fade_in_out', 'Fade in & out', 'layers'], ['clear', 'Remove all keyframes', 'x'],
];

function Tile({ kind, id, name, bg, icon, img, sprite, onApply, onContext, title }) {
  const style = img ? `background-image:url("${img}")` : bg ? `background:${bg}` : 'background:#0f1013;display:grid;place-items:center;color:var(--accent)';
  return html`<div class="fx" draggable="true" title=${title || `${name} — click to apply to the selection, or drag onto a clip`}
      onDragStart=${e => dragData(e, { kind, id })} onClick=${onApply} onContextMenu=${onContext}>
    <div class=${`prev ${img ? (sprite ? 'img sprite' : 'img') : ''}`} style=${style}>${!img && icon ? html`<${Icon} n=${icon} s=${18} />` : ''}</div>
    <div class="lbl">${name}</div>
  </div>`;
}

/** Real thumbnails (server renders the actual shaders on a frame of your footage), fetched once per kind. */
const PV_KINDS = { filters: ['filters'], luts: ['looks', 'luts'], transitions: ['transitions'] };
function usePreviews(tab) {
  const pv = useStore(s => s.previews || {});
  useEffect(() => {
    for (const k of PV_KINDS[tab] || []) {
      if (S.previews?.[k] || S.previewsLoading?.[k]) continue;
      set(s => ({ previewsLoading: { ...(s.previewsLoading || {}), [k]: true } }));
      api('/api/previews', { kind: k }).then(r => set(s => ({ previews: { ...(s.previews || {}), [k]: r.items } })))
        .catch(() => {}).finally(() => set(s => ({ previewsLoading: { ...(s.previewsLoading || {}), [k]: false } })));
    }
  }, [tab]);
  return pv;
}

export function EffectsPanel() {
  const presets = useStore(s => s.presets);
  const luts = useStore(s => s.luts || []);
  const [q, setQ] = useState('');
  const tab = useStore(s => s.fxTab || 'captions');     // chosen in the ribbon (ribbon.js)
  useEffect(() => {                                    // other parts of the app can open a tab (e.g. "Check unclear spots")
    const f = e => set({ fxTab: e.detail });
    window.addEventListener('vs-tab', f);
    return () => window.removeEventListener('vs-tab', f);
  }, []);
  const pv = usePreviews(tab);
  if (!presets) return null;
  const match = n => !q || n.toLowerCase().includes(q.toLowerCase());
  const looksAll = (presets.looks || []).filter(l => match(l.name));
  const lookMenu = (e, l) => { if (!l.user) return; e.preventDefault();
    set({ ctx: { x: e.clientX, y: e.clientY, items: [{ label: `Delete “${l.name}”`, run: () => api('/api/looks/delete_preset', { id: l.id })
      .then(r => { set(s => ({ presets: { ...s.presets, looks: r.looks } })); toast('Look deleted'); }) }] } }); };
  const cats = {};
  presets.transitions.filter(t => match(t.name)).forEach(t => (cats[t.category] ||= []).push(t));
  const looks = presets.filters.filter(f => f.category === 'Looks' && match(f.name));
  const fx = presets.filters.filter(f => f.category === 'Effects' && match(f.name));
  const fxGroups = {};
  fx.forEach(f => (fxGroups[f.group || 'Basics'] ||= []).push(f));
  const packs = presets.transition_packs || [];
  const texts = presets.text_presets.filter(p => match(p.name));
  return html`<div class="panel">
    <div class="panel-head"><span class="panel-title">${tabName(tab)}</span></div>
    ${!['captions', 'voice', 'assistant'].includes(tab) && html`<div style="padding:8px 10px 2px"><label class="search"><${Icon} n="search" s=${14} /><input class="input" placeholder=${`Search ${tabName(tab).toLowerCase()}`} value=${q} onInput=${e => setQ(e.target.value)} /></label></div>`}
    <div class="panel-body">
      ${tab === 'captions' && html`<${CaptionsPanel} />`}
      ${tab === 'voice' && html`<${VoicePanel} />`}
      ${tab === 'assistant' && html`<${AssistantPanel} />`}
      ${tab === 'transitions' && html`
        ${!q && html`<div class="fx-group">Transition packs <span style="text-transform:none;font-weight:400;letter-spacing:0">· one click for every cut</span></div>
          <div class="packs">${packs.map(p => html`<div class="pack">
            <div class="pack-sw">${p.items.slice(0, 4).map(id => html`<i style=${`background:${TPREV[id] || CA}`} />`)}</div>
            <div class="pack-txt"><b>${p.name}</b><span>${p.desc} · ${p.items.length} transitions</span></div>
            <button class="btn small" title=${`Put ${p.name} transitions on every cut (selected clips, or the whole V1 track)`} onClick=${() => A.transitionPack(p.id)}>Apply</button>
          </div>`)}</div>`}
        ${Object.entries(cats).map(([cat, list]) => html`<div class="fx-group">${cat}</div>
          <div class="fx-list">${list.map(t => html`<${Tile} kind="transition" id=${t.id} name=${t.name} bg=${TPREV[t.id]} img=${pv.transitions?.[t.id]} sprite=${true}
            title=${`${t.name} — hover to preview, click to add at the cut nearest the playhead (or drag onto a clip edge)`} onApply=${() => A.applyTransition(t.id)} />`)}</div>`)}
        <div class="fx-hint">Drop on a clip's start or end. With nothing selected, a click uses the cut nearest the playhead.</div>`}
      ${tab === 'filters' && html`
        <div class="fx-group">Color filters</div>
        <div class="fx-list">${looks.map(f => html`<${Tile} kind="filter" id=${f.id} name=${f.name} img=${pv.filters?.[f.id]}
            bg=${`linear-gradient(135deg, ${f.swatch?.[0] || '#888'}, ${f.swatch?.[1] || '#222'})`} onApply=${() => A.applyFilter(f.id)} />`)}</div>
        ${Object.entries(fxGroups).map(([grp, list]) => html`<div class="fx-group">${grp === 'Basics' ? 'Effects' : grp}</div>
          <div class="fx-list">${list.map(f => html`<${Tile} kind="filter" id=${f.id} name=${f.name} icon=${FX_ICON[f.id] || 'wand'} img=${pv.filters?.[f.id]} onApply=${() => A.applyFilter(f.id)} />`)}</div>`)}
        <div class="fx-hint">Filters stack on the selected clip. Tune them in the Inspector; color correction is there too.</div>`}
      ${tab === 'luts' && html`
        <div class="fx-group">Look presets <span style="text-transform:none;font-weight:400;letter-spacing:0">· full grade in one click</span></div>
        <div class="fx-list">${looksAll.filter(l => !l.user).map(l => html`<${Tile} kind="look" id=${l.id} name=${l.name} img=${pv.looks?.[l.id]} icon="palette"
            title=${`${l.name}: ${l.desc} — click: selected clips (nothing selected = every clip on V1). Replaces their color & filters.`} onApply=${() => A.applyLook(l.id)} />`)}</div>
        ${looksAll.some(l => l.user) && html`<div class="fx-group">★ My looks</div>
          <div class="fx-list">${looksAll.filter(l => l.user).map(l => html`<${Tile} kind="look" id=${l.id} name=${l.name} icon="palette"
            title=${`${l.name} — click to apply, right-click to delete`} onApply=${() => A.applyLook(l.id)} onContext=${e => lookMenu(e, l)} />`)}</div>`}
        <div class="fx-group" style="display:flex;align-items:center">Color LUTs
          <span style="flex:1" />
          <button class="btn ghost icon small" title="Reload the LUT folder" onClick=${A.refreshLuts}><${Icon} n="refresh" s=${13} /></button>
          <button class="btn ghost icon small" title="Open library/luts (shared by all projects) — drop your own .cube files here" onClick=${() => A.open('luts')}><${Icon} n="folder" s=${13} /></button></div>
        <div class="fx-list">${luts.filter(l => !l.error && match(l.name)).map(l => html`<${Tile} kind="lut" id=${l.file} name=${l.name} img=${pv.luts?.[l.file]}
            bg=${`linear-gradient(90deg, ${l.swatch.slice(0, 3).join(', ')}, ${l.swatch[4]})`} onApply=${() => A.applyLut(l.file)} />`)}</div>
        ${luts.some(l => l.error) && html`<div class="fx-hint" style="color:var(--danger)">Couldn't read: ${luts.filter(l => l.error).map(l => l.name).join(', ')}</div>`}
        <div class="fx-hint">A LUT is a complete color grade. Click to apply to the selected clip (a clip has one LUT; clicking another swaps it), then set its Amount in the Inspector. Your own .cube files: put them in library/luts and press ⟳.</div>`}
      ${tab === 'layouts' && html`
        <div class="fx-group">Split screen</div>
        <div class="fx-list">${LAYOUTS.slice(0, 6).filter(l => match(l[1])).map(([id, name, bg]) => html`<${Tile} kind="layout" id=${id} name=${name} bg=${bg} onApply=${() => A.layout(id)} />`)}</div>
        <div class="fx-group">Picture in picture</div>
        <div class="fx-list">${LAYOUTS.slice(6).filter(l => match(l[1])).map(([id, name, bg]) => html`<${Tile} kind="layout" id=${id} name=${name} bg=${bg} onApply=${() => A.layout(id)} />`)}</div>
        <div class="fx-hint">Split: select two overlapping clips (V1 + V2) and click — the lower track goes left/top. PiP shrinks the top clip into a corner. Fine-tune by dragging in the monitor.</div>`}
      ${tab === 'motion' && html`
        <div class="fx-group">Animation presets</div>
        <div class="fx-list">${ANIMS.filter(a => match(a[1])).map(([id, name, icon]) => html`<${Tile} kind="anim" id=${id} name=${name} icon=${icon} onApply=${() => A.animPreset(id)} />`)}</div>
        <div class="fx-hint">Adds keyframes to the selected clip (edit them in the Inspector with the ◆ buttons).</div>`}
      ${tab === 'text' && html`
        <div class="fx-group">Text presets</div>
        <div class="fx-list">${texts.map(p => html`<${Tile} kind="text" id=${p.id} name=${p.name} icon="type" onApply=${() => A.addText(p.id)} />`)}</div>
        <div class="fx-group">Generators</div>
        <div class="fx-list"><${Tile} kind="generator" id="typed_intro" name="Typed Intro" icon="keyboard" onApply=${() => A.dialog('intro')} /></div>
        <div class="fx-hint">Click adds at the playhead on T1. Subtitles: double-click a .srt/.ass file in the Project panel, or Clip ▸ Transcribe.</div>`}
    </div>
  </div>`;
}
