// Voice effects (Filter · Noise · Space · Distance · Pan) as a WebAudio graph. MIRROR of app/render/voicefx.py:
// voice → filter chain (dry/wet) → distance (high-cut, presence dip, level) → dry + convolution reverb → stereo pan → + noise bed
import { S } from './store.js';

const VF = () => S.presets?.voice_fx || { filters: [], spaces: [], distance: {} };

export function biquad(t, f, q = 0.7071, g = 0, sr = 48000) {
  f = Math.min(f, sr * 0.45);
  const w0 = 2 * Math.PI * f / sr, cw = Math.cos(w0), sw = Math.sin(w0), A = 10 ** (g / 40);
  const alpha = (t === 'lowshelf' || t === 'highshelf') ? sw / 2 * Math.SQRT2 : sw / (2 * Math.max(q, 1e-4));
  let b, a;
  if (t === 'lp') { b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]; }
  else if (t === 'hp') { b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]; }
  else if (t === 'peak') { b = [1 + alpha * A, -2 * cw, 1 - alpha * A]; a = [1 + alpha / A, -2 * cw, 1 - alpha / A]; }
  else if (t === 'lowshelf') { const sa = 2 * Math.sqrt(A) * alpha;
    b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)];
    a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]; }
  else if (t === 'highshelf') { const sa = 2 * Math.sqrt(A) * alpha;
    b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)];
    a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]; }
  const a0 = a[0];
  return { b: b.map(v => v / a0), a: a.map(v => v / a0) };
}
export function driveCurve(k, n = 2049) { const c = new Float32Array(n); for (let i = 0; i < n; i++) { const x = -1 + 2 * i / (n - 1); c[i] = Math.tanh(k * x) / Math.tanh(k); } return c; }
export function crushCurve(bits, n = 2049) { const c = new Float32Array(n), s = 2 ** (bits - 1); for (let i = 0; i < n; i++) { const x = -1 + 2 * i / (n - 1); c[i] = Math.round(x * s) / s; } return c; }
export function distanceStages(d) {
  if (d <= 0.001) return [];
  return [{ t: 'lp', f: 18000 * (0.16 ** d), q: 0.7071 }, { t: 'peak', f: 3000, q: 1.0, g: -5 * d }, { t: 'gain', db: -8 * d }];
}
export const fxActive = fx => !!fx && !!(fx.filter || fx.noise || fx.space || (fx.distance || 0) > 0.001 || Math.abs(fx.pan || 0) > 0.001);

// ---- decoded IRs / beds, shared across clips
const buffers = new Map();
function buffer(actx, file, gain = 1, onReady) {
  const key = `${file}|${gain}`;
  const e = buffers.get(key);
  if (e?.buf) return e.buf;
  if (!e) {
    const ent = { buf: null, waiters: [] };
    buffers.set(key, ent);
    fetch('/files/' + file.split('/').map(encodeURIComponent).join('/')).then(r => r.arrayBuffer()).then(ab => actx.decodeAudioData(ab)).then(b => {
      if (gain !== 1) for (let c = 0; c < b.numberOfChannels; c++) { const d = b.getChannelData(c); for (let i = 0; i < d.length; i++) d[i] *= gain; }
      ent.buf = b; ent.waiters.forEach(f => f(b)); ent.waiters = [];
    }).catch(err => console.error('voice fx file', file, err));
  }
  if (onReady) buffers.get(key).waiters.push(onReady);
  return null;
}

function stagesNode(actx, stages, sr) {
  const input = actx.createGain();
  let last = input;
  for (const st of stages) {
    let n;
    if (['hp', 'lp', 'peak', 'lowshelf', 'highshelf'].includes(st.t)) {
      const { b, a } = biquad(st.t, st.f, st.q ?? 0.7071, st.g ?? 0, sr);
      n = new IIRFilterNode(actx, { feedforward: b, feedback: a });
    } else if (st.t === 'drive' || st.t === 'crush') {
      n = actx.createWaveShaper(); n.curve = st.t === 'drive' ? driveCurve(st.k) : crushCurve(st.bits | 0); n.oversample = 'none';
    } else if (st.t === 'gain') {
      n = actx.createGain(); n.gain.value = 10 ** (st.db / 20);
    } else if (st.t === 'ring') {                     // out = x·(1−m) + x·sin(2πft)·m
      const m = st.mix ?? 1, out = actx.createGain(), dry = actx.createGain(), ring = actx.createGain(), og = actx.createGain(), osc = actx.createOscillator();
      dry.gain.value = 1 - m; ring.gain.value = 0; og.gain.value = m; osc.frequency.value = st.f;
      osc.connect(og).connect(ring.gain); osc.start();
      last.connect(dry).connect(out); last.connect(ring).connect(out);
      last = out; continue;
    } else continue;
    last.connect(n); last = n;
  }
  return { input, output: last };
}

