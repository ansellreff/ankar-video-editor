"""Subtitle import (.srt / .ass / .vtt) and Whisper transcription → timed lines."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import av
import numpy as np
from scipy.io import wavfile

from .paths import MODELS


def _ts(s: str) -> float:
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    if len(parts) == 2:
        parts = ["0"] + parts
    h, m, sec = parts
    return int(h) * 3600 + int(m) * 60 + float(sec)


def parse(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    ext = path.suffix.lower()
    out = []
    if ext == ".ass":
        fmt = None
        for line in text.splitlines():
            if line.startswith("Format:") and fmt is None and "Text" in line and "Start" in line:
                fmt = [x.strip() for x in line[7:].split(",")]
            if line.startswith("Dialogue:"):
                f = line[9:].split(",", len(fmt or range(10)) - 1)
                fields = dict(zip(fmt or ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"], f))
                body = re.sub(r"\{[^}]*\}", "", fields.get("Text", "")).replace(r"\N", "\n").replace(r"\n", "\n").strip()
                if body:
                    out.append((_ts(fields["Start"]), _ts(fields["End"]), body))
    else:  # srt / vtt
        for block in re.split(r"\n\s*\n", text.replace("\r", "")):
            m = re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", block)
            if not m:
                continue
            lines = block[m.end():].strip().splitlines()
            body = re.sub(r"<[^>]+>", "", "\n".join(lines)).strip()
            if body:
                out.append((_ts(m.group(1)), _ts(m.group(2)), body))
    return sorted(out)


DEFAULT_GLOSSARY = ["E-DA Theme Park", "Kaohsiung", "Ansell", "Karina", "Fo Guang Shan", "Hsinchu", "MOTC",
                    "Tourism Administration", "Taiwan"]
KNOWN_FIXES = {"ita timpa": "E-DA Theme Park", "eda theme park": "E-DA Theme Park", "kao shion": "Kaohsiung",
               "kaoshiung": "Kaohsiung", "gaoxiong": "Kaohsiung", "enzo": "Ansell", "hokkaungsan": "Fo Guang Shan",
               "foguangshan": "Fo Guang Shan", "sin chu": "Hsinchu", "xinzhu": "Hsinchu",
               "yida world": "E-DA World", "yida amusement park": "E-DA Theme Park", "yida theme park": "E-DA Theme Park",
               "yida": "E-DA", "foguang mountain": "Fo Guang Shan"}
ENGLISH_BIAS = 0.35        # treat as English if Whisper gives English at least this probability (accented English)
LANG_NAMES = {"en": "English", "id": "Indonesian", "zh": "Mandarin", "ms": "Malay", "jw": "Javanese", "ja": "Japanese", "ko": "Korean"}


def model_file() -> Path:
    for name in ("ggml-medium-q5_0.bin", "ggml-medium.bin", "ggml-small.bin", "ggml-base.bin"):
        if (MODELS / name).exists():
            return MODELS / name
    raise FileNotFoundError("No Whisper model in models/ (expected ggml-medium-q5_0.bin).")


def fix_terms(text: str, glossary) -> str:
    for wrong, right in KNOWN_FIXES.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.I)
    for term in glossary:                                   # canonical spelling/casing for glossary terms
        text = re.sub(rf"\b{re.escape(term)}\b", term, text, flags=re.I)
    return text.strip()


def utterances(x: np.ndarray, sr=16000, max_len=24.0):
    """Energy VAD → [(start_sample, end_sample)] speech chunks, merged over short pauses, split if too long."""
    hop = int(sr * 0.03)
    n = len(x) // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    floor = np.percentile(db, 15)
    thr = max(-48.0, floor + 9.0)
    voiced = db > thr
    segs, i = [], 0
    while i < n:
        if voiced[i]:
            j = i
            while j < n and (voiced[j] or (j + 12 < n and voiced[j:j + 12].any())):   # bridge pauses < 0.36 s
                j += 1
            if (j - i) * 0.03 >= 0.35:
                segs.append([i, j])
            i = j
        else:
            i += 1
    out = []
    for a, b in segs:
        a, b = max(0, a - 5), min(n, b + 5)                   # 150 ms padding
        while (b - a) * 0.03 > max_len:                       # split long runs at the quietest frame
            lo, hi = a + int(8 / 0.03), a + int(max_len / 0.03)
            cut = lo + int(np.argmin(db[lo:hi]))
            out.append((a * hop, cut * hop))
            a = cut
        out.append((a * hop, b * hop))
    return out


_model = None


def _get_model():
    global _model
    from pywhispercpp.model import Model
    if _model is None or getattr(_model, "_vs_path", None) != str(model_file()):
        _model = Model(str(model_file()), n_threads=max(2, (os.cpu_count() or 4) - 2), print_progress=False, print_realtime=False)
        _model._vs_path = str(model_file())
    return _model


def transcribe_multilingual(path: str, t0: float, t1: float, start_offset=0.0, glossary=None, progress=None,
                            force_lang=None, english_bias=ENGLISH_BIAS):
    """Lines in English: English speech as is; other languages translated to English and wrapped in ( ).
    Returns [{start, end, text, lang, translated, original, src}] with times relative to t0.
    force_lang: skip detection (used to redo a line as Indonesian / Mandarin / English)."""
    from scipy.signal import resample_poly
    from .render.audio import decode_range
    glossary = glossary or DEFAULT_GLOSSARY
    x = decode_range(path, t0, t1, start_offset).mean(axis=0)
    x16 = resample_poly(x, 1, 3).astype(np.float32)
    chunks = utterances(x16) if not force_lang else [(0, len(x16))]
    m = _get_model()
    prompt = "A travel vlog in Taiwan. Names: " + ", ".join(glossary) + "."
    out = []
    for k, (a, b) in enumerate(chunks):
        seg = x16[a:b]
        if len(seg) < 16000:
            seg = np.pad(seg, (0, 16000 - len(seg)))
        if force_lang:
            lang = force_lang
        else:
            (lang, _p), probs = m.auto_detect_language(seg)
            if lang != "en" and float(probs.get("en", 0.0)) >= english_bias:   # accented English is often mis-detected
                lang = "en"
        # pywhispercpp keeps parameters between calls → set translate / initial_prompt explicitly every time
        common = dict(language=lang, max_len=60, split_on_word=True, token_timestamps=True, no_context=True, suppress_blank=True)
        if lang == "en":
            res, original = m.transcribe(seg, initial_prompt=prompt, translate=False, **common), None   # names prompt only helps English
        else:
            original = " ".join(s.text.strip() for s in m.transcribe(seg, initial_prompt="", translate=False, **common)).strip()
            res = m.transcribe(seg, initial_prompt="", translate=True, **common)   # no English prompt: it leaks into translations
        for s in res:
            txt = fix_terms(s.text, glossary)
            if not txt or txt in ("[BLANK_AUDIO]", "(music)", "[Music]"):
                continue
            if lang != "en":
                txt = txt.strip("()[] ")
                txt = f"({txt})"
            st = a / 16000 + s.t0 / 100
            en = min(b / 16000, a / 16000 + s.t1 / 100)
            if out and st < out[-1]["end"]:                    # never overlap the previous line
                st = out[-1]["end"]
            if en - st < 0.3:
                en = st + 0.3
            out.append({"start": round(st, 3), "end": round(en, 3), "text": txt, "lang": lang,
                        "translated": lang != "en", **({"original": original} if original else {}),
                        "src": [round(t0 + a / 16000, 3), round(t0 + b / 16000, 3)]})   # source range, for "redo this line"
        if progress:
            progress((k + 1) / max(1, len(chunks)))
    return out


# ---------------------------------------------------------------- word-level captions (v3)
def realign(words: list[dict], text: str) -> list[dict]:
    """Give the tokens of `text` the timing of `words` (used after glossary fixes or manual edits change the words)."""
    toks = text.split()
    if not toks:
        return []
    if not words:
        return [{"w": w, "t0": 0.0, "t1": 0.0} for w in toks]
    if len(toks) == len(words):
        return [{**o, "w": w} for o, w in zip(words, toks)]
    t0, t1 = words[0]["t0"], words[-1]["t1"]
    total = sum(len(w) + 1 for w in toks)
    out, acc = [], 0.0
    for w in toks:                                            # spread by length across the original span
        a = t0 + (t1 - t0) * acc / total
        acc += len(w) + 1
        o = {"w": w, "t0": round(a, 3), "t1": round(t0 + (t1 - t0) * acc / total, 3)}
        mid = (o["t0"] + o["t1"]) / 2
        near = min(words, key=lambda x: abs((x["t0"] + x["t1"]) / 2 - mid))
        for k in ("conf", "emph"):                            # keep confidence / emphasis of the word that was there
            if k in near:
                o[k] = near[k]
        out.append(o)
    return out


def transcribe_words(path: str, t0: float, t1: float, start_offset=0.0, glossary=None, progress=None,
                     english_bias=ENGLISH_BIAS):
    """Utterances with per-word timing (seconds relative to t0):
    [{lang, translated, original, words:[{w, t0, t1}]}]. English keeps Whisper's word times; translated speech gets the
    utterance span spread over the English words (so karaoke highlighting still flows)."""
    from scipy.signal import resample_poly
    from .render.audio import decode_range
    glossary = glossary or DEFAULT_GLOSSARY
    x = decode_range(path, t0, t1, start_offset).mean(axis=0)
    x16 = resample_poly(x, 1, 3).astype(np.float32)
    chunks = utterances(x16)
    m = _get_model()
    prompt = "A travel vlog in Taiwan. Names: " + ", ".join(glossary) + "."
    out = []
    for k, (a, b) in enumerate(chunks):
        seg = x16[a:b]
        if len(seg) < 16000:
            seg = np.pad(seg, (0, 16000 - len(seg)))
        (lang, _p), probs = m.auto_detect_language(seg)
        if lang != "en" and float(probs.get("en", 0.0)) >= english_bias:
            lang = "en"
        base = a / 16000
        span = (b - a) / 16000
        if lang == "en":
            res = m.transcribe(seg, language="en", initial_prompt=prompt, translate=False, max_len=1, split_on_word=True,
                               token_timestamps=True, no_context=True, suppress_blank=True)
            confs = _word_confidences(m)
            words = []
            for i, s in enumerate(res):
                w = s.text.strip()
                if not w or w.startswith("[") or w in ("(music)",):
                    continue
                conf = confs[i] if i < len(confs) else 1.0
                words.append({"w": w, "t0": round(base + s.t0 / 100, 3), "t1": round(min(base + span, base + s.t1 / 100), 3),
                              "conf": round(conf, 3)})
            words = _drop_repeats(words)
            if not words:
                out.append(_unheard(base, span, seg[: b - a], "en"))
                continue
            fixed = fix_terms(" ".join(o["w"] for o in words), glossary)
            words = realign(words, fixed)
            mean = float(np.mean([w["conf"] for w in words]))
            lang_p = float(probs.get("en", 0.0))
            # Whisper can "hear" a fluent sentence in mumbling/noise: unsure language + lower word scores give it away
            suspect = (lang_p < 0.9 and mean < 0.88) or mean < 0.75
            out.append({"lang": "en", "translated": False, "words": words, **({"suspect": True} if suspect else {})})
        else:
            common = dict(language=lang, no_context=True, suppress_blank=True, max_len=0, split_on_word=False, token_timestamps=False)
            segs = m.transcribe(seg, initial_prompt="", translate=False, extract_probability=True, **common)
            original = " ".join(s.text.strip() for s in segs).strip()
            probs_o = [s.probability for s in segs if s.probability == s.probability]
            english = " ".join(s.text.strip() for s in m.transcribe(seg, initial_prompt="", translate=True, **common)).strip()
            english = fix_terms(english.strip("()[] "), glossary)
            if not english:
                out.append(_unheard(base, span, seg[: b - a], lang))
                continue
            speech = speech_bounds(seg[: b - a])
            words = realign([{"w": "", "t0": round(base + speech[0], 3), "t1": round(base + speech[1], 3)}], english)
            conf = round(float(np.mean(probs_o)) if probs_o else 1.0, 3)
            out.append({"lang": lang, "translated": True, "original": original, "words": words, "line_conf": conf})
        if progress:
            progress((k + 1) / max(1, len(chunks)))
    return out


UNCLEAR_WORD = 0.40          # word confidence below this → "check this word"
UNCLEAR_LINE = 0.50          # translated line (no word scores) below this → "check this line"
_PUNCT = set(".,!?;:…-\"'()[]")


def _word_confidences(m) -> list[float]:
    """Per segment (= word with max_len=1) of the last transcribe: the lowest probability of its text tokens,
    ignoring punctuation tokens (a trailing '.' is often unsure even when the word is clear)."""
    import _pywhispercpp as pw
    ctx = m._ctx
    eot = pw.whisper_token_eot(ctx)
    out = []
    for i in range(pw.whisper_full_n_segments(ctx)):
        ps = []
        for j in range(pw.whisper_full_n_tokens(ctx, i)):
            if pw.whisper_full_get_token_id(ctx, i, j) >= eot:
                continue
            txt = str(pw.whisper_full_get_token_text(ctx, i, j)).strip()
            if not txt or all(ch in _PUNCT for ch in txt):
                continue
            ps.append(float(pw.whisper_full_get_token_p(ctx, i, j)))
        out.append(min(ps) if ps else 1.0)
    return out


def _drop_repeats(words: list[dict]) -> list[dict]:
    """Whisper sometimes loops on noise ("the the the the ..."): keep at most 3 identical words in a row."""
    out = []
    for w in words:
        if len(out) >= 3 and all(o["w"].lower() == w["w"].lower() for o in out[-3:]):
            continue
        out.append(w)
    return out


def _unheard(base, span, x16, lang):
    """Speech was detected but nothing could be recognised → an empty entry the review list shows as 'unclear speech'."""
    a, b = speech_bounds(x16)
    return {"lang": lang, "translated": False, "words": [], "unheard": True,
            "start": round(base + a, 3), "end": round(base + max(b, a + 0.4), 3)}


def review_flags(cap: dict) -> list[str]:
    """Why a caption needs a human check (empty list = looks fine)."""
    why = []
    low = [w["w"] for w in cap.get("words", []) if w.get("conf", 1.0) < UNCLEAR_WORD]
    if cap.get("suspect"):
        unsure = [w["w"] for w in cap.get("words", []) if w.get("conf", 1.0) < 0.7]
        why.append("may be misheard — listen" + (": " + ", ".join(unsure[:6]) if unsure else ""))
    elif low:
        why.append("unclear: " + ", ".join(low[:6]))
    if cap.get("line_conf", 1.0) < UNCLEAR_LINE:
        why.append(f"translation unsure ({cap['line_conf']:.0%})")
    return why


def speech_bounds(x16: np.ndarray) -> tuple[float, float]:
    """First/last voiced moment of a 16 kHz utterance (seconds)."""
    hop = 320
    n = max(1, len(x16) // hop)
    db = 20 * np.log10(np.sqrt(np.mean(x16[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9) if len(x16) >= hop else np.array([0.0])
    v = np.where(db > max(-48.0, db.max() - 35))[0]
    if not len(v):
        return 0.0, len(x16) / 16000
    return v[0] * hop / 16000, (v[-1] + 1) * hop / 16000


PUNCT_END = (".", "!", "?", ",", ";", ":", "…")


def chunk_captions(utts: list[dict], max_words=5, max_chars=28, gap=0.35, min_dur=0.6) -> list[dict]:
    """Group words into caption lines: ≤ max_words / max_chars, break after punctuation or pauses > gap seconds.
    Returns [{start, end, words:[{w, t0, t1}] (relative to start), lang, translated, original}] (times absolute)."""
    caps = []
    for u in utts:
        if u.get("unheard") or not u.get("words"):
            continue
        cur = []

        def flush():
            if not cur:
                return
            ws = [dict(w) for w in cur]
            if u["translated"]:
                ws[0]["w"] = "(" + ws[0]["w"]
                ws[-1]["w"] = ws[-1]["w"] + ")"
            start, end = ws[0]["t0"], max(ws[-1]["t1"], ws[0]["t0"] + min_dur)
            cap = {"start": start, "end": end, "lang": u["lang"], "translated": u["translated"],
                   **({"original": u["original"]} if u.get("original") else {}),
                   **({"line_conf": u["line_conf"]} if "line_conf" in u else {}),
                   **({"suspect": True} if u.get("suspect") else {}),
                   "words": [{"w": w["w"], "t0": round(w["t0"] - start, 3), "t1": round(w["t1"] - start, 3),
                              **({"conf": w["conf"]} if "conf" in w else {})} for w in ws]}
            cap["review"] = review_flags(cap)
            caps.append(cap)
            cur.clear()

        for i, w in enumerate(u["words"]):
            if cur:
                chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
                pause = w["t0"] - cur[-1]["t1"]
                if len(cur) >= max_words or chars > max_chars or pause > gap or cur[-1]["w"].endswith(PUNCT_END):
                    flush()
            cur.append(w)
        flush()
    for a, b in zip(caps, caps[1:]):                          # no overlaps; small gaps are closed so lines don't flicker
        if a["end"] > b["start"] or b["start"] - a["end"] < 0.25:
            a["end"] = max(a["start"] + 0.2, b["start"])
    return caps


def transcribe(path: str, t0: float, t1: float, start_offset=0.0, language="en") -> list[tuple[float, float, str]]:
    """Whisper (pywhispercpp, base model in models/) on source range [t0, t1). Times are relative to t0."""
    model = MODELS / "ggml-base.bin"
    if not model.exists():
        raise FileNotFoundError("Put the Whisper model ggml-base.bin into the models/ folder first.")
    from pywhispercpp.model import Model
    from .render.audio import decode_range
    x = decode_range(path, t0, t1, start_offset).mean(axis=0)
    idx = np.linspace(0, len(x) - 1, int(len(x) * 16000 / 48000))
    x16 = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        wavfile.write(wav, 16000, (np.clip(x16, -1, 1) * 32767).astype(np.int16))
        m = Model(str(model), n_threads=4, print_progress=False, print_realtime=False)
        segs = m.transcribe(str(wav), language=language, max_len=42, split_on_word=True, token_timestamps=True)
    return [(s.t0 / 100, s.t1 / 100, s.text.strip()) for s in segs if s.text.strip()]
