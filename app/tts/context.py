"""What's happening in the video around a narration: shot changes and where people talk (timeline seconds).

- cuts: starts/ends of clips on enabled video tracks + scene changes inside a clip (one scan per asset of its preview
  proxy, cached in cache/media/<id>/scenes.json).
- speech: for clips with sound on the dialogue side (audio tracks that aren't Narration / music / SFX):
  the words of the auto captions when the clip has them (most accurate), else an energy VAD of the asset's audio
  (subtitles.utterances, cached in cache/media/<id>/speech.json). Intervals are mapped through the clip's in / speed.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import av
import numpy as np

from ..paths import MEDIA_CACHE, ROOT
from ..render.timeline import clip_dur

VERSION = 1
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
NOT_DIALOGUE = re.compile(r"music|bgm|song|sfx|effect|ambien|narrat|voice ?over", re.I)


def _lock(aid):
    with _guard:
        return _locks.setdefault(aid, threading.Lock())


def _cached(aid: str, name: str, mtime, build):
    f = MEDIA_CACHE / aid / name
    with _lock(aid):
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if d.get("v") == VERSION and d.get("mtime") == mtime:
                    return d["data"]
            except (OSError, ValueError, KeyError):
                pass
        data = build()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"v": VERSION, "mtime": mtime, "data": data}), encoding="utf-8")
        return data


# ---------------------------------------------------------------- per-asset analysis
def audio16(path: str, start_offset=0.0) -> np.ndarray:
    """Whole audio of a file as 16 kHz mono float32 (streamed, so long videos stay small in memory)."""
    out = []
    with av.open(path) as c:
        if not c.streams.audio:
            return np.zeros(0, np.float32)
        s = c.streams.audio[0]
        rs = av.AudioResampler(format="flt", layout="mono", rate=16000)
        first = None
        for fr in c.decode(s):
            if first is None and fr.time is not None:
                first = float(fr.time) - start_offset
                if first > 0:
                    out.append(np.zeros(int(first * 16000), np.float32))
            for r in rs.resample(fr):
                out.append(r.to_ndarray().reshape(-1))
        for r in rs.resample(None):
            out.append(r.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)


def speech_of(asset: dict) -> list[list[float]]:
    """[[s0, s1]] seconds of the source where someone (probably) talks."""
    def build():
        from ..subtitles import utterances
        x = audio16(str(ROOT / asset["path"]), (asset.get("meta") or {}).get("start", 0.0))
        if len(x) < 1600:
            return []
        return [[round(a / 16000, 3), round(b / 16000, 3)] for a, b in utterances(x, 16000, max_len=1e9)]
    return _cached(asset["id"], "speech.json", asset.get("mtime"), build)


def detect_cuts(path: str, fps=5.0, min_gap=0.8) -> list[float]:
    """Seconds where the picture changes shot (hard cuts) in a video file. Also used by the AI Editor's reference
    analysis (higher fps, shorter min_gap for fast edits)."""
    cuts, prev, prev_t, t_first, diffs = [], None, -1e9, None, []
    with av.open(str(path)) as c:
        if not c.streams.video:
            return []
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        for fr in c.decode(s):
            if fr.time is None:
                continue
            t = float(fr.time)
            t_first = t if t_first is None else t_first
            if t - prev_t < 1.0 / fps - 1e-3:
                continue
            prev_t = t
            img = fr.to_ndarray(width=48, height=27, format="rgb24").astype(np.float32) / 255.0
            hist = np.histogramdd(img.reshape(-1, 3), bins=(6, 6, 6), range=((0, 1),) * 3)[0].ravel()
            hist /= max(1.0, hist.sum())
            if prev is not None:
                hd = float(np.abs(hist - prev[1]).sum())          # 0..2
                pd = float(np.abs(img - prev[0]).mean())          # 0..1
                diffs.append((t - t_first, hd, pd))
            prev = (img, hist)
    if len(diffs) < 3:
        return []
    med = float(np.median([d[1] for d in diffs])) + 1e-3
    for i, (t, hd, pd) in enumerate(diffs):                       # strong change, much bigger than usual motion
        if hd > 0.55 and pd > 0.12 and hd > 4 * med:
            if not cuts or t - cuts[-1] > min_gap:
                cuts.append(round(t, 3))
    return cuts


def scenes_of(asset: dict, fps=5.0) -> list[float]:
    """Source seconds where the picture changes shot (hard cuts inside one file), from the preview proxy."""
    def build():
        src = MEDIA_CACHE / asset["id"] / "proxy.mp4"
        if not src.exists():
            src = ROOT / asset["path"]
        return detect_cuts(str(src), fps)
    return _cached(asset["id"], "scenes.json", asset.get("mtime"), build)


# ---------------------------------------------------------------- timeline mapping
def _to_timeline(c: dict, src: float) -> float:
    sp = c.get("speed", 1.0) or 1.0
    if c.get("reverse"):
        return c["start"] + (c["out"] - src) / sp
    return c["start"] + (src - c.get("in", 0.0)) / sp


def _merge(iv, gap=0.25):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def dialogue_tracks(project: dict) -> set[str]:
    out = set()
    for t in project["tracks"]:
        if t["kind"] != "audio" or t.get("mute"):
            continue
        if t.get("role") == "dialogue" or (t.get("role") is None and not t.get("duck") and not NOT_DIALOGUE.search(t.get("name") or "")):
            out.add(t["id"])
    return out


def context(project: dict, get_asset, t0: float, t1: float, scenes=True) -> dict:
    """{cuts: [t], speech: [[a, b]], sources: [{clip, how}]} for timeline range [t0, t1]."""
    tracks = {t["id"]: t for t in project["tracks"]}
    cuts = set()
    for c in project["clips"]:
        tr = tracks.get(c["track"])
        if not tr or tr["kind"] != "video" or c.get("enabled") is False or tr.get("hidden") or c["type"] not in ("media", "generator"):
            continue
        s, e = c["start"], c["start"] + clip_dur(c)
        if e < t0 or s > t1:
            continue
        cuts.update((round(s, 3), round(e, 3)))
        a = get_asset(c.get("asset")) if c.get("asset") else None
        if scenes and a and a.get("kind") == "video" and c.get("hold") is None and not c.get("still"):
            lo, hi = sorted((c.get("in", 0.0), c.get("out", 0.0)))
            for src in scenes_of(a):
                if lo + 0.2 < src < hi - 0.2:
                    cuts.add(round(_to_timeline(c, src), 3))
    subs = [k for k in project["clips"] if k["type"] == "text" and (k.get("meta") or {}).get("subtitle")
            and (k.get("text") or {}).get("caption")]
    speech, sources = [], []
    for c in project["clips"]:
        if c["track"] not in dialogue_tracks(project) or c["type"] != "media" or c.get("enabled") is False:
            continue
        if (c.get("volume_db") or 0) < -30:
            continue
        s, e = c["start"], c["start"] + clip_dur(c)
        if e < t0 or s > t1:
            continue
        words = [[k["start"] + w["t0"], k["start"] + w["t1"]] for k in subs if k["start"] < e and k["start"] + k["dur"] > s
                 for w in k["text"]["caption"].get("words", []) if w.get("w")]
        if words:
            iv, how = words, "captions"
        else:
            a = get_asset(c.get("asset"))
            if not a or not (a.get("meta") or {}).get("has_audio"):
                continue
            lo, hi = sorted((c.get("in", 0.0), c.get("out", 0.0)))
            iv = []
            for a0, a1 in speech_of(a):
                if a1 <= lo or a0 >= hi:
                    continue
                x0, x1 = sorted((_to_timeline(c, max(a0, lo)), _to_timeline(c, min(a1, hi))))
                iv.append([x0, x1])
            how = "sound"
        speech += [[max(a, s), min(b, e)] for a, b in iv if b > s and a < e]
        sources.append({"clip": c["id"], "how": how})
    speech = [[round(a, 3), round(b, 3)] for a, b in _merge(speech) if b > t0 and a < t1]
    return {"cuts": sorted(t for t in cuts if t0 - 1e-6 <= t <= t1 + 1e-6), "speech": speech, "sources": sources}
