"""Beat tracking for music (numpy/scipy only): tempo + beat times, so cuts can land on the beat.

Onset strength = half-wave-rectified spectral flux of a log-magnitude mel-ish spectrogram (hop 10 ms). Tempo = the
strongest autocorrelation peak of the onset envelope in 70–180 BPM (weighted toward ~120). Beats = dynamic programming
(Ellis 2007): maximise onset strength at beats while keeping beat spacing close to the tempo period. Downbeats (bar
starts, 4/4) = the phase of every 4th beat with the most onset energy.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly, stft

SR = 22050
HOP = 220                      # ≈ 10 ms


def onset_envelope(x: np.ndarray, sr: int) -> np.ndarray:
    if x.ndim > 1:
        x = x.mean(axis=0)
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g)
    _, _, Z = stft(x, fs=SR, nperseg=1024, noverlap=1024 - HOP, boundary="zeros", padded=False)   # frame i centred at i·HOP
    mag = np.abs(Z)
    nb = mag.shape[0]                                          # 40 log-spaced bands
    edges = np.unique(np.geomspace(2, nb - 1, 41).astype(int))
    bands = np.stack([mag[a:b].sum(axis=0) for a, b in zip(edges[:-1], edges[1:])])
    logm = np.log1p(100 * bands / (bands.max() + 1e-9))
    flux = np.maximum(0.0, np.diff(logm, axis=1)).sum(axis=0)
    flux = np.concatenate([[0.0], flux])
    flux -= np.convolve(flux, np.ones(31) / 31, mode="same")  # remove slow trend
    flux = np.maximum(flux, 0)
    return flux / (flux.std() + 1e-9)


def tempo(env: np.ndarray, fps: float, lo=70.0, hi=180.0) -> float:
    n = len(env)
    ac = np.fft.irfft(np.abs(np.fft.rfft(env, 2 * n)) ** 2)[:n]
    lags = np.arange(n)
    bpm = 60.0 * fps / np.maximum(lags, 1)
    ok = (bpm >= lo) & (bpm <= hi)
    w = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 120.0) / 0.9) ** 2)    # mild prior toward 120 BPM
    score = np.where(ok, ac * w, -np.inf)
    lag = int(np.argmax(score))
    # parabolic refinement
    if 1 <= lag < n - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        d = 0.5 * (a - c) / (a - 2 * b + c + 1e-12)
        lag = lag + float(np.clip(d, -0.5, 0.5))
    return 60.0 * fps / lag


def track(env: np.ndarray, fps: float, bpm: float, tightness=100.0) -> np.ndarray:
    period = 60.0 * fps / bpm
    n = len(env)
    score = env.astype(float).copy()
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period * 0.5)), int(round(period * 2.0))
    prange = np.arange(-hi, -lo + 1)
    penalty = -tightness * np.log(-prange / period) ** 2
    for i in range(hi, n):
        cand = score[i + prange] + penalty
        k = int(np.argmax(cand))
        score[i] = env[i] + cand[k]
        back[i] = i + prange[k]
    # start from the best score in the last period
    i = int(np.argmax(score[-int(period) - 1:])) + n - int(period) - 1
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    return np.array(beats[::-1])


def analyze(x: np.ndarray, sr: int) -> dict:
    env = onset_envelope(x, sr)
    fps = SR / HOP
    bpm = tempo(env, fps)
    b = track(env, fps, bpm)
    times = b / fps
    # downbeats: which of the 4 phases has the most onset energy
    strength = [env[b[p::4]].sum() for p in range(4)] if len(b) >= 8 else [0]
    phase = int(np.argmax(strength))
    return {"bpm": round(float(bpm), 2), "beats": [round(float(t), 3) for t in times],
            "downbeats": [round(float(t), 3) for t in times[phase::4]]}


def analyze_file(path: str) -> dict:
    from .render.audio import decode_range
    import av
    with av.open(path) as c:
        dur = float(c.duration / 1e6) if c.duration else None
    x = decode_range(path, 0.0, dur or 600.0, 0.0)               # 48 kHz stereo float
    return analyze(x, 48000)
