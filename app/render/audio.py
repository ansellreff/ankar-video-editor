"""Export audio mix (48 kHz stereo float). Preview in web/js/player.js follows the same rules.

- clip gain = clip.volume_db + track.volume_db; clip fade_in / fade_out are linear amplitude ramps
- mute / solo per track (any solo → only soloed tracks play)
- tracks with duck=True drop by settings.duck_db while a dialogue/narration track (role) has sound
- speed != 1: WSOLA time-stretch keeps pitch (keep_pitch, default) or resampling (pitch follows); reverse flips
- volume_db keyframes become a per-sample gain curve; freeze frames and stills are silent
- final mix normalized to settings.normalize_lufs (None = off), peaks kept under -1 dBFS
"""
from __future__ import annotations

import av
import numpy as np
import pyloudnorm as pyln

from .timeline import clip_dur

SR = 48000


def decode_range(path: str, t0: float, t1: float, start_offset: float = 0.0) -> np.ndarray:
    """(2, n) float32 audio from source seconds [t0, t1) (0 = container start)."""
    n_want = max(0, int(round((t1 - t0) * SR)))
    out = np.zeros((2, n_want), np.float32)
    if n_want == 0:
        return out
    with av.open(path) as c:
        if not c.streams.audio:
            return out
        s = c.streams.audio[0]
        rs = av.AudioResampler(format="fltp", layout="stereo", rate=SR)
        c.seek(int(max(0.0, t0 + start_offset - 1.0) / s.time_base), stream=s, backward=True)
        pos = None
        for frame in c.decode(s):
            ft = float(frame.time) - start_offset if frame.time is not None else None
            for r in rs.resample(frame):
                x = r.to_ndarray()
                if pos is None:
                    pos = int(round(((ft if ft is not None else t0) - t0) * SR))
                a, b = pos, pos + x.shape[1]
                pos = b
                lo, hi = max(a, 0), min(b, n_want)
                if hi > lo:
                    out[:, lo:hi] = x[:, lo - a:hi - a]
            if pos is not None and pos >= n_want:
                break
    return out


def stretch(x: np.ndarray, speed: float, m: int, keep_pitch: bool) -> np.ndarray:
    """Play (2, n) audio at `speed` and return exactly m samples. keep_pitch → WSOLA, else resample (pitch follows)."""
    if x.shape[1] < 2:
        return np.zeros((2, m), np.float32)
    if keep_pitch and abs(speed - 1.0) > 1e-3:
        from audiotsm import wsola
        from audiotsm.io.array import ArrayReader, ArrayWriter
        w = ArrayWriter(2)
        wsola(2, speed=speed).run(ArrayReader(np.ascontiguousarray(x, dtype=np.float32)), w)
        y = w.data.astype(np.float32)
    elif abs(speed - 1.0) > 1e-3:
        xi = np.linspace(0, x.shape[1] - 1, max(2, int(round(x.shape[1] / speed))))
        y = np.stack([np.interp(xi, np.arange(x.shape[1]), ch) for ch in x]).astype(np.float32)
    else:
        y = x
    return y[:, :m] if y.shape[1] >= m else np.pad(y, ((0, 0), (0, m - y.shape[1])))


def clip_audio(c: dict, a: dict | None, s0: float, s1: float, root=None) -> np.ndarray | None:
    """Rendered audio of clip c for timeline range [s0, s1) — before gain/fades."""
    m = int(round((s1 - s0) * SR))
    if c["type"] == "tts":
        f = (c.get("tts") or {}).get("file")
        if not f or root is None:
            return None
        off = c.get("in", 0.0) or 0.0
        x = decode_range(str(root / f), off + s0 - c["start"], off + s1 - c["start"])
        return x[:, :m] if x.shape[1] >= m else np.pad(x, ((0, 0), (0, m - x.shape[1])))
    if not a or not a.get("has_audio") or c.get("hold") is not None or c.get("still"):
        return None
    sp = c.get("speed", 1.0)
    r0, r1 = (s0 - c["start"]) * sp, (s1 - c["start"]) * sp
    if c.get("reverse"):
        x = decode_range(a["abs"], c["out"] - r1, c["out"] - r0, a.get("start", 0.0))[:, ::-1]
    else:
        x = decode_range(a["abs"], c["in"] + r0, c["in"] + r1, a.get("start", 0.0))
    return stretch(x, sp, m, c.get("keep_pitch", True))


CEILING = 0.89                     # −1 dBFS


def limit(x: np.ndarray, ceiling=CEILING, lookahead=0.005, release=0.08, block=48) -> np.ndarray:
    """Look-ahead peak limiter (stereo-linked). Gain per 1 ms block = ceiling / peak (≤ 1), held over the look-ahead
    window so it is already down when a peak arrives, released smoothly (≈ 80 ms), interpolated to samples."""
    n = x.shape[-1]
    nb = (n + block - 1) // block
    pad = nb * block - n
    env = np.abs(np.pad(x, ((0, 0), (0, pad)))).max(axis=0).reshape(nb, block).max(axis=1)
    g = np.minimum(1.0, ceiling / np.maximum(env, 1e-9))
    la = max(1, int(round(lookahead * SR / block)))
    gmin = g.copy()                                   # min over [i, i + la]: the gain comes down before the peak
    for k in range(1, la + 1):
        gmin[:-k] = np.minimum(gmin[:-k], g[k:])
    rel = 1 - np.exp(-block / (release * SR))
    out_g = np.empty_like(gmin)
    cur = 1.0
    for i, v in enumerate(gmin):                      # instant attack, smooth release
        cur = v if v < cur else cur + (v - cur) * rel
        out_g[i] = cur
    centers = np.arange(nb) * block + block / 2
    gs = np.interp(np.arange(n), centers, out_g).astype(np.float32)
    y = x * gs
    return np.clip(y, -ceiling, ceiling)              # tiny interpolation overshoots only


