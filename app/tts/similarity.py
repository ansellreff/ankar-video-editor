"""Voice match: how much a generated line sounds like the cloned person (0–100%).

Uses the same speaker-verification encoder as speaker detection (Chatterbox VoiceEncoder via the worker `embed` command):
mean fingerprint over 1.6 s speech windows, cosine similarity. Same person typically scores ≈75–90%, a different
person ≈30–60%. Used after every generation and by scripts/voice_match_test.py to pick the best settings.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from ..paths import WORK


def load_mono16(path: str | Path) -> np.ndarray:
    """Any audio file (wav/mp3/m4a/opus…) → mono float32 16 kHz."""
    p = Path(path)
    if p.suffix.lower() == ".wav":
        sr, x = wavfile.read(p)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        if x.ndim > 1:
            x = x.mean(axis=1)
    else:
        import av
        chunks = []
        with av.open(str(p)) as c:
            rs = av.AudioResampler(format="flt", layout="mono", rate=16000)
            for fr in c.decode(audio=0):
                chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(fr)]
            chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(None)]
        return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(16000, np.float32)
    if sr != 16000:
        from math import gcd
        g = gcd(16000, sr)
        x = resample_poly(x, 16000 // g, sr // g).astype(np.float32)
    return x


def windows(x16: np.ndarray, max_n=48, win=1.6, hop=0.8):
    from ..subtitles import utterances
    from .speakers import _windows
    ws = _windows(utterances(x16, max_len=12.0), win=win, hop=hop) if len(x16) > 16000 else [(0.0, len(x16) / 16000)]
    if len(ws) > max_n:                                          # spread evenly over the file
        idx = np.linspace(0, len(ws) - 1, max_n).round().astype(int)
        ws = [ws[i] for i in idx]
    return ws or [(0.0, min(len(x16) / 16000, win))]


def fingerprint(embed_fn, audio: str | Path | np.ndarray, max_n=48) -> np.ndarray:
    """Unit-length mean voice fingerprint of the speech in a file (or 16 kHz array)."""
    x16 = audio if isinstance(audio, np.ndarray) else load_mono16(audio)
    tmp = WORK / f"fp_{uuid.uuid4().hex[:8]}.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(tmp, 16000, x16.astype(np.float32))
    try:
        e = np.array(embed_fn(str(tmp), windows(x16, max_n)), np.float32)
    finally:
        tmp.unlink(missing_ok=True)
    e /= np.linalg.norm(e, axis=1, keepdims=True) + 1e-9
    m = e.mean(axis=0)
    return m / (np.linalg.norm(m) + 1e-9)


def match(a: np.ndarray, b: np.ndarray) -> float:
    return round(float(np.clip(a @ b, 0, 1)) * 100, 1)


def voice_fingerprint(embed_fn, voice_dir: Path) -> np.ndarray | None:
    """Fingerprint of a voice's samples, cached in its folder (refreshed when the samples change)."""
    files = sorted(p for p in voice_dir.glob("*") if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac", ".ogg"))
    if not files:
        return None
    h = hashlib.sha1(json.dumps([[f.name, f.stat().st_size] for f in files]).encode()).hexdigest()[:12]
    cache = voice_dir / "fingerprint.json"
    try:
        d = json.loads(cache.read_text(encoding="utf-8"))
        if d.get("hash") == h:
            return np.array(d["fp"], np.float32)
    except Exception:
        pass
    x16 = np.concatenate([load_mono16(f) for f in files])
    fp = fingerprint(embed_fn, x16, max_n=64)
    cache.write_text(json.dumps({"hash": h, "fp": [round(float(v), 5) for v in fp]}), encoding="utf-8")
    return fp
