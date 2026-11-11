// Server calls + live events (SSE). Every edit is an op executed by app/project.py on the server.
import { S, set, toast } from './store.js';
import { onClaudeProgress } from './claudeProgress.js';
import { onAssistantEvent } from './assistantPanel.js';

export const CLIENT = Math.random().toString(36).slice(2);

export async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
  return j;
}

function applyState(r) {
  set({ project: r.project, history: r.history, ...(r.project_name ? { projectName: r.project_name, projectPath: r.project_path } : {}) });
}

/** After opening/creating/renaming a project: replace everything project-specific. */
export function applySwitch(r) {
  set({ project: r.project, history: r.history, projectName: r.project_name, projectPath: r.project_path,
        exports: r.exports || [], projects: r.projects || [], checkpoints: r.checkpoints || [],
        ...(r.assets ? { assets: Object.fromEntries(r.assets.map(a => [a.id, a])), previews: {} } : {}),   // each project has its own assets
        sel: { clips: [], transition: null, asset: null }, t: 0, playing: false, inPt: null, outPt: null });
}
export async function projectAction(action, body = {}) {
  try {
    const r = await api(`/api/projects/${action}`, body);
    if (action === 'checkpoint') { set({ checkpoints: r.checkpoints }); return r; }
    if (action === 'revert') { applyState(r); set({ checkpoints: r.checkpoints }); return r; }
    applySwitch(r);
    return r;
  } catch (e) { toast(e.message, 'error'); throw e; }
}

export async function op(name, args = {}, label) {
  try {
    const r = await api('/api/op', { op: name, args, label, client: CLIENT });
    applyState(r);
    return r.result;
  } catch (e) { toast(e.message, 'error'); throw e; }
}

export async function batch(ops, label) {
  try {
    const r = await api('/api/op', { batch: ops, label, client: CLIENT });
    applyState(r);
    return r.result;
  } catch (e) { toast(e.message, 'error'); throw e; }
}

export async function undo() {
  const r = await api('/api/undo', { client: CLIENT }); applyState(r);
  if (r.label) toast(`Undo: ${r.label}`);
}
export async function redo() {
  const r = await api('/api/redo', { client: CLIENT }); applyState(r);
  if (r.label) toast(`Redo: ${r.label}`);
}

export async function loadState() {
  const r = await api('/api/state');
  const assets = Object.fromEntries(r.assets.map(a => [a.id, a]));
  set({ project: r.project, history: r.history, presets: r.presets, exports: r.exports, packs: r.packs, assets,
        exportJob: r.export_job.running ? r.export_job.progress : null, projectName: r.project_name, projectPath: r.project_path,
        projects: r.projects, checkpoints: r.checkpoints, voices: r.voices || [], ttsJobs: r.tts_jobs || {}, ttsStatus: r.tts, luts: r.luts || [], ambience: r.ambience || [] });
}

export function connectEvents() {
  const es = new EventSource('/api/events');
  es.onopen = () => set({ connected: true });
  es.onerror = () => set({ connected: false });
  es.onmessage = async ev => {
    const { type, data } = JSON.parse(ev.data);
    if (type === 'project') {
      if (data.client === CLIENT) return;                 // our own op: already applied from the response
      if (data.project_name && data.project_name !== S.projectName) return;   // another tab's project
      applyState(data);
    } else if (type === 'project_switched') {
      if (data.project_name !== S.projectName) applySwitch(data);
    } else if (type === 'task') {
      set({ task: data.value >= 1 ? null : data });
    } else if (type === 'presets') {
      set(s => ({ presets: { ...s.presets, ...data } }));
    } else if (type === 'tts') {
      set(s => ({ ttsJobs: { ...s.ttsJobs, [data.clip]: data } }));
      if (data.clip?.startsWith('quick_') && data.state === 'error') set(s => ({ quickTts: { ...(s.quickTts || {}), [data.clip]: { error: data.error } } }));
    } else if (type === 'voices') {
      set({ voices: data });
    } else if (type === 'reverse_ready') {
      set(s => ({ revProxies: { ...(s.revProxies || {}), [`${data.asset}_${data.in.toFixed(3)}_${data.out.toFixed(3)}`]: data.url } }));
    } else if (type === 'quick_tts') {
      set(s => ({ quickTts: { ...(s.quickTts || {}), [data.id]: data } }));
    } else if (type === 'tts_config') {
      set(s => ({ ttsStatus: { ...(s.ttsStatus || {}), config: data } }));
    } else if (type === 'tts_engine') {
      set(s => ({ ttsStatus: { ...(s.ttsStatus || {}), engine: data.engine } }));
    } else if (type === 'asset') {
      set(s => ({ assets: { ...s.assets, [data.id]: data } }));
    } else if (type === 'assets') {
      const r = await api('/api/state');
      set({ assets: Object.fromEntries(r.assets.map(a => [a.id, a])) });
    } else if (type === 'toast') {
      toast(data.text, data.kind || 'info', (data.detail || []).join?.('\n') || '');
    } else if (type === 'export') {
      set({ exportJob: data });
    } else if (type === 'claude_progress') {
      onClaudeProgress(data);
    } else if (type === 'assistant') {
      onAssistantEvent(data);
    } else if (type === 'keys') {                       // keys changed on the API Keys page: refresh "key set" states
      if (S.ai) api('/api/assistant/config').then(c => set(s => ({ ai: s.ai ? { ...s.ai, config: c } : s.ai }))).catch(() => {});
    } else if (type === 'changelog') {
      if (S.dialog === 'changelog' && (!S.changelog || S.changelog.project === data.project)) set({ changelog: data });
    } else if (type === 'export_done') {
      set({ exportJob: null, exports: data.exports, lastExport: data });
    }
  };
}

export const openFolder = target => api('/api/open', { target });
export const rescan = () => api('/api/rescan', {}).then(r => toast(`Rescanned: ${r.count} assets${r.moved.length ? `, sorted ${r.moved.length} from import/` : ''}`));
