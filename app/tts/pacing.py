"""Steady pacing for AI narration.

Voice models speak a whole paragraph with their own, fairly random rhythm: they rush long sentences, hesitate in odd
places and copy the tempo of the reference sample. Stretching the whole result (the old "Pace" slider) can't fix an
UNEVEN rhythm. So narration is built sentence by sentence:

1. split_text: sentences (and clauses of very long sentences); manual pauses with "[pause]", "[pause 1.2]", "..." and blank lines.
2. each piece is generated on its own (cached per piece → changing pace/pauses later is instant, no re-generation).
3. tidy: trim the edges and cap hesitations inside a piece.
4. measure each piece's speaking rate (syllables per second of actual speech) and time-stretch it (WSOLA, pitch kept)
   to ONE target rate: a words-per-minute setting, or "auto" = the voice's own average, evened out.
5. join with consistent pauses (comma < sentence < paragraph, scaled by the Pauses setting).
6. "fit to clip": change the pauses first (natural-sounding), then the tempo by at most ±12%.
"""
from __future__ import annotations

import re

import numpy as np

SR = 48000
# words per minute WITHIN sentences (measured on each sentence's spoken length; the pauses between sentences come on
# top, set by the Pauses control). Calibrated on real output: a typical narrator voice speaks ≈ 180-210 here.
RATES = {"slow": 140, "relaxed": 160, "natural": 180, "brisk": 200, "fast": 220}
PAUSE = {"clause": 0.20, "sentence": 0.42, "paragraph": 0.75, "hesitation": 0.50, "manual": 0.60}
STRETCH = (0.88, 1.12)            # per-piece tempo limits: beyond ±12% time-stretching audibly changes the voice


# ------------------------------------------------------------------ text
def syllables(text: str) -> int:
    n = 0
    for w in re.findall(r"[A-Za-z']+|\d+", text):
        if w.isdigit():
            n += max(1, len(w)) * 2 if len(w) < 5 else 6                     # numbers are said as words
            continue
        w = w.lower().strip("'")
        groups = re.findall(r"[aeiouy]+", w)
        k = len(groups)
        if w.endswith("e") and k > 1 and not w.endswith(("le", "ee", "ye")):
            k -= 1
        if w.endswith(("ed",)) and k > 1 and not w.endswith(("ted", "ded")):
            k -= 1
        n += max(1, k)
    return max(1, n)


def words(text: str) -> int:
    return max(1, len(re.findall(r"[A-Za-z0-9']+", text)))


_PAUSE_TAG = re.compile(r"\[\s*pause(?:\s+([\d.]+)\s*s?)?\s*\]", re.I)


def split_text(text: str, long_sentence=16) -> list[dict]:
    """→ [{"text", "pause" (seconds after this piece, before Pauses scaling), "kind"}]. Pieces have real words."""
    text = text.replace("…", "...").replace("\r", "")
    tokens = []                                                    # ("text", s) | ("pause", seconds, kind)
    for para_i, para in enumerate(re.split(r"\n\s*\n|\n", text)):
        if para_i:
            tokens.append(("pause", PAUSE["paragraph"], "paragraph"))
        pos = 0
        for m in _PAUSE_TAG.finditer(para):
            tokens.append(("text", para[pos:m.start()]))
            tokens.append(("pause", float(m.group(1)) if m.group(1) else PAUSE["manual"], "manual"))
            pos = m.end()
        tokens.append(("text", para[pos:]))
    pieces = []

    def add_pause(sec, kind):
        if pieces:
            if pieces[-1]["pause"] < sec:
                pieces[-1]["pause"], pieces[-1]["kind"] = sec, kind

    for tok in tokens:
        if tok[0] == "pause":
            add_pause(tok[1], tok[2])
            continue
        chunk = tok[1]
        # "..." mid-text = a hesitation pause
        parts = re.split(r"\.\.\.+", chunk)
        for pi, part in enumerate(parts):
            if pi:
                add_pause(PAUSE["hesitation"], "hesitation")
            # sentences: split after . ! ? followed by space (not decimals like 2.5, not single initials)
            sents = re.split(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])", part.strip())
            for s in sents:
                s = s.strip()
                if not re.search(r"[A-Za-z0-9]", s):
                    continue
                clauses = [s]
                if words(s) > long_sentence:                      # long sentence: also breathe at clause marks
                    raw = re.split(r"(?<=[,;:])\s+|\s+[—–-]{1,2}\s+", s)
                    clauses, cur = [], ""
                    for c in raw:                                 # only break where both sides have ≥ 4 words
                        cur = f"{cur} {c}".strip()
                        if words(cur) >= 4:
                            clauses.append(cur)
                            cur = ""
                    if cur:
                        if clauses and words(cur) < 4:
                            clauses[-1] = f"{clauses[-1]} {cur}"
                        else:
                            clauses.append(cur)
                for ci, c in enumerate(clauses):
                    pieces.append({"text": c, "pause": PAUSE["clause"] if ci < len(clauses) - 1 else PAUSE["sentence"],
                                   "kind": "clause" if ci < len(clauses) - 1 else "sentence"})
    # one or two words alone ("Wow!") make voice models unstable: merge them into the next piece
    merged = []
    for p in pieces:
        if merged and words(merged[-1]["text"]) <= 2 and merged[-1]["kind"] in ("sentence", "clause"):
            prev = merged.pop()
            p = {**p, "text": f"{prev['text']} {p['text']}"}
        merged.append(p)
    if len(merged) >= 2 and words(merged[-1]["text"]) <= 2:
        last = merged.pop()
        merged[-1] = {**last, "text": f"{merged[-1]['text']} {last['text']}"}
    if merged:
        merged[-1] = {**merged[-1], "pause": 0.0, "kind": "end"}
    return merged


