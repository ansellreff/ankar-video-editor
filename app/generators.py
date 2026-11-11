"""Generators: assets made by the app. Currently: Typed Intro (type-on text + real keystroke SFX), as in v3."""
from __future__ import annotations

import hashlib
import importlib.util
import json

import numpy as np
from scipy.io import wavfile

from .paths import GENERATED_SFX, ROOT, rel

_spec = importlib.util.spec_from_file_location("keys_real", ROOT / "scripts" / "keys_real.py")
keys_real = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keys_real)

# v3 approved layout (ASS sizes 112 / 150 → em px 80 / 107 with Poppins' 1.4 line box)
DEFAULT_LINES = [
    {"text": "Friday, October 30th 2026", "weight": 500, "size": 80, "y": 860 / 1920, "spacing": 1, "track": "T1"},
    {"text": "05:00 PM", "weight": 700, "size": 107, "y": 1040 / 1920, "spacing": 4, "track": "T2"},
]


def schedule(lines, seed=23, gap=0.095, jit=0.03, first=0.9, line_pause=0.75):
    """Letter times per line — same rhythm as scripts/keys.py variant 2 (the approved v3 intro)."""
    rng = np.random.default_rng(seed)
    t, out = first, []
    for li, ln in enumerate(lines):
        if li:
            t += line_pause
        times = []
        g = gap if li == 0 else gap * 1.3
        for ch in ln["text"]:
            times.append(round(t, 2))                         # centiseconds, like the .ass the v3 audio used
            extra = (0.07 if ch in " ," else 0) if li == 0 else (0.06 if ch == " " else 0)
            t += g + rng.uniform(-jit, jit) + extra
        out.append(times)
    return out


def typed_intro(lines=None, start=0.0, pack="slim", length=8.0, lufs=-28.5):
    """Returns {'wav': rel path, 'texts': [add_text args...], 'sfx_start': start, 'length': length}."""
    lines = lines or DEFAULT_LINES
    times = schedule(lines)
    last = max(ts[-1] for ts in times if ts)
    fade_start = min(max(6.4, last + 1.0), length - 1.1)
    fade_end = fade_start + 0.6
    letters = [(t, ch) for ln, ts in zip(lines, times) for t, ch in zip(ts, ln["text"])]
    key = hashlib.sha1(json.dumps([lines, pack, lufs, length]).encode()).hexdigest()[:8]
    wav = GENERATED_SFX / f"typed_intro_{pack}_{key}.wav"
    if not wav.exists():
        wavfile.write(wav, keys_real.SR, keys_real.make_track(letters, pack=pack, lufs=lufs, dur=length))
    texts = []
    for i, (ln, ts) in enumerate(zip(lines, times)):
        texts.append({
            "track": ln.get("track", f"T{i + 1}"), "start": start, "dur": fade_end, "content": ln["text"],
            "preset": "typewriter", "x": 0.5, "y": ln["y"], "times": ts,
            "style": {"font": "Poppins", "weight": ln["weight"], "size": ln["size"], "outline": 0, "spacing": ln.get("spacing", 0)},
            "anim": {"in": "typewriter", "in_dur": 0.0, "out": "fade", "out_dur": 0.6},
        })
    return {"wav": rel(wav), "texts": texts, "length": length, "packs": keys_real.PACK_INFO}
