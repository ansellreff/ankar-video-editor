import { html, useState, useRef, useEffect, useMemo } from '../vendor/preact-htm.js';
import { S, set, useStore } from './store.js';
import { A } from './actions.js';
import { getWave } from './player.js';
import { Icon, dur, bytes } from './util.js';

const TABS = [['all', 'All'], ['video', 'Video'], ['audio', 'Audio'], ['image', 'Images'], ['subtitle', 'Subs'], ['gen', 'Generators']];

export const dragData = (e, data) => { e.dataTransfer.setData('application/x-vlog', JSON.stringify(data)); e.dataTransfer.effectAllowed = 'copy'; };

function Wave({ aid }) {
  const ref = useRef();
  useEffect(() => {
    const draw = w => {
      const c = ref.current; if (!c || !w) return;
      const ctx = c.getContext('2d'); const W = c.width = 240, H = c.height = 120;
      ctx.clearRect(0, 0, W, H); ctx.fillStyle = '#2bd1a6';
      const n = w.peaks.length;
      for (let x = 0; x < W; x++) {
        const i0 = Math.floor(x / W * n), i1 = Math.max(i0 + 1, Math.floor((x + 1) / W * n));
        let m = 0; for (let i = i0; i < i1; i++) m = Math.max(m, w.peaks[i]);
        const h = Math.max(1, m / 255 * H * 0.9); ctx.fillRect(x, (H - h) / 2, 1, h);
      }
    };
    draw(getWave(aid, draw));
  }, [aid]);
  return html`<canvas ref=${ref} />`;
}

function AssetCard({ a, used, selected }) {
  const [scrub, setScrub] = useState(null);
  const st = a.derived?.strip;
  const isVid = a.kind === 'video', ready = a.status === 'ready';
  const poster = (isVid || a.kind === 'image') && a.derived?.poster ? `/files/cache/media/${a.id}/poster.jpg?v=${a.mtime}` : null;
  const portrait = a.meta?.h > a.meta?.w;
  const onMove = e => {
    if (!st) return;
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.min(st.count - 1, Math.floor((e.clientX - r.left) / r.width * st.count));
    setScrub({ i, w: r.width, h: r.height });
  };
  const scrubStyle = s => {
    const fh = s.h, fw = st.tw * fh / st.th;                  // keep the frame's aspect ratio, centered
    return `background-image:url(/files/cache/media/${a.id}/strip.jpg?v=${a.mtime});background-size:${st.count * fw}px ${fh}px;` +
      `background-position:${(s.w - fw) / 2 - s.i * fw}px 0`;
  };
  const icon = { audio: 'music', subtitle: 'cc', font: 'type', image: 'image', video: 'film' }[a.kind];
  return html`<div class=${`asset ${selected ? 'selected' : ''}`} draggable="true" title=${a.path}
      onDragStart=${e => dragData(e, { kind: 'asset', id: a.id })}
      onClick=${() => set({ sel: { clips: [], transition: null, asset: a.id } })}
      onDblClick=${() => A.addAsset(a.id)}
      onContextMenu=${e => { e.preventDefault(); set({ sel: { clips: [], transition: null, asset: a.id }, ctx: { x: e.clientX, y: e.clientY, items: [
        { label: 'Add to timeline at playhead', run: () => A.addAsset(a.id) },
        ...((a.kind === 'video' || a.kind === 'audio') && a.meta?.has_audio ? [
          { label: 'Clone a voice from this video…', run: () => A.voiceWizard(a.id) },
          { label: 'Use as voice sample (pick a time range)…', run: () => A.voiceSampleDialog(null, null, a.id) }] : []),
        { label: 'Open its folder', run: () => A.open(a.scope === 'library' ? 'library' : a.kind === 'video' ? 'video' : a.kind === 'audio' ? 'audio' : a.kind === 'image' ? 'photos' : 'assets') },
      ] } }); }}>
    <div class=${`thumb ${portrait ? 'portrait' : ''}`} style=${poster ? `background-image:url(${poster})` : ''}
         onMouseMove=${onMove} onMouseLeave=${() => setScrub(null)}>
      ${scrub != null && st && html`<div class="scrub" style=${scrubStyle(scrub)} />`}
      ${a.kind === 'audio' && ready && html`<${Wave} aid=${a.id} />`}
      ${!poster && !(a.kind === 'audio' && ready) && html`<span style="color:var(--muted)"><${Icon} n=${icon} s=${26} w=${1.5} /></span>`}
      ${a.meta?.dur ? html`<span class="badge dur">${dur(a.meta.dur)}</span>` : ''}
      ${a.status === 'error' ? html`<span class="badge err" title=${a.error}>error</span>` : used ? html`<span class="badge used">in use</span>` : ''}
      ${(a.status === 'processing' || a.status === 'queued') && html`<div class="progress-ring"><i style=${`width:${Math.round((a.progress || 0.03) * 100)}%`} /></div>`}
    </div>
    <div class="meta">
      <div class="name">${a.name}</div>
      <div class="sub">${a.status === 'processing' ? `preparing ${Math.round((a.progress || 0) * 100)}%` : a.status === 'queued' ? 'queued' :
        a.meta?.w ? `${a.meta.w}×${a.meta.h}` : bytes(a.size)}${a.meta?.fps ? html`<span>${a.meta.fps.toFixed(2)} fps</span>` : ''}</div>
    </div>
  </div>`;
}