# ------------------------------------------------------------------ audio
def _db(y, hop):
    n = max(1, len(y) // hop)
    fr = y[: n * hop].reshape(n, hop) if len(y) >= hop else np.pad(y, (0, hop - len(y))).reshape(1, hop)
    return 20 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-9)


def tidy(y: np.ndarray, max_inner: float) -> tuple[np.ndarray, float]:
    """Trim leading/trailing silence and shorten pauses inside a piece to `max_inner` s.
    Returns (audio, seconds of actual speech)."""
    hop = SR // 100                                                # 10 ms frames
    db = _db(y, hop)
    thr = max(-50.0, db.max() - 38.0)
    voiced = db > thr
    if not voiced.any():
        return y[:0], 0.0
    # close tiny gaps (< 60 ms) so consonants don't count as pauses
    idx = np.where(voiced)[0]
    a, b = idx[0], idx[-1] + 1
    out, speech, i, keep = [], 0, a, int(max_inner * 100)
    while i < b:
        j = i
        if voiced[i]:
            while j < b and (voiced[j] or (j + 6 < b and voiced[j:j + 6].any())):
                j += 1
            out.append(y[i * hop: j * hop])
            speech += j - i
        else:
            while j < b and not voiced[j]:
                j += 1
            gap = j - i
            if gap > keep:                                         # long hesitation: keep the start and end of it
                h = keep // 2
                out.append(y[i * hop: (i + h) * hop] * np.linspace(1, 0, h * hop, dtype=np.float32))
                out.append(y[(j - h) * hop: j * hop] * np.linspace(0, 1, h * hop, dtype=np.float32))
            else:
                out.append(y[i * hop: j * hop])
        i = j
    pad_in, pad_out = int(0.03 * SR), int(0.06 * SR)
    z = np.concatenate(out)
    s0, s1 = max(0, a * hop - pad_in), min(len(y), b * hop + pad_out)
    z = np.concatenate([y[s0: a * hop], z, y[b * hop: s1]])
    return z.astype(np.float32), speech / 100.0


def _stretch(y: np.ndarray, speed: float) -> np.ndarray:
    if abs(speed - 1) < 0.025 or len(y) < SR // 10:
        return y
    from ..render.audio import stretch
    return stretch(np.stack([y, y]), speed, int(round(len(y) / speed)), True)[0]


