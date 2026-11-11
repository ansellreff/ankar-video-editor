"""Creative style: the choices the AI Editor suggests and the editor decides (stage 3), in 4 short rounds.

Nothing here is a default rule. Every value is pre-filled by Claude WITH a reason, the editor accepts or changes it,
and the result is the style sheet docs/edit/style.md (human, editable) + docs/edit/style.json (machine). The editor's
edits to style.md win (re-read before use). Presets ("My styles" in library/styles/ + built-ins) only pre-fill."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from ..paths import LIBRARY

STYLES_DIR = LIBRARY / "styles"

# round id → (title, [(field id, label, hint)])
ROUNDS = [
    ("goal", "① Goal, versions & duration", [
        ("purpose", "Purpose & audience", "who it is for and why (e.g. tourism event entry, friends & family, a client)"),
        ("platform", "Platform & format", "Reels/TikTok 9:16 · YouTube 16:9 · Shorts 9:16 · 1:1 · 4:5 · client spec"),
        ("viewer_action", "What viewers should do", "follow / comment / share / visit / just enjoy"),
        ("versions", "Versions & what each contains", "long, parts, personal POV, teaser…"),
        ("duration", "Duration per version (always asked)", "target ± range, hard maximum, may it grow? e.g. 'Part 1 2:00 ± 0:15, max 3:00'"),
        ("deadline", "Deadline", "posting / delivery date"),
        ("brand_rules", "Brand & client rules", "required logos, hashtags, words or claims to avoid, facts only from the brief"),
        ("people", "People", "names, roles, speaker colors, who is in which version, strangers' faces to avoid"),
    ]),
    ("story", "② Story & voice", [
        ("structure", "Structure", "hook first or not (which moment), intro type, scene order, teaser / 'previously', ending"),
        ("call_to_action", "Ending & call to action", "e.g. a question to comment on, end card text, or none"),
        ("mood", "Mood & personality", "funny, warm, informative, epic, calm…"),
        ("narration", "Narration", "none / AI voices / own recording; voice per person; dialogue or monologue; emotion"),
        ("language", "Language", "narration + subtitle language; translated lines in ( )"),
        ("must_have", "Must-have moments", "shots or moments that must be in"),
        ("avoid", "Shots to avoid", "bad takes, strangers' faces, anything not to show"),
    ]),
    ("look_sound", "③ Look & sound", [
        ("pacing", "Pacing", "cut rhythm, seconds after narration, scenery hold, slow-mo / speed ramps / hyperlapse"),
        ("framing", "Framing", "crop to fill vs blurred letterbox, split screen vs single POV"),
        ("music", "Music", "songs per version, where they change, cut on the beat or free, level"),
        ("music_rights", "Music rights plan", "own files / licensed / platform in-app music (→ no-music export)"),
        ("footage_sound", "Footage sound", "level of the original sound, moments at full volume"),
        ("sfx", "Sound effects", "reveal sounds, whooshes, typing, none"),
        ("look", "Color look", "one look for the video (+ night boost?)"),
        ("transitions", "Transitions", "the set, signature transitions, how often (or hard cuts only)"),
    ]),
    ("text_brand", "④ Text, brand & cover", [
        ("captions", "Captions", "template, speaker colors, position, words per line"),
        ("titles", "Titles & tags", "hook text wording, location / name tags, typed date intro"),
        ("logos", "Logos", "logo strip layout and the scene it starts from, or none"),
        ("end_card", "End card", "final text / logo, or none"),
        ("cover", "Cover / thumbnail", "a frame + title, or a frame only"),
        ("delivery", "Delivery files", "with / without a no-music copy, file names"),
    ]),
]
ROUND_IDS = [r for r, _, _ in ROUNDS]
FIELDS = {f: (rid, label, hint) for rid, _, fs in ROUNDS for f, label, hint in fs}

PRESETS = {
    "fast_viral_travel": {"name": "Fast viral travel vlog", "builtin": True,
                          "note": "the settings of the 'Having Fun in Taiwan' edit",
                          "values": {
                              "platform": "Reels/TikTok 9:16, 1080×1920 30 fps",
                              "structure": "short parts open with a hook in the first 1.5–3 s; series parts end with a teaser and the next part opens with a short 'previously'; long version in script order with the full typed-date intro",
                              "call_to_action": "a question that invites comments, end card text",
                              "pacing": "a new visual every 1.5–3 s; each shot plays 1–2 s past its narration; scenery / drone / tiny planet 3–4 s with no voice; long slow parts sped up or hyperlapse",
                              "music": "cut on the beat, scene changes on downbeats; music ducks under narration",
                              "music_rights": "post the no-music file and add the song in the app",
                              "footage_sound": "30% (−10.5 dB); screams / funny moments at full volume",
                              "look": "clean_natural + night boost on night clips",
                              "transitions": "whip pan / zoom punch / flash on beats, light-leak between days, dip to black at scene ends",
                              "captions": "karaoke pill, one color per speaker, y≈0.70",
                              "narration": "AI voices of the people, natural conversation, emotion 0.2",
                              "delivery": "FINAL + FINAL (no music)"}},
    "calm_cinematic": {"name": "Calm cinematic", "builtin": True, "values": {
        "pacing": "long shots (4–8 s), slow cuts on phrases, slow motion where it adds feeling",
        "transitions": "cross dissolves and dip to black only", "music": "one emotional track, cuts on phrases not beats",
        "captions": "small, clean, bottom", "look": "soft, warm cinematic look", "footage_sound": "ambient sound kept low under music"}},
    "documentary": {"name": "Informative / documentary", "builtin": True, "values": {
        "pacing": "medium (3–5 s shots), each fact gets a clear shot", "narration": "one calm narrator voice",
        "titles": "lower thirds for places and names", "transitions": "hard cuts, occasional cross dissolve",
        "music": "light background bed, ducks under narration", "captions": "full subtitles, bottom"}},
    "casual_daily": {"name": "Casual daily vlog", "builtin": True, "values": {
        "pacing": "medium-fast, jump cuts allowed", "narration": "own voice or none, natural sound kept",
        "footage_sound": "original sound up front (70–100%)", "transitions": "hard cuts, a few zooms",
        "captions": "bold word-by-word captions", "music": "upbeat bed, low"}},
    "custom": {"name": "Custom", "builtin": True, "values": {}},
}


def round_spec(rid: str) -> dict:
    for r, title, fs in ROUNDS:
        if r == rid:
            return {"id": r, "title": title, "fields": [{"id": f, "label": l, "hint": h} for f, l, h in fs]}
    raise ValueError(f"unknown round {rid} (rounds: {', '.join(ROUND_IDS)})")


class StyleSheet:
    """docs/edit/style.json + style.md for one project."""

    def __init__(self, project_dir: Path, workflow):
        self.dir = Path(project_dir)
        self.wf = workflow
        self.json_file = self.dir / "docs" / "edit" / "style.json"
        self.data = self._load()

    def _load(self) -> dict:
        try:
            d = json.loads(self.json_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("values", {})                       # field → {value, decided_by, reason}
        d.setdefault("rounds_done", [])
        d.setdefault("preset", None)
        return d

    def _save(self):
        self.json_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.json_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.json_file)

    def set_round(self, rid: str, answers: dict, recommendations: dict):
        """answers: field → value the editor submitted. decided_by = 'you' when it differs from the recommendation."""
        for f, v in answers.items():
            if f not in FIELDS:
                continue
            rec = (recommendations or {}).get(f) or {}
            same = str(v).strip() == str(rec.get("value", "")).strip()
            self.data["values"][f] = {"value": str(v).strip(), "reason": rec.get("reason", ""),
                                      "decided_by": ("AI suggestion accepted" if same else "you")
                                      if not rec.get("from_brief") else "from your brief"}
        if rid not in self.data["rounds_done"]:
            self.data["rounds_done"].append(rid)
        self._save()
        self.write_md()

    def write_md(self):
        """Render style.md. If the editor edited it, their table values are read back first (their edits win)."""
        self.sync_from_md()
        lines = ["# Style sheet (the creative decisions for this project)", "",
                 "Edit any value in the tables; your edits win. Then press **Approve style** in the AI Editor.", ""]
        for rid, title, fs in ROUNDS:
            lines += [f"## {title}", "", "| Choice | Value | Decided by | Reason |", "|---|---|---|---|"]
            for f, label, _ in fs:
                e = self.data["values"].get(f) or {}
                cell = lambda s: str(s or "").replace("|", "/").replace("\n", " ")  # noqa: E731
                lines.append(f"| {label} | {cell(e.get('value'))} | {cell(e.get('decided_by'))} | {cell(e.get('reason'))} |")
            lines.append("")
        text = "\n".join(lines)
        md = self.dir / "docs" / "edit" / "style.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(text, encoding="utf-8")
        self.wf.data["docs"]["edit/style.md"] = {"sha": __import__("hashlib").sha1(text.encode()).hexdigest()[:16],
                                                 "text": text, "at": time.strftime("%Y-%m-%d %H:%M")}
        self.wf.save()

    def sync_from_md(self) -> list[str]:
        """Read the editor's edits from style.md back into the values. Returns the fields they changed."""
        md = self.dir / "docs" / "edit" / "style.md"
        if not md.exists() or not self.wf.edited_by_user("edit/style.md"):
            return []
        label_to_field = {label: f for f, (_, label, _) in FIELDS.items()}
        changed = []
        for row in md.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$", row)
            if not m or m.group(1) in ("Choice", "---"):
                continue
            f = label_to_field.get(m.group(1))
            if not f:
                continue
            old = (self.data["values"].get(f) or {}).get("value", "")
            if m.group(2) != old:
                self.data["values"][f] = {"value": m.group(2), "reason": m.group(4), "decided_by": "you"}
                changed.append(f)
        if changed:
            self._save()
        return changed

    def summary(self) -> str:
        self.sync_from_md()
        out = []
        for rid, title, fs in ROUNDS:
            vals = [(label, (self.data["values"].get(f) or {}).get("value")) for f, label, _ in fs]
            vals = [f"- {l}: {v}" for l, v in vals if v]
            if vals:
                out += [title] + vals
        missing = [title for rid, title, _ in ROUNDS if rid not in self.data["rounds_done"]]
        if missing:
            out.append("Rounds not answered yet: " + ", ".join(missing))
        return "\n".join(out) or "No style decided yet."

    def duration_target(self) -> str | None:
        return (self.data["values"].get("duration") or {}).get("value")