def mix(project: dict, assets_abs: dict, t0: float, t1: float, progress=None) -> tuple[np.ndarray, dict]:
    from ..paths import ROOT
    from .timeline import prop
    n = int(round((t1 - t0) * SR))
    tracks = {t["id"]: t for t in project["tracks"] if t["kind"] == "audio"}
    solo = any(t.get("solo") for t in tracks.values())
    buses = {tid: np.zeros((2, n), np.float32) for tid in tracks}
    clips = [c for c in project["clips"] if c["track"] in tracks and c.get("enabled", True) and c["type"] in ("media", "tts")]
    for i, c in enumerate(clips):
        tr = tracks[c["track"]]
        if tr.get("mute") or (solo and not tr.get("solo")):
            continue
        d = clip_dur(c)
        s0, s1 = max(c["start"], t0), min(c["start"] + d, t1)
        if s1 <= s0:
            continue
        x = clip_audio(c, assets_abs.get(c.get("asset")), s0, s1, ROOT)
        if x is None:
            continue
        if c.get("voice_fx"):                                            # Filter · Noise · Space · Distance · Pan
            from .voicefx import process
            x = process(x, c["voice_fx"], s0 - c["start"])
        m = x.shape[1]
        tt = s0 + np.arange(m) / SR
        if (c.get("keys") or {}).get("volume_db"):                      # volume keyframes, evaluated every 10 ms
            grid = np.arange(s0, s1 + 0.01, 0.01)
            vdb = np.array([prop(c, "volume_db", t) for t in grid])
            g = (10 ** ((np.interp(tt, grid, vdb) + tr.get("volume_db", 0)) / 20)).astype(np.float32)
        else:
            g = np.full(m, 10 ** ((c.get("volume_db", 0) + tr.get("volume_db", 0)) / 20), np.float32)
        if c.get("fade_in", 0) > 0:
            g *= np.clip((tt - c["start"]) / c["fade_in"], 0, 1)
        if c.get("fade_out", 0) > 0:
            g *= np.clip((c["start"] + d - tt) / c["fade_out"], 0, 1)
        k = int(round((s0 - t0) * SR))
        buses[c["track"]][:, k:k + m] += x * g
        if progress:
            progress((i + 1) / max(1, len(clips)))

    # ---- auto-duck tracks flagged duck=True under speech (dialogue + narration tracks)
    duck_db = project.get("settings", {}).get("duck_db", -12.0)
    speech = [buses[tid] for tid, t in tracks.items() if t.get("role") in ("dialogue", "narration")]
    dlg = sum(speech) if speech else None
    if dlg is not None and any(t.get("duck") for t in tracks.values()):
        hop = SR // 100
        env = np.abs(dlg).max(axis=0)
        frames = env[: len(env) // hop * hop].reshape(-1, hop).max(axis=1) if len(env) >= hop else np.zeros(1)
        speaking = (frames > 10 ** (-40 / 20)).astype(np.float32)
        target = np.where(speaking > 0, 10 ** (duck_db / 20), 1.0)
        sm = np.empty_like(target)
        cur = 1.0
        att, rel = 1 - np.exp(-1 / (0.15 * 100)), 1 - np.exp(-1 / (0.45 * 100))
        for i, v in enumerate(target):
            cur += (v - cur) * (att if v < cur else rel)
            sm[i] = cur
        gain = np.repeat(sm, hop)
        gain = np.pad(gain, (0, max(0, n - len(gain))), constant_values=gain[-1] if len(gain) else 1.0)[:n]
        for tid, t in tracks.items():
            if t.get("duck"):
                buses[tid] *= gain

    out = sum(buses.values()) if buses else np.zeros((2, n), np.float32)
    report = {"lufs": None, "peak_db": None}
    target = project.get("settings", {}).get("normalize_lufs", -14.0)
    meter = pyln.Meter(SR)
    if n > SR * 0.5 and np.abs(out).max() > 1e-5:
        loud = meter.integrated_loudness(out.T.astype(np.float64))
        if target is not None and np.isfinite(loud):
            # reach the target loudness and keep peaks under −1 dBFS with a look-ahead limiter (only the loud moments
            # are turned down) instead of scaling the whole mix down for one peak (which left exports ~3 dB quiet)
            for _ in range(2):
                out = out * 10 ** ((target - loud) / 20)
                out = limit(out, CEILING)
                loud = meter.integrated_loudness(out.T.astype(np.float64))
                if not np.isfinite(loud) or abs(loud - target) < 0.3:
                    break
        pk = np.abs(out).max()
        if pk > CEILING:
            out = out * (CEILING / pk)
        report["lufs"] = round(float(meter.integrated_loudness(out.T.astype(np.float64))), 1)
        report["peak_db"] = round(float(20 * np.log10(np.abs(out).max() + 1e-12)), 1)
    return out.astype(np.float32), report
