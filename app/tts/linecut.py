"""Cut one line out of a performed conversation at the quietest point and check it (Whisper + leak test).

Same rules as the Taiwan narration (scripts/having_fun/narration_fix.py, where these were first written): a line ends
at the QUIETEST moment between its last word and the next speaker's first word (never a fixed padding that can catch
the neighbour); the check flags extra sounds at the start / end and voices outside the line's word span — a flagged
line gets a new take, it is never cut tighter."""
from __future__ import annotations

import difflib
import re

import numpy as np
from scipy.signal import resample_poly


def rms_track(x, sr, win=0.02):
    w = max(1, int(win * sr))
    p = np.convolve(x.astype(np.float64) ** 2, np.ones(w) / w, mode="same")
    return np.sqrt(p + 1e-12)


def quietest(x, sr, lo, hi):
    lo, hi = max(0.0, lo), min(len(x) / sr, hi)
    if hi - lo < 0.02:
        return (lo + hi) / 2
    a, b = int(lo * sr), int(hi * sr)
    return lo + int(np.argmin(rms_track(x[a:b], sr))) / sr


def cut_line(audio, sr, s, e, prev_end=None, next_start=None):
    """s/e = first word start / last word end (s). Returns (clip, origin s)."""
    a = quietest(audio, sr, max(prev_end, s - 0.35), s - 0.01) if prev_end is not None and prev_end < s else max(0.0, s - 0.12)
    b = quietest(audio, sr, e + 0.01, min(next_start, e + 0.5)) if next_start is not None and next_start > e else min(len(audio) / sr, e + 0.3)
    y = audio[int(a * sr):int(b * sr)].copy()
    fi, fo = int(0.012 * sr), int(0.03 * sr)
    if len(y) > fi + fo:
        y[:fi] *= np.linspace(0, 1, fi)
        y[-fo:] *= np.linspace(1, 0, fo) ** 1.5
    return y, a


def _norm(s):
    return [t for t in re.sub(r"[^a-z0-9' ]", " ", s.lower()).split() if t]


def expected(text: str) -> str:
    """What Whisper writes: hyphenated names as one word (E-DA → EDA)."""
    return re.sub(r"\b([A-Z])-([A-Z]{1,3})\b", r"\1\2", text)


def check(model, y, sr, text, words=None):
    """→ (ok, transcript, problems)."""
    x16 = resample_poly(y, 1, 3).astype(np.float32) if sr == 48000 else y.astype(np.float32)
    if len(x16) < 16000:
        x16 = np.pad(x16, (0, 16000 - len(x16)))
    heard = " ".join(s.text.strip() for s in model.transcribe(x16, language="en", initial_prompt="", translate=False, no_context=True))
    exp, got = _norm(expected(text)), _norm(heard)
    probs = []
    ops = difflib.SequenceMatcher(a=exp, b=got, autojunk=False).get_opcodes()
    if ops and ops[-1][0] == "insert":
        probs.append(f"extra sound at the end: “{' '.join(got[ops[-1][3]:ops[-1][4]])}”")
    if ops and ops[0][0] == "insert":
        probs.append(f"extra sound at the start: “{' '.join(got[ops[0][3]:ops[0][4]])}”")
    sim = lambda a, b: difflib.SequenceMatcher(a=a, b=b).ratio()  # noqa: E731
    if exp and got and len(exp) > 1:
        if exp[0] not in got[:2] and sim(exp[0], got[0]) < 0.6:
            probs.append(f"start may be clipped: expected “{exp[0]}”, heard “{got[0]}”")
        if exp[-1] not in got[-2:] and sim(exp[-1], got[-1]) < 0.6:
            probs.append(f"end may be clipped: expected “{exp[-1]}”, heard “{got[-1]}”")
    if words:
        e = rms_track(y, sr)
        loud = np.percentile(e, 90) + 1e-9
        a = int(max(0.0, words[0]["t0"] - 0.15) * sr)
        b = int(min(len(y) / sr, words[-1]["t1"] + 0.15) * sr)
        pre = 20 * np.log10(e[:a].max() / loud) if a > int(0.02 * sr) else -99
        post = 20 * np.log10(e[b:].max() / loud) if len(y) - b > int(0.02 * sr) else -99
        if post > -24:
            probs.append(f"another voice after the last word ({post:.0f} dB)")
        if pre > -24:
            probs.append(f"another voice before the first word ({pre:.0f} dB)")
    return not probs, heard, probs
