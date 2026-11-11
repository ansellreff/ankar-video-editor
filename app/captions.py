"""Caption helpers: templates, building caption text clips, editing text with timing kept, re-chunking.

A caption clip is a normal text clip with
  text.caption = {template, style, words:[{w, t0, t1, emph?, conf?}], group}
word times relative to the clip start; text.content mirrors the words (joined with spaces) for the timeline/inspector.
meta = {lang, translated, original, review:[reasons], review_ok}
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache

from .paths import EFFECTS, ROOT

CHUNK_KEYS = ("max_words", "max_chars")
NOT_STYLE = ("id", "name", "desc", "anim", "y", "max_words", "max_chars")
USER_PRESETS = ROOT / "presets" / "user_presets.json"


@lru_cache(maxsize=1)
def _builtin():
    return json.loads((EFFECTS / "presets.json").read_text(encoding="utf-8")).get("caption_templates", [])


def user_presets() -> dict:
    try:
        return json.loads(USER_PRESETS.read_text(encoding="utf-8"))
    except Exception:
        return {"looks": [], "captions": []}


def templates() -> list[dict]:
    return _builtin() + [dict(t, user=True) for t in user_presets().get("captions", [])]


def template(tid: str | None) -> dict:
    ts = templates()
    for t in ts:
        if t["id"] == tid:
            return t
    return ts[0]


def style_of(tpl: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in tpl.items() if k not in NOT_STYLE and k != "user"}


def content_of(words) -> str:
    return " ".join(w["w"] for w in words)


_NUM = re.compile(r"\d")


def auto_emphasis(words, glossary):
    """Mark numbers and glossary names (Kaohsiung, E-DA ...) as emphasis words (shown by Keyword Highlight)."""
    names = {p.strip("().,!?").lower() for g in glossary or [] for p in g.split()}
    for w in words:
        core = w["w"].strip("().,!?\"'").lower()
        if _NUM.search(core) or (core in names and len(core) > 2):
            w["emph"] = True
    return words


def parse_edit(text: str):
    """User-typed caption text → tokens with emphasis: '*word*' marks emphasis."""
    out = []
    for tok in text.split():
        emph = len(tok) > 2 and tok.startswith("*") and tok.endswith("*")
        out.append((tok.strip("*") if emph else tok, emph))
    return out


def retime(words: list[dict], text: str, dur: float) -> list[dict]:
    """New text for a caption, keeping the timing: same word count → same slots; otherwise words are spread over
    the old span by length. Confidence is dropped for changed words (a human checked them)."""
    toks = parse_edit(text)
    if not toks:
        return []
    if not words:
        words = [{"w": "", "t0": 0.0, "t1": max(0.2, dur)}]
    if len(toks) == len(words):
        out = []
        for (w, emph), o in zip(toks, words):
            n = {"w": w, "t0": o["t0"], "t1": o["t1"]}
            if emph or (o.get("emph") and w == o["w"]):
                n["emph"] = True
            if w == o["w"] and "conf" in o:
                n["conf"] = o["conf"]
            out.append(n)
        return out
    t0, t1 = words[0]["t0"], max(words[-1]["t1"], words[0]["t0"] + 0.2)
    total = sum(len(w) + 1 for w, _ in toks)
    out, acc = [], 0.0
    for w, emph in toks:
        a = t0 + (t1 - t0) * acc / total
        acc += len(w) + 1
        n = {"w": w, "t0": round(a, 3), "t1": round(t0 + (t1 - t0) * acc / total, 3)}
        if emph:
            n["emph"] = True
        out.append(n)
    return out


def caption_text(words, tpl: dict, x=0.5, y=None, group=None) -> dict:
    """The `text` block of a caption clip."""
    return {"content": content_of(words), "preset": "caption_auto", "x": x, "y": tpl.get("y", 0.75) if y is None else y,
            "times": None, "anim": copy.deepcopy(tpl.get("anim") or {"in": "none", "in_dur": 0, "out": "none", "out_dur": 0}),
            "caption": {"template": tpl["id"], "style": style_of(tpl), "words": words, **({"group": group} if group else {})}}


def shift_words(c: dict, dt: float, dur: float):
    """Clip start moved by -dt (head trim): word times move by dt; words outside [0, dur) are dropped."""
    cap = c["text"]["caption"]
    ws = []
    for w in cap["words"]:
        a, b = w["t0"] + dt, w["t1"] + dt
        if b <= 0.02 or a >= dur - 0.02:
            continue
        ws.append({**w, "t0": round(max(0.0, a), 3), "t1": round(min(dur, b), 3)})
    cap["words"] = ws
    c["text"]["content"] = content_of(ws)


def chunk_words(words_abs: list[dict], max_words: int, max_chars: int, gap=0.35):
    """Absolute-time words → [[word, ...], ...] lines (break on count/length/pause/punctuation)."""
    lines, cur = [], []
    for w in words_abs:
        if cur:
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if len(cur) >= max_words or chars > max_chars or w["t0"] - cur[-1]["t1"] > gap or cur[-1]["w"].endswith((".", "!", "?", ",", ";", ":")):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines
