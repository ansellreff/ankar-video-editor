"""Pronunciation list for AI narration (shared by all projects): library/pronunciations.json {"Kaohsiung": "Gao-shyong"}.

The voice engine gets the respelled text; the clip text, captions and sentence blocks keep the real spelling.
Whole words / phrases, case-insensitive, longest first. Only sentences that contain a listed name change (the piece
cache key uses the respelled text), so editing the list regenerates just those sentences.
Defaults are names from the Taiwan vlog, spelled the way they're said in Taiwan (Mandarin) for an English voice.
"""
from __future__ import annotations

import json
import re

from ..paths import LIBRARY

FILE = LIBRARY / "pronunciations.json"
DEFAULTS = {
    "Kaohsiung": "Gao-shyong",
    "Taipei": "Tie-pay",
    "E-DA": "Ee-dah",
    "Wanpi": "Wahn-pee",
    "Fo Guang Shan": "Foh Gwahng Shahn",
    "Zuoying": "Dzwaw-ying",
    "Dashu": "Dah-shoo",
    "Chiayi": "Jya-yee",
}
_cache = {"mtime": None, "rules": None}


def rules() -> dict:
    if not FILE.exists():
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(DEFAULTS, indent=1, ensure_ascii=False), encoding="utf-8")
    m = FILE.stat().st_mtime
    if _cache["mtime"] != m:
        try:
            d = json.loads(FILE.read_text(encoding="utf-8-sig"))      # -sig: files saved by Notepad/PowerShell have a BOM
            _cache["rules"] = {str(k): str(v) for k, v in d.items() if str(k).strip() and str(v).strip()}
        except Exception:  # noqa: BLE001  (a broken file must never stop narration)
            _cache["rules"] = dict(DEFAULTS)
        _cache["mtime"] = m
    return _cache["rules"]


def apply(text: str) -> str:
    out = text
    for word in sorted(rules(), key=len, reverse=True):
        out = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", rules()[word], out, flags=re.I)
    return out


def save(d: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    _cache["mtime"] = None
