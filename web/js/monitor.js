import { html, useRef, useEffect, useState } from '../vendor/preact-htm.js';
import { S, set, useStore, fps } from './store.js';
import { player } from './player.js';
import { A } from './actions.js';
import { projectDuration } from './evaluate.js';
import { Gizmo, selectAt } from './gizmo.js';
import { Icon, tc } from './util.js';

const ZOOMS = [['fit', 'Fit'], [0.25, '25%'], [0.5, '50%'], [1, '100%']];

export function Monitor() {
  const stage = useRef(), canvas = useRef(), svg = useRef();
  const [box, setBox] = useState({ w: 0, h: 0 });
  const t = useStore(s => s.t);
  const playing = useStore(s => s.playing);
  const project = useStore(s => s.project);
  const safe = useStore(s => s.safe);
  const loop = useStore(s => s.loop);
  const vol = useStore(s => s.volume);
  const zoom = useStore(s => s.monZoom ?? 'fit');
  const recording = useStore(s => s.recording);
  const fmt = project?.format;

  useEffect(() => { player.attach(canvas.current).catch(e => console.error(e)); }, []);
  useEffect(() => {
    const ro = new ResizeObserver(() => { const r = stage.current.getBoundingClientRect(); setBox({ w: r.width, h: r.height }); });
    ro.observe(stage.current);
    return () => ro.disconnect();
  }, []);

  let cw = 0, ch = 0;
  if (fmt && box.w) {
    if (zoom === 'fit') {
      const pad = 18, k = Math.min((box.w - pad * 2) / fmt.w, (box.h - pad * 2) / fmt.h);
      cw = Math.max(2, Math.floor(fmt.w * k)); ch = Math.max(2, Math.floor(fmt.h * k));
    } else { cw = Math.round(fmt.w * zoom); ch = Math.round(fmt.h * zoom); }
  }
  useEffect(() => {
    const c = canvas.current; if (!c || !fmt || !cw) return;
    const dpr = window.devicePixelRatio || 1;
    const rw = Math.min(fmt.w, Math.round(cw * dpr)), rh = Math.round(rw * fmt.h / fmt.w);
    if (c.width !== rw || c.height !== rh) { c.width = rw; c.height = rh; player.invalidate(); }
  }, [cw, ch, fmt?.w, fmt?.h]);

  const total = project ? projectDuration(project) : 0;
  const onDrop = e => {
    e.preventDefault();
    const d = JSON.parse(e.dataTransfer.getData('application/x-vlog') || 'null');
    if (d?.kind === 'asset') A.addAsset(d.id, S.t);
    else if (d?.kind === 'text') A.addText(d.id, S.t);
    else if (d?.kind === 'filter') A.applyFilter(d.id);
    else if (d?.kind === 'lut') A.applyLut(d.id);
    else if (d?.kind === 'look') A.applyLook(d.id);
    else if (d?.kind === 'transition') A.applyTransition(d.id);
    else if (d?.kind === 'layout') A.layout(d.id);
    else if (d?.kind === 'generator') A.dialog('intro');
  };
  const onCanvasDown = e => {
    if (e.button !== 0 || !fmt) return;
    const r = svg.current.getBoundingClientRect();
    selectAt([(e.clientX - r.left) / r.width * fmt.w, (e.clientY - r.top) / r.height * fmt.h]);
  };
  const k = fmt ? cw / fmt.w : 1;
  const subY = fmt ? fmt.h * (1 - 330 / 1920) : 0;
  return html`<div class="panel monitor">
    <div class="panel-head">
      <span class="panel-title">Program</span>
      <span class="hint">${fmt ? `${fmt.preset} · ${fmt.w}×${fmt.h}` : ''}</span>
      <span class="spacer" />
      <div class="seg">${ZOOMS.map(([z, l]) => html`<button class=${zoom === z ? 'on' : ''} onClick=${() => set({ monZoom: z })}>${l}</button>`)}</div>
      <button class=${`btn ghost icon ${safe ? 'on' : ''}`} title="Safe areas & subtitle line" onClick=${A.toggleSafe}><${Icon} n="safe" /></button>
      <button class="btn ghost icon" title="Save this frame as PNG (exports/<project>/frames)" onClick=${A.snapshot}><${Icon} n="image" /></button>
      <button class=${`btn ghost icon ${recording ? 'on' : ''}`} title="Record voiceover from the microphone" onClick=${A.recordVoiceover}><${Icon} n="mic" /></button>
    </div>
    <div class=${`stage ${zoom === 'fit' ? '' : 'zoomed'}`} ref=${stage} onDragOver=${e => e.preventDefault()} onDrop=${onDrop}>
      <div class="screen-wrap" style=${`width:${cw}px;height:${ch}px`}>
        <canvas class="screen" ref=${canvas} style=${`width:${cw}px;height:${ch}px`} />
        ${fmt && cw > 0 && html`<svg class="mon-overlay" ref=${svg} viewBox=${`0 0 ${fmt.w} ${fmt.h}`} preserveAspectRatio="none"
            style=${`width:${cw}px;height:${ch}px`} onPointerDown=${onCanvasDown} onDblClick=${() => player.toggle()}>
          ${safe && html`<g class="safe-lines">
            <rect x=${fmt.w * 0.05} y=${fmt.h * 0.05} width=${fmt.w * 0.9} height=${fmt.h * 0.9} />
            <rect x=${fmt.w * 0.1} y=${fmt.h * 0.1} width=${fmt.w * 0.8} height=${fmt.h * 0.8} style="opacity:.5" />
            <line x1="0" y1=${subY} x2=${fmt.w} y2=${subY} class="sub" />
          </g>`}
          <${Gizmo} k=${k} />
        </svg>`}
      </div>
      ${project && project.clips.length === 0 && html`<div class="drop-hint"><div><div style="font-size:15px;color:var(--text-2);margin-bottom:6px">Your timeline is empty</div>
        Drag clips from the Project panel onto the timeline below (or drop them here).</div></div>`}
      ${recording && html`<div class="rec-badge">${recording.count > 0 ? recording.count : html`<span class="dot" /> REC ${tc(recording.elapsed || 0, fps()).slice(3, 8)}`}</div>`}
    </div>
    <div class="transport">
      <span class="timecode">${tc(t, fps())}</span>
      <span class="grow" />
      <button class="btn ghost icon" title="Go to start (Home)" onClick=${A.goStart}><${Icon} n="start" /></button>
      <button class="btn ghost icon" title="Previous frame (←)" onClick=${() => A.step(-1)}><${Icon} n="prev" /></button>
      <button class="play-btn" title="Play / Pause (Space)" onClick=${() => player.toggle()}><${Icon} n=${playing ? 'pause' : 'play'} s=${16} /></button>
      <button class="btn ghost icon" title="Next frame (→)" onClick=${() => A.step(1)}><${Icon} n="next" /></button>
      <button class="btn ghost icon" title="Go to end (End)" onClick=${A.goEnd}><${Icon} n="end" /></button>
      <span class="grow" />
      <button class=${`btn ghost icon ${loop ? 'on' : ''}`} title="Loop between In and Out" onClick=${A.toggleLoop}><${Icon} n="loop" s=${15} /></button>
      <button class="btn ghost icon" title="Mute preview" onClick=${() => set({ volume: vol > 0 ? 0 : 1 })}><${Icon} n=${vol > 0 ? 'vol' : 'mute'} s=${15} /></button>
      <span class="timecode total">${tc(total, fps())}</span>
    </div>
  </div>`;
}
