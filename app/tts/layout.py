"""Sentence timing inside a narration clip (drag / nudge / Match to video).

A steady-pace narration is assembled from one piece per sentence (pacing.assemble), so we know exactly where each
sentence sits in the generated file: tts.segs = [{text, a, b}] (seconds in tts.base). A layout moves sentences without
regenerating anything: tts.layout = [{at, speed}] (seconds from the start of the composed file; speed 0.88–1.12, >1 =
faster). compose() cuts each sentence out of the base file, time-stretches it and writes a new file with the sentences
at their new places — the clip then plays that file like any other narration, so preview, export, trim, split, voice
effects and MP3 download need no special handling.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from .pacing import SR, STRETCH, _stretch

MIN_GAP = 0.02          # sentences may touch but never overlap
TAIL = 0.12             # silence kept after the last sentence


def natural_layout(segs: list[dict]) -> list[dict]:
    return [{"at": round(float(s["a"]), 3), "speed": 1.0} for s in segs]


def seg_len(s: dict, speed: float = 1.0) -> float:
    return max(0.0, float(s["b"]) - float(s["a"])) / max(0.01, speed)


def clean(segs: list[dict], layout: list[dict] | None) -> list[dict]:
    """Valid layout for these sentences: speeds in range, in order, no overlaps (later ones pushed back), at >= 0
    is NOT enforced here — negative starts are handled by the caller (the clip start moves earlier)."""
    if not layout or len(layout) != len(segs):
        layout = natural_layout(segs)
    out, prev_end = [], None
    for s, l in zip(segs, layout):
        sp = float(min(STRETCH[1], max(STRETCH[0], float(l.get("speed") or 1.0))))
        at = float(l.get("at", s["a"]))
        if prev_end is not None and at < prev_end + MIN_GAP:
            at = prev_end + MIN_GAP
        out.append({"at": round(at, 3), "speed": round(sp, 3)})
        prev_end = at + seg_len(s, sp)
    return out


def is_natural(segs, layout) -> bool:
    return all(abs(l["at"] - s["a"]) < 1e-3 and abs(l["speed"] - 1) < 1e-3 for s, l in zip(segs, layout))


def end_of(segs, layout) -> float:
    return max((l["at"] + seg_len(s, l["speed"]) for s, l in zip(segs, layout)), default=0.0)


def _read(path: Path) -> np.ndarray:
    sr, x = wavfile.read(path)
    x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:                                             # generated narration is always 48 kHz; be safe anyway
        xi = np.linspace(0, len(x) - 1, int(len(x) * SR / sr))
        x = np.interp(xi, np.arange(len(x)), x).astype(np.float32)
    return x


def compose(base: Path, segs: list[dict], layout: list[dict], out_dir: Path) -> Path:
    """Write (or reuse) the narration with sentences moved: out_dir/lay_<hash>.wav. layout must be clean() and >= 0."""
    key = hashlib.sha1(json.dumps([base.name, segs, layout]).encode()).hexdigest()[:12]
    out = out_dir / f"lay_{key}.wav"
    if out.exists():
        return out
    x = _read(base)
    parts = []
    for s, l in zip(segs, layout):
        a, b = int(round(s["a"] * SR)), int(round(s["b"] * SR))
        y = x[a:b]
        if abs(l["speed"] - 1.0) > 1e-3 and len(y) > 64:
            y = _stretch(y, l["speed"])
        parts.append((int(round(l["at"] * SR)), y))
    n = max([p + len(y) for p, y in parts] + [0]) + int(TAIL * SR)
    z = np.zeros(n, np.float32)
    for p, y in parts:
        z[p:p + len(y)] += y
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    wavfile.write(tmp, SR, (np.clip(z, -1, 1) * 32767).astype(np.int16))
    tmp.replace(out)
    return out


def timeline_spans(clip: dict) -> list[dict]:
    """[{i, text, t0, t1}] where each sentence of a narration clip plays on the timeline (only the visible part)."""
    tt = clip.get("tts") or {}
    segs = tt.get("segs") or []
    if not segs:
        return []
    layout = tt.get("layout") or natural_layout(segs)
    base = clip["start"] - (clip.get("in") or 0.0)
    end = clip["start"] + clip["dur"]
    out = []
    for i, (s, l) in enumerate(zip(segs, layout)):
        t0 = base + l["at"]
        t1 = t0 + seg_len(s, l["speed"])
        if t1 > clip["start"] and t0 < end:
            out.append({"i": i, "text": s["text"], "t0": round(t0, 3), "t1": round(t1, 3)})
    return out