function Generators() {
  return html`<div class="asset-grid" style="padding-top:10px">
    <div class="asset" draggable="true" onDragStart=${e => dragData(e, { kind: 'generator', id: 'typed_intro' })} onDblClick=${() => A.dialog('intro')}>
      <div class="thumb" style="background:#000">
        <div style="text-align:center;font-family:Poppins;color:#fff;line-height:1.2"><div style="font-size:10px">Friday, October 30th</div><div style="font-weight:700;font-size:14px">05:00 PM</div></div>
      </div>
      <div class="meta"><div class="name">Typed Intro</div><div class="sub">type-on text + keyboard</div></div>
    </div>
  </div>
  <div class="fx-hint">Drag onto the timeline, or double-click to set the text and keyboard sound.</div>`;
}

export function ProjectPanel() {
  const assets = useStore(s => s.assets);
  const project = useStore(s => s.project);
  const selAsset = useStore(s => s.sel.asset);
  const [tab, setTab] = useState('all');
  const [q, setQ] = useState('');
  const [collapsed, setCollapsed] = useState({});
  const projName = useStore(s => s.projectName);
  const used = useMemo(() => new Set(project?.clips.map(c => c.asset).filter(Boolean)), [project]);
  const visible = Object.values(assets).filter(a => a.kind !== 'font');
  const list = visible
    .filter(a => tab === 'all' || a.kind === tab)
    .filter(a => !q || a.path.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => a.path.localeCompare(b.path));
  const mine = list.filter(a => a.scope !== 'library'), shared = list.filter(a => a.scope === 'library');
  const grouped = items => {
    const g = {};
    for (const a of items) (g[a.folder || '(root)'] ||= []).push(a);
    const order = ['video', 'photos', 'brand/logo', 'brand/watermark', 'audio/music', 'audio/voiceover', 'audio/sfx', 'subtitles',
      'library/samples', 'library/ambience', 'library/sfx', 'library/generated'];
    const rank = f => { const i = order.findIndex(p => f.startsWith(p)); return i < 0 ? 99 : i; };
    return Object.entries(g).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  };
  const isClosed = f => collapsed[f] ?? (f.startsWith('library/') && !q);
  const counts = k => visible.filter(a => a.scope !== 'library' && (k === 'all' || a.kind === k)).length;   // this project's own media
  const busy = Object.values(assets).filter(a => a.status === 'processing' || a.status === 'queued').length;
  const folders = items => grouped(items).map(([folder, its]) => html`
    <div class="folder-head" style="cursor:pointer" onClick=${() => setCollapsed({ ...collapsed, [folder]: !isClosed(folder) })}>
      <span style=${`display:inline-flex;transition:transform .15s;transform:rotate(${isClosed(folder) ? -90 : 0}deg)`}><${Icon} n="chev" s=${12} /></span>
      <${Icon} n="folder" s=${13} /><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${folder.replace(/^library\//, '')}</span><span style="margin-left:auto">${its.length}</span></div>
    ${!isClosed(folder) && html`<div class="asset-grid">${its.map(a => html`<${AssetCard} key=${a.id} a=${a} used=${used.has(a.id)} selected=${selAsset === a.id} />`)}</div>`}`);
  return html`<div class="panel">
    <div class="panel-head">
      <span class="panel-title">Project</span><span class="spacer" />
      <button class="btn ghost icon" title="Open this project's folder in Explorer" onClick=${() => A.open('project')}><${Icon} n="folder" /></button>
      <button class="btn ghost icon" title="Rescan folders" onClick=${A.rescan}><${Icon} n="refresh" /></button>
    </div>
    <div class="tabs">${TABS.map(([k, l]) => html`<button class=${`tab ${tab === k ? 'active' : ''}`} onClick=${() => setTab(k)}>${l}${k !== 'gen' ? html`<span class="count">${counts(k)}</span>` : ''}</button>`)}</div>
    ${tab !== 'gen' && html`<div style="padding:8px 10px 0"><label class="search"><${Icon} n="search" s=${14} /><input class="input" placeholder="Search assets" value=${q} onInput=${e => setQ(e.target.value)} /></label></div>`}
    <div class="panel-body">
      ${tab === 'gen' ? html`<${Generators} />` : html`
        ${mine.length === 0 && !q ? html`<div class="empty where">
            <div style="margin-bottom:6px"><b>“${projName}” has no media yet</b></div>
            <div>Drop files into this project's <b>import</b> folder — they're sorted automatically:</div>
            <table class="where-t">
              <tr><td>Footage</td><td>assets/video <span>(a subfolder per day)</span></td></tr>
              <tr><td>Photos</td><td>assets/photos</td></tr>
              <tr><td>Logo · watermark</td><td>assets/brand/logo · brand/watermark</td></tr>
              <tr><td>Background music</td><td>assets/audio/music</td></tr>
              <tr><td>Sound effects</td><td>assets/audio/sfx</td></tr>
              <tr><td>Voice recordings</td><td>assets/audio/voiceover</td></tr>
              <tr><td>Script · storyboard</td><td>docs/script · docs/storyboard</td></tr>
            </table>
            <div class="hint">Name a file or subfolder with “logo”, “watermark”, “music”, “sfx”, “voice”, “script”… and it lands in the right place.</div>
            <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;justify-content:center">
              <button class="btn small primary" onClick=${() => A.open('import')}><${Icon} n="folder" s=${13} /> Open import folder</button>
              <button class="btn small" onClick=${() => A.open('project')}>Project folder</button></div>
          </div>` : folders(mine)}
        ${shared.length > 0 && html`<div class="lib-head">Shared library <span>(all projects)</span></div>${folders(shared)}`}
        ${list.length === 0 && q ? html`<div class="empty">Nothing matches “${q}”.</div>` : ''}`}
    </div>
    <div class="panel-foot">${busy ? html`<span style="color:var(--accent)">Preparing ${busy} file${busy > 1 ? 's' : ''}…</span>` : html`<span>Watching this project's import/ and assets/</span>`}</div>
  </div>`;
}