def assemble(pieces: list[dict], audio: list[np.ndarray], rate=None, pause_scale=1.0, target=None, pace=1.0) -> tuple[np.ndarray, dict]:
    """Join generated pieces at one steady speaking rate with consistent pauses (see module doc).
    rate: words per minute (number or a RATES name) or None = the voice's own average pace, evened out."""
    pause_scale = float(min(2.5, max(0.3, pause_scale or 1.0)))
    tidied = [tidy(y, max(0.15, 0.28 * pause_scale)) for y in audio]
    syl = [syllables(p["text"]) for p in pieces]
    wds = [words(p["text"]) for p in pieces]
    speech = [max(0.05, len(z) / SR - 0.09) for z, _ in tidied]     # spoken length of each sentence (minus edge padding)
    rates = [s / t for s, t in zip(syl, speech)]                   # syllables per second of speech
    if isinstance(rate, str):
        rate = RATES.get(rate)
    if rate:
        spw = sum(syl) / sum(wds)                                  # this text's syllables per word
        R = float(rate) / 60.0 * spw
    else:                                                          # voice's own pace: syllable-weighted geometric mean
        w = np.array(syl, float)
        R = float(np.exp((w * np.log(np.array(rates))).sum() / w.sum()))
    R *= float(pace or 1.0)
    out_pieces, speeds, limited = [], [], False
    whole = sum(syl) / sum(speech)
    for (y, _), s, r in zip(tidied, syl, rates):
        k = min(1.0, s / 8.0)                                      # short pieces: trust the line's average more
        sp = R / (r * k + whole * (1 - k))                         # playback speed: >1 = faster (piece was too slow)
        if not STRETCH[0] <= sp <= STRETCH[1]:
            limited = True
        sp = float(min(STRETCH[1], max(STRETCH[0], sp)))
        speeds.append(round(sp, 3))
        out_pieces.append(_stretch(y, sp))
    pauses = [p["pause"] * (pause_scale if p["kind"] != "manual" else 1.0) for p in pieces]
    total_speech = sum(len(y) for y in out_pieces) / SR
    spw = sum(syl) / sum(wds)
    info = {"pieces": len(pieces), "speeds": speeds, "limited": limited,
            "voice_wpm": round(whole / spw * 60)}                  # how fast the voice spoke before evening out
    tempo = 1.0
    if target:
        free = sum(pauses)
        need = target - total_speech
        adjustable = [i for i, p in enumerate(pieces) if p["kind"] not in ("manual", "end")]
        lo = sum(pauses[i] * 0.4 for i in adjustable) + sum(pauses[i] for i in range(len(pauses)) if i not in adjustable)
        hi = sum(pauses[i] * 2.2 for i in adjustable) + sum(pauses[i] for i in range(len(pauses)) if i not in adjustable)
        if lo <= need <= hi and adjustable:                        # pauses alone can absorb the difference
            fixed = free - sum(pauses[i] for i in adjustable)
            f = (need - fixed) / max(1e-6, sum(pauses[i] for i in adjustable))
            for i in adjustable:
                pauses[i] *= f
        else:                                                      # pauses to their limit, then the tempo (±12%)
            for i in adjustable:
                pauses[i] *= 0.4 if need < lo else 2.2
            rest = target - sum(pauses)
            tempo = total_speech / max(0.1, rest)
            if not (0.88 <= tempo <= 1.12):
                tempo = None
    if tempo is None:                                              # can't fit nicely: natural length, clip gets resized
        info["fitted"] = False
        tempo = 1.0
        pauses = [p["pause"] * (pause_scale if p["kind"] != "manual" else 1.0) for p in pieces]
    elif target:
        info["fitted"] = True
    parts, segs, pos = [], [], 0
    for p, y, pz in zip(pieces, out_pieces, pauses):
        z = _stretch(y, tempo) if abs(tempo - 1) > 0.01 else y
        parts.append(z)
        segs.append({"text": p["text"], "a": pos, "b": pos + len(z)})       # where each sentence sits in the file (samples)
        pos += len(z)
        if pz > 0:
            n = int(round(pz * SR))
            parts.append(np.zeros(n, np.float32))
            pos += n
    y = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    if target and info.get("fitted"):
        m = int(round(target * SR))
        y = y[:m] if len(y) >= m else np.pad(y, (0, m - len(y)))
    info["segs"] = [{"text": s["text"], "a": round(min(s["a"], len(y)) / SR, 4), "b": round(min(s["b"], len(y)) / SR, 4)}
                    for s in segs if s["a"] < len(y)]
    spoken = sum(speech[i] / speeds[i] for i in range(len(speech))) / tempo
    info["wpm"] = round(sum(wds) / max(0.1, spoken) * 60)
    info["natural"] = round(len(y) / SR, 3) if not info.get("fitted") else None
    return y.astype(np.float32), info


def estimate(text: str, rate=None, pause_scale=1.0) -> float:
    """Expected seconds for the UI (rate None → assume 'natural')."""
    ps = split_text(text)
    wpm = RATES.get(rate, rate) if rate else RATES["natural"]
    sp = sum(words(p["text"]) for p in ps) / (float(wpm) / 60)
    return round(sp + sum(p["pause"] * pause_scale for p in ps) + 0.1, 2)
