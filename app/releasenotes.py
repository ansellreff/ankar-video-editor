"""CHANGELOG.md ⇄ release notes. One format, read by the app (Help ▸ What's new), scripts/release.py and the website:

    ## 1.1.0 — 2026-12-01
    - Plain-language note (what users notice)
    - Another note

Newest version first. Text after the bullets' "- " is plain text (no HTML)."""
from __future__ import annotations

import re
from pathlib import Path

from .paths import ROOT

FILE = ROOT / "CHANGELOG.md"
_HEAD = re.compile(r"^##\s+v?(\d+\.\d+\.\d+)\s*(?:[—–-]+\s*(\d{4}-\d{2}-\d{2}))?\s*$")


def parse(text: str) -> list[dict]:
    out, cur = [], None
    for line in text.splitlines():
        m = _HEAD.match(line.strip())
        if m:
            cur = {"version": m.group(1), "date": m.group(2) or "", "notes": []}
            out.append(cur)
        elif cur and line.strip().startswith(("- ", "* ")):
            cur["notes"].append(line.strip()[2:].strip())
        elif cur and cur["notes"] and line.startswith("  ") and line.strip():
            cur["notes"][-1] += " " + line.strip()         # wrapped bullet
    return out


def load(path: Path | None = None) -> list[dict]:
    try:
        return parse((path or FILE).read_text(encoding="utf-8"))
    except OSError:
        return []