/** Build the effect graph for one clip. Returns {input, output, bed:{start(offset), stop()}|null, dispose()} */
export function buildChain(actx, fx, onBedReady) {
  const vf = VF(), sr = actx.sampleRate;
  const input = new GainNode(actx, { channelCount: 2, channelCountMode: 'explicit', channelInterpretation: 'speakers' });   // mono → stereo like the export
  let cur = input;
  const fl = vf.filters.find(f => f.id === fx.filter);
  if (fl) {
    const m = fx.filter_mix ?? 1, mid = actx.createGain(), dry = actx.createGain(), wet = actx.createGain(), ch = stagesNode(actx, fl.stages, sr);
    dry.gain.value = 1 - m; wet.gain.value = m;
    cur.connect(dry).connect(mid); cur.connect(ch.input); ch.output.connect(wet).connect(mid);
    cur = mid;
  }
  const dist = stagesNode(actx, distanceStages(fx.distance || 0), sr);
  cur.connect(dist.input); cur = dist.output;
  // space
  const spaces = Object.fromEntries(vf.spaces.map(s => [s.id, s]));
  const d = fx.distance || 0;
  let sp = null, send = 0;
  if (spaces[fx.space]) { sp = spaces[fx.space]; send = Math.min(1, (fx.space_mix ?? sp.mix ?? 0.35) + 0.4 * d); }
  else if (d > 0.001) { sp = spaces[vf.distance?.room_for_distance || 'living_room']; send = 0.35 * d; }
  if (sp && send > 0) {
    const mix = actx.createGain(), dry = actx.createGain(), wet = actx.createGain();
    const conv = new ConvolverNode(actx, { disableNormalization: true });
    dry.gain.value = 1 - 0.3 * Math.min(1, send); wet.gain.value = send;
    const b = buffer(actx, sp.file, sp.gain ?? 1, bb => { try { conv.buffer = bb; } catch (e) { /* already set */ } });
    if (b) conv.buffer = b;
    cur.connect(dry).connect(mix); cur.connect(conv).connect(wet).connect(mix);
    cur = mix;
  }
  const pan = new StereoPannerNode(actx, { pan: Math.max(-1, Math.min(1, fx.pan || 0)) });
  cur.connect(pan);
  const output = actx.createGain();
  pan.connect(output);
  // noise bed (looped; started/stopped by the player in sync with the clip time)
  let bed = null;
  const beds = Object.fromEntries((S.ambience || []).map(a => [a.id, a]));
  if (fx.noise && beds[fx.noise]) {
    const bg = actx.createGain(); bg.gain.value = 10 ** ((fx.noise_db ?? -24) / 20); bg.connect(output);
    let src = null, buf = buffer(actx, beds[fx.noise].file, 1, b => { buf = b; onBedReady?.(); });
    bed = {
      playing: false,
      start(offset) {
        if (!buf) return false;
        this.stop();
        src = new AudioBufferSourceNode(actx, { buffer: buf, loop: true });
        src.connect(bg); src.start(0, ((offset % buf.duration) + buf.duration) % buf.duration);
        this.playing = true; this.t0 = actx.currentTime; this.off = offset; return true;
      },
      position() { return this.off + (actx.currentTime - this.t0); },
      stop() { if (src) { try { src.stop(); } catch (e) { /* ignore */ } src.disconnect(); src = null; } this.playing = false; },
    };
  }
  return { input, output, bed, dispose() { bed?.stop(); try { input.disconnect(); output.disconnect(); } catch (e) { /* ignore */ } } };
}
