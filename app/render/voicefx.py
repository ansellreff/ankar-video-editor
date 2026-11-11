"""Voice effects (Filter · Noise · Space · Distance · Pan) — export renderer. MIRROR of web/js/voicefx.js.

clip.voice_fx = {filter, filter_mix, noise, noise_db, space, space_mix, distance (0 near … 1 far), pan (−1 … 1)}
Signal flow (identical in the browser WebAudio graph):
  voice → filter chain (dry/wet by filter_mix) → distance (high-cut, presence dip, level) →
  dry + convolution reverb (space IR; "distance" alone adds a little room) → stereo pan → + looped noise bed
Biquads use the RBJ Audio-EQ-Cookbook formulas (same coefficients as the browser's IIRFilterNode); drive = tanh(k·x)/tanh(k);
crush = rounding to 2^(bits−1) steps; pan = the Web Audio StereoPannerNode equal-power law.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, lfilter

from ..paths import AMBIENCE, EFFECTS, ROOT, rel

SR = 48000
DEFAULT = {"filter": None, "filter_mix": 1.0, "noise": None, "noise_db": -24.0, "space": None, "space_mix": None,
           "distance": 0.0, "pan": 0.0}


@lru_cache(maxsize=1)
def presets() -> dict:
    return json.loads((EFFECTS / "presets.json").read_text(encoding="utf-8")).get("voice_fx", {})


def normalize(fx: dict | None) -> dict | None:
    if not fx:
        return None
    d = {**DEFAULT, **fx}
    f = lambda v, lo, hi, dv: float(min(hi, max(lo, dv if v is None else v)))  # noqa: E731
    d["filter_mix"] = f(d["filter_mix"], 0, 1, 1.0)
    d["noise_db"] = f(d["noise_db"], -60, 0, -24.0)
    d["distance"] = f(d["distance"], 0, 1, 0.0)
    d["pan"] = f(d["pan"], -1, 1, 0.0)
    if d["space_mix"] is not None:
        d["space_mix"] = f(d["space_mix"], 0, 1, 0.35)
    return d


def active(fx: dict | None) -> bool:
    return bool(fx) and bool(fx.get("filter") or fx.get("noise") or fx.get("space") or (fx.get("distance") or 0) > 0.001
                             or abs(fx.get("pan") or 0) > 0.001)


# ------------------------------------------------------------------ biquads (RBJ cookbook)
def biquad(t: str, f: float, q: float = 0.7071, g: float = 0.0, sr: int = SR):
    """→ (b[3], a[3]) normalised so a0 = 1."""
    f = min(f, sr * 0.45)
    w0 = 2 * math.pi * f / sr
    cw, sw = math.cos(w0), math.sin(w0)
    A = 10 ** (g / 40)
    if t in ("lowshelf", "highshelf"):
        alpha = sw / 2 * math.sqrt(2)                          # shelf slope S = 1
    else:
        alpha = sw / (2 * max(q, 1e-4))
    if t == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif t == "lowshelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa)]
        a = [(A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    elif t == "highshelf":
        sa = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa)]
        a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    else:
        raise ValueError(t)
    a0 = a[0]
    return [v / a0 for v in b], [v / a0 for v in a]


def drive_curve(k: float, n=2049) -> np.ndarray:
    x = np.linspace(-1, 1, n)
    return (np.tanh(k * x) / math.tanh(k)).astype(np.float32)


def crush_curve(bits: int, n=2049) -> np.ndarray:
    x = np.linspace(-1, 1, n)
    s = 2 ** (bits - 1)
    return (np.round(x * s) / s).astype(np.float32)


def shape(x: np.ndarray, curve: np.ndarray) -> np.ndarray:
    """WaveShaperNode semantics: curve sampled over [−1, 1], linear interpolation, clamped outside."""
    n = len(curve)
    pos = (np.clip(x, -1, 1) + 1) * 0.5 * (n - 1)
    return np.interp(pos, np.arange(n), curve).astype(np.float32)


def run_stages(x: np.ndarray, stages: list, t0: float) -> np.ndarray:
    y = x.astype(np.float64)
    for st in stages:
        t = st["t"]
        if t in ("hp", "lp", "peak", "lowshelf", "highshelf"):
            b, a = biquad(t, st["f"], st.get("q", 0.7071), st.get("g", 0.0))
            y = lfilter(b, a, y, axis=-1)
        elif t == "drive":
            y = shape(y, drive_curve(st["k"]))
        elif t == "crush":
            y = shape(y, crush_curve(int(st["bits"])))
        elif t == "ring":
            n = y.shape[-1]
            ph = 2 * math.pi * st["f"] * (t0 + np.arange(n) / SR)
            m = st.get("mix", 1.0)
            y = y * (1 - m) + y * np.sin(ph) * m
        elif t == "gain":
            y = y * 10 ** (st["db"] / 20)
    return y.astype(np.float32)


# ------------------------------------------------------------------ files
def _read_audio(path: Path) -> np.ndarray:
    """(2, n) float32 at 48 kHz from wav/mp3/m4a/ogg."""
    import av
    chunks = []
    with av.open(str(path)) as c:
        rs = av.AudioResampler(format="fltp", layout="stereo", rate=SR)
        for fr in c.decode(audio=0):
            chunks += [r.to_ndarray() for r in rs.resample(fr)]
        chunks += [r.to_ndarray() for r in rs.resample(None)]
    return np.concatenate(chunks, axis=1).astype(np.float32) if chunks else np.zeros((2, SR), np.float32)


@lru_cache(maxsize=24)
def _ir(file: str, gain: float) -> np.ndarray:
    return _read_audio(ROOT / file) * gain


@lru_cache(maxsize=24)
def _bed(file: str) -> np.ndarray:
    return _read_audio(ROOT / file)


def ambience_list() -> list[dict]:
    """Noise beds: generated ones (ambience.json) + any audio the user dropped into library/ambience/."""
    d = AMBIENCE
    meta = {}
    try:
        meta = json.loads((d / "ambience.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    out, seen = [], set()
    for k, v in meta.items():
        if (ROOT / v["file"]).exists():
            out.append({"id": k, "name": v["name"], "file": v["file"]})
            seen.add(Path(v["file"]).name)
    for f in sorted(d.glob("*")) if d.exists() else []:
        if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac") and f.name not in seen:
            out.append({"id": "file:" + f.name, "name": f.stem.replace("_", " "), "file": rel(f), "user": True})
    return out


def _space(fx):
    sp = {s["id"]: s for s in presets().get("spaces", [])}
    d = fx.get("distance") or 0.0
    if fx.get("space") in sp:
        s = sp[fx["space"]]
        mix = fx["space_mix"] if fx.get("space_mix") is not None else s.get("mix", 0.35)
        return s, min(1.0, mix + 0.4 * d)
    if d > 0.001:                                              # distance alone: a little room around the voice
        s = sp.get(presets().get("distance", {}).get("room_for_distance", "living_room"))
        return s, 0.35 * d
    return None, 0.0


def distance_stages(d: float) -> list:
    if d <= 0.001:
        return []
    return [{"t": "lp", "f": 18000 * (0.16 ** d), "q": 0.7071}, {"t": "peak", "f": 3000, "q": 1.0, "g": -5 * d},
            {"t": "gain", "db": -8 * d}]


def pan_stereo(y: np.ndarray, p: float) -> np.ndarray:
    """StereoPannerNode equal-power law for stereo input."""
    if abs(p) < 1e-6:
        return y
    L, R = y[0], y[1]
    if p <= 0:
        x = (p + 1) * math.pi / 2
        gl, gr = math.cos(x), math.sin(x)
        return np.stack([L + R * gl, R * gr]).astype(np.float32)
    x = p * math.pi / 2
    gl, gr = math.cos(x), math.sin(x)
    return np.stack([L * gl, R + L * gr]).astype(np.float32)


def process(x: np.ndarray, fx: dict | None, t_rel: float = 0.0) -> np.ndarray:
    """x: (2, n) clip audio starting `t_rel` seconds into the clip → processed (2, n)."""
    fx = normalize(fx)
    if not active(fx):
        return x
    n = x.shape[1]
    y = x.astype(np.float32)
    fl = {f["id"]: f for f in presets().get("filters", [])}.get(fx.get("filter"))
    if fl:
        wet = run_stages(y, fl["stages"], t_rel)
        m = fx["filter_mix"]
        y = (y * (1 - m) + wet * m).astype(np.float32)
    y = run_stages(y, distance_stages(fx["distance"]), t_rel)
    s, send = _space(fx)
    if s and send > 0:
        ir = _ir(s["file"], float(s.get("gain", 1.0)))
        wet = np.stack([fftconvolve(y[c], ir[c])[:n] for c in range(2)]).astype(np.float32)
        y = y * (1 - 0.3 * min(1.0, send)) + wet * send
    y = pan_stereo(y, fx["pan"])
    bed_id = fx.get("noise")
    if bed_id:
        beds = {b["id"]: b for b in ambience_list()}
        if bed_id in beds:
            bed = _bed(beds[bed_id]["file"])
            L = bed.shape[1]
            idx = (int(round(t_rel * SR)) + np.arange(n)) % L
            y = y + bed[:, idx] * 10 ** (fx["noise_db"] / 20)
    return y.astype(np.float32)
