"""ElevenLabs Text to Dialogue (Eleven v4 / v3): a whole conversation performed in one go, so the two voices react to
each other with natural rhythm — far less "robotic" than sentence-by-sentence TTS with stretched, evenly spaced pieces.

POST /v1/text-to-dialogue/with-timestamps → audio + voice_segments (per input line) + character alignment, which gives
every line's exact span (to cut it into its own clip) and word times (for captions). Names are respelled for the voice
(app/tts/pronounce) while the returned words are mapped back to the real spelling.
The API key comes from config/secrets.json via app.config (never logged or written anywhere else).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from pathlib import Path

import av
import numpy as np
from scipy.io import wavfile

from . import elevenlabs as el
from . import pronounce
from ..paths import WORK

SR = 48000
CACHE = WORK / "dialogue"
TAG = re.compile(r"\[[^\]]*\]")


MOODS = {"cheerful": "cheerful", "excited": "excited", "curious": "curious", "calm": "calm", "warm": "warm",
         "serious": "serious", "dramatic": "dramatic", "neutral": None}


def tag(text: str, tone: str | None, emotion: float) -> str:
    """Delivery cue scaled by the Emotion amount (0–1): 0 = none, low = "[slightly cheerful]", mid = "[cheerful]",
    high = "[very cheerful]". Emotion 0.2 ≈ the user's pick: conversation take B with ~20% of take C's emotion."""
    mood = MOODS.get(tone or "neutral")
    text = TAG.sub("", text).strip()               # user text never carries its own tags into the scaled version
    if not mood or emotion < 0.1:
        return text
    adv = "slightly " if emotion < 0.35 else "" if emotion < 0.7 else "very "
    return f"[{adv}{mood}] {text}"


def stability_for(emotion: float) -> float:
    """Less emotion → a bit steadier (0.55 at 0 … 0.35 at 1)."""
    return round(0.55 - 0.2 * max(0.0, min(1.0, emotion)), 2)


def _decode(data: bytes) -> np.ndarray:
    out = []
    with av.open(io.BytesIO(data)) as c:
        rs = av.AudioResampler(format="fltp", layout="mono", rate=SR)
        for fr in c.decode(audio=0):
            out += [r.to_ndarray()[0] for r in rs.resample(fr)]
        out += [r.to_ndarray()[0] for r in rs.resample(None)]
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, np.float32)


def generate(key: str, turns: list[dict], model="eleven_v4", stability=0.5, seed=None, fmt="mp3_44100_192",
             respell=True, previous_text=None) -> dict:
    """turns: [{voice_id, text (may contain [audio tags]), display (real spelling, no tags)}].
    Returns {audio (float32 mono 48 kHz), sr, lines:[{i, start, end, words:[{w,t0,t1}]}], cached}. Cached on disk."""
    sent = [{"voice_id": t["voice_id"], "text": pronounce.apply(t["text"]) if respell else t["text"]} for t in turns]
    body = {"inputs": sent, "model_id": model, "settings": {"stability": stability}}
    if seed is not None:
        body["seed"] = int(seed)
    if previous_text:
        body["previous_text"] = previous_text[-100:]
    h = hashlib.sha1(json.dumps([body, fmt, "dlg1"], sort_keys=True).encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    f_json, f_wav = CACHE / f"{h}.json", CACHE / f"{h}.wav"
    if f_json.exists() and f_wav.exists():
        r = json.loads(f_json.read_text(encoding="utf-8"))
        sr, x = wavfile.read(f_wav)
        return {**r, "audio": x.astype(np.float32) / 32768.0, "sr": sr, "cached": True, "key": h}
    try:
        raw = el._req("POST", f"/text-to-dialogue/with-timestamps?output_format={fmt}", key, body, timeout=300)
    except el.ElevenLabsError as e:
        if fmt != "mp3_44100_128" and ("format" in str(e).lower() or e.status in (400, 403)):
            return generate(key, turns, model, stability, seed, "mp3_44100_128", respell, previous_text)
        raise
    r = json.loads(raw)
    audio = _decode(base64.b64decode(r["audio_base64"]))
    al = r.get("alignment") or r.get("normalized_alignment") or {}
    chars = al.get("characters") or []
    cs, ce = al.get("character_start_times_seconds") or [], al.get("character_end_times_seconds") or []
    lines = []
    for seg in r.get("voice_segments", []):
        i = seg["dialogue_input_index"]
        a, b = seg["character_start_index"], seg["character_end_index"]
        words = _words(chars[a:b], cs[a:b], ce[a:b])
        disp = (turns[i].get("display") or TAG.sub("", turns[i]["text"])).split()
        if len(disp) == len(words):
            words = [{**w, "w": d} for w, d in zip(words, disp)]
        else:                                     # different token count → spread display words over the span
            if words:
                t0, t1 = words[0]["t0"], words[-1]["t1"]
                tot = sum(len(d) + 1 for d in disp) or 1
                acc, nw = 0, []
                for d in disp:
                    w0 = t0 + (t1 - t0) * acc / tot
                    acc += len(d) + 1
                    nw.append({"w": d, "t0": round(w0, 3), "t1": round(t0 + (t1 - t0) * acc / tot, 3)})
                words = nw
        lines.append({"i": i, "start": round(seg["start_time_seconds"], 3), "end": round(seg["end_time_seconds"], 3), "words": words})
    # one entry per input (segments of the same input are merged)
    merged = {}
    for ln in lines:
        m = merged.setdefault(ln["i"], {"i": ln["i"], "start": ln["start"], "end": ln["end"], "words": []})
        m["start"], m["end"] = min(m["start"], ln["start"]), max(m["end"], ln["end"])
        m["words"] += ln["words"]
    out = {"lines": [merged[k] for k in sorted(merged)], "model": model, "stability": stability}
    wavfile.write(f_wav, SR, (np.clip(audio, -1, 1) * 32767).astype(np.int16))
    f_json.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return {**out, "audio": audio, "sr": SR, "cached": False, "key": h}


def _words(chars, starts, ends):
    """Characters + times → words (skipping [audio tags])."""
    words, cur, t0, t1, depth = [], "", None, None, 0
    for ch, a, b in zip(chars, starts, ends):
        if ch == "[":
            depth += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            continue
        if depth:
            continue
        if ch.isspace():
            if cur:
                words.append({"w": cur, "t0": round(t0, 3), "t1": round(t1, 3)})
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = a
        cur += ch
        t1 = b
    if cur:
        words.append({"w": cur, "t0": round(t0, 3), "t1": round(t1, 3)})
    return words


def cut(audio: np.ndarray, sr: int, start: float, end: float, pad=(0.06, 0.18)) -> np.ndarray:
    """One line out of the dialogue audio, with a little air and short fades (no clicks)."""
    a = max(0, int((start - pad[0]) * sr))
    b = min(len(audio), int((end + pad[1]) * sr))
    y = audio[a:b].copy()
    n = min(len(y) // 4, int(0.012 * sr))
    if n > 0:
        y[:n] *= np.linspace(0, 1, n)
        y[-n:] *= np.linspace(1, 0, n)
    return y