# ---------------------------------------------------------------- My styles (shared presets)
def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "style"


def list_presets() -> list[dict]:
    mine = []
    if STYLES_DIR.exists():
        for f in sorted(STYLES_DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                mine.append({"id": f.stem, "name": d.get("name", f.stem), "mine": True, "saved": d.get("saved"),
                             "values": d.get("values", {})})
            except (OSError, ValueError):
                continue
    return mine + [{"id": k, "name": v["name"], "mine": False, "note": v.get("note", ""), "values": v["values"]}
                   for k, v in PRESETS.items()]


def save_preset(name: str, sheet: StyleSheet) -> dict:
    STYLES_DIR.mkdir(parents=True, exist_ok=True)
    sheet.sync_from_md()
    vals = {f: e["value"] for f, e in sheet.data["values"].items() if e.get("value")}
    f = STYLES_DIR / f"{_slug(name)}.json"
    f.write_text(json.dumps({"name": name, "saved": time.strftime("%Y-%m-%d"), "values": vals}, indent=1,
                            ensure_ascii=False), encoding="utf-8")
    return {"id": f.stem, "name": name, "fields": len(vals)}


def get_preset(pid: str) -> dict | None:
    return next((p for p in list_presets() if p["id"] == pid or p["name"].lower() == str(pid).lower()), None)
