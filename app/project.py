"""The edit: project.json schema, edit operations, undo/redo history, atomic saves, external-change detection.

All times are timeline seconds, snapped to the frame grid. Clip duration = (out - in) / speed for media,
`dur` for text. Placing or moving a clip OVERWRITES whatever was under it on that track (Premiere default).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from . import captions
from .render import voicefx
from .render.timeline import ANIMATABLE, clip_dur, has_dur, prop

# Instagram Reels (the default for new projects): 1080×1920, 9:16, 30 fps, H.264/AAC
FORMATS = {"reels": (1080, 1920), "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FORMAT_FPS = {"reels": "30/1"}                    # other presets keep the project's frame rate
DEFAULT_FORMAT = "reels"
TRACK_ORDER_KIND = {"text": 0, "video": 1, "audio": 2}

MOTION = {"x": 0.0, "y": 0.0, "scale": 1.0, "rot": 0.0, "opacity": 1.0, "fit": "fit"}
CROP = {"l": 0.0, "t": 0.0, "r": 0.0, "b": 0.0}
TEXT_STYLE = {"font": "Poppins", "weight": 700, "size": 64, "color": "#FFFFFF", "outline": 4, "outline_color": "#000000",
              "shadow": 0, "box": False, "box_color": "#000000B3", "align": "center", "spacing": 0, "line_height": 1.2}
TEXT_ANIM = {"in": "fade", "in_dur": 0.3, "out": "fade", "out_dur": 0.3}
# project-wide watermark / logo, drawn over every frame (render/timeline.py brand_motion — mirrored in evaluate.js)
BRAND_DEFAULT = {"asset": None, "enabled": False, "position": "tr", "size": 0.18, "opacity": 0.85, "margin": 0.04}
BRAND_POSITIONS = ("tl", "tr", "bl", "br", "center")


def _track(tid, kind, name, **kw):
    t = {"id": tid, "kind": kind, "name": name, "mute": False, "solo": False, "lock": False, "hidden": False,
         "volume_db": 0.0, "duck": False, "role": None, "height": "m"}
    t.update(kw)
    return t


def new_project(name="vlog") -> dict:
    return {
        "version": 1, "name": name,
        "format": {"preset": DEFAULT_FORMAT, "w": 1080, "h": 1920, "fps": FORMAT_FPS[DEFAULT_FORMAT]},
        "tracks": [_track("T2", "text", "Text 2"), _track("T1", "text", "Text 1"),
                   _track("V3", "video", "Video 3"), _track("V2", "video", "Video 2"), _track("V1", "video", "Video 1"),
                   _track("A1", "audio", "Dialogue", role="dialogue"), _track("A2", "audio", "Music", duck=True),
                   _track("A3", "audio", "SFX"), _track("A4", "audio", "Narration", role="narration")],
        "assets": {}, "clips": [], "transitions": [], "markers": [],
        "settings": {"snap": True, "normalize_lufs": -14.0, "duck_db": -12.0,
                     "brand": dict(BRAND_DEFAULT),
                     "glossary": ["E-DA Theme Park", "Kaohsiung", "Ansell", "Karina", "Fo Guang Shan", "Hsinchu", "MOTC",
                                  "Tourism Administration", "Taiwan"]},
        "next_id": 1,
    }


def deep_merge(dst: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


class OpError(ValueError):
    pass


class Editor:
    """Holds the current project + history. `asset_info(aid)` returns library metadata for an asset id."""

    MAX_HISTORY = 100

    def __init__(self, path: Path, asset_info=None):
        self.path = Path(path)
        self.asset_info = asset_info or (lambda aid: None)
        self.past: list[tuple[str, str]] = []      # (label, json snapshot)
        self.future: list[tuple[str, str]] = []
        self.last_hash = None
        self.last_autosave = 0.0
        if self.path.exists():
            self.p = self._normalize(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.p = new_project(self.path.parent.name)
            self.save()

    # ================================================================ basics
    @property
    def fps(self) -> Fraction:
        return Fraction(self.p["format"]["fps"])

    @staticmethod
    def _snap(t: float, fps: float) -> float:
        return round(round(float(t) * fps) / fps, 6)

    def q(self, t: float) -> float:
        """Snap a time to the frame grid."""
        return self._snap(t, float(self.fps))

    @property
    def half_frame(self):
        return 0.5 / float(self.fps)

    def _id(self, prefix="c"):
        n = self.p["next_id"]
        self.p["next_id"] = n + 1
        return f"{prefix}{n}"

    def clip(self, cid) -> dict:
        for c in self.p["clips"]:
            if c["id"] == cid:
                return c
        raise OpError(f"no clip {cid}")

    def track(self, tid) -> dict:
        for t in self.p["tracks"]:
            if t["id"] == tid:
                return t
        raise OpError(f"no track {tid}")

    @staticmethod
    def dur(c) -> float:
        return clip_dur(c)

    def end(self, c) -> float:
        return round(c["start"] + self.dur(c), 6)

    def on_track(self, tid):
        return sorted([c for c in self.p["clips"] if c["track"] == tid], key=lambda c: c["start"])

    def linked(self, ids) -> list[str]:
        ids = list(dict.fromkeys(ids))
        groups = {self.clip(i).get("link") for i in ids if self.clip(i).get("link")}
        for c in self.p["clips"]:
            if c.get("link") in groups and c["id"] not in ids:
                ids.append(c["id"])
        return ids

    def _locked(self, c) -> bool:
        return self.track(c["track"]).get("lock", False)

    def duration(self) -> float:
        return max([self.end(c) for c in self.p["clips"]] + [0.0])

    # ================================================================ assets
    def _asset(self, aid) -> dict:
        info = self.asset_info(aid)
        if info is None:
            snap = self.p["assets"].get(aid)
            if snap is None:
                raise OpError(f"unknown asset {aid}")
            return snap
        meta = info.get("meta") or {}
        snap = {"path": info["path"], "kind": info["kind"], "dur": meta.get("dur"), "has_audio": meta.get("has_audio", False),
                "has_video": meta.get("has_video", False), "w": meta.get("w"), "h": meta.get("h"), "fps": meta.get("fps")}
        self.p["assets"][aid] = snap
        return snap

    # ================================================================ dispatch + history
    def apply(self, op: str, args: dict | None = None, label: str | None = None):
        fn = getattr(self, "op_" + op, None)
        if fn is None:
            raise OpError(f"unknown op {op}")
        before = json.dumps(self.p)
        try:
            result = fn(**(args or {}))
            self.p = self._normalize(self.p)
        except Exception:
            self.p = json.loads(before)
            raise
        if json.dumps(self.p) != before:
            self.past.append((label or op.replace("_", " ").title(), before))
            del self.past[:-self.MAX_HISTORY]
            self.future.clear()
            self.save()
        return result

    def apply_batch(self, ops: list[tuple[str, dict]], label: str):
        """Several ops as ONE undo step (all-or-nothing)."""
        before = json.dumps(self.p)
        results = []
        try:
            for op, args in ops:
                fn = getattr(self, "op_" + op, None)
                if fn is None:
                    raise OpError(f"unknown op {op}")
                results.append(fn(**(args or {})))
                self.p = self._normalize(self.p)
        except Exception:
            self.p = json.loads(before)
            raise
        if json.dumps(self.p) != before:
            self.past.append((label, before))
            del self.past[:-self.MAX_HISTORY]
            self.future.clear()
            self.save()
        return results

    def undo(self):
        if not self.past:
            return None
        label, snap = self.past.pop()
        self.future.append((label, json.dumps(self.p)))
        self.p = json.loads(snap)
        self.save()
        return label

    def redo(self):
        if not self.future:
            return None
        label, snap = self.future.pop()
        self.past.append((label, json.dumps(self.p)))
        self.p = json.loads(snap)
        self.save()
        return label

    def history(self):
        return {"undo": self.past[-1][0] if self.past else None, "redo": self.future[-1][0] if self.future else None,
                "depth": len(self.past)}

    # ================================================================ persistence
    def save(self):
        data = json.dumps(self.p, indent=1, ensure_ascii=False).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, self.path)
        self.last_hash = hashlib.sha1(data).hexdigest()
        if time.time() - self.last_autosave > 120:
            self.autosave()

    def autosave(self):
        d = self.path.parent / "autosave"
        d.mkdir(exist_ok=True)
        (d / f"project-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(json.dumps(self.p, indent=1, ensure_ascii=False), encoding="utf-8")
        for old in sorted(d.glob("project-*.json"))[:-20]:
            old.unlink(missing_ok=True)
        self.last_autosave = time.time()

    def check_external(self) -> bool:
        """If project.json was changed by someone else (e.g. Claude), load it as an undoable step."""
        if not self.path.exists():
            return False
        data = self.path.read_bytes()
        h = hashlib.sha1(data).hexdigest()
        if h == self.last_hash:
            return False
        try:
            new = self._normalize(json.loads(data.decode("utf-8")))
        except Exception:
            return False          # half-written or invalid: ignore until it's valid
        self.past.append(("Edit from outside the app", json.dumps(self.p)))
        self.future.clear()
        self.p = new
        self.save()
        return True

    def load_snapshot(self, data: dict, label="Restore version"):
        self.past.append((label, json.dumps(self.p)))
        self.future.clear()
        self.p = self._normalize(data)
        self.save()

    # ================================================================ normalization
    def _normalize(self, p: dict) -> dict:
        base = new_project(p.get("name", "vlog"))
        for k, v in base.items():
            p.setdefault(k, copy.deepcopy(v))
        for k, v in base["settings"].items():
            p["settings"].setdefault(k, v)
        br = {**BRAND_DEFAULT, **(p["settings"].get("brand") or {})}
        br["position"] = br["position"] if br["position"] in BRAND_POSITIONS else "tr"
        br["size"] = float(min(1.0, max(0.02, br["size"])))
        br["opacity"] = float(min(1.0, max(0.0, br["opacity"])))
        br["margin"] = float(min(0.3, max(0.0, br["margin"])))
        p["settings"]["brand"] = br
        for t in p["tracks"]:
            for k, v in _track("x", "video", "x").items():
                t.setdefault(k, v)
            if t["id"] == "A1" and t.get("role") is None and t["name"] == "Dialogue":
                t["role"] = "dialogue"
        if not any(t.get("role") == "narration" for t in p["tracks"]):       # older projects: add the Narration track
            n = max([int(t["id"][1:]) for t in p["tracks"] if t["kind"] == "audio"] + [0]) + 1
            p["tracks"].append(_track(f"A{n}", "audio", "Narration", role="narration"))
        fps = float(Fraction(p["format"]["fps"]))     # never touch self.p here: callers snapshot it first
        half = 0.5 / fps
        end = lambda c: round(c["start"] + self.dur(c), 6)  # noqa: E731
        track_ids = {t["id"] for t in p["tracks"]}
        keep = []
        for c in p["clips"]:
            if c.get("track") not in track_ids:
                continue
            c.setdefault("type", "media")
            c.setdefault("speed", 1.0)
            c.setdefault("enabled", True)
            c.setdefault("link", None)
            c["motion"] = {**MOTION, **c.get("motion", {})}
            c["crop"] = {**CROP, **c.get("crop", {})}
            c.setdefault("color", {})
            c.setdefault("filters", [])
            c.setdefault("volume_db", 0.0)
            c.setdefault("fade_in", 0.0)
            c.setdefault("fade_out", 0.0)
            c["keys"] = {k: sorted(v, key=lambda x: x["t"]) for k, v in (c.get("keys") or {}).items() if v and k in ANIMATABLE}
            if c["type"] == "tts":
                c["tts"] = {**self.TTS_DEFAULT, **c.get("tts", {})}
            if c.get("voice_fx") is not None:                                 # Filter · Noise · Space · Distance · Pan
                fx = voicefx.normalize(c["voice_fx"])
                if voicefx.active(fx):
                    c["voice_fx"] = fx
                else:
                    c.pop("voice_fx", None)
            if c["type"] == "text":
                c["text"] = {"content": "", "preset": "title", "x": 0.5, "y": 0.5, "times": None, **c.get("text", {})}
                c["text"]["style"] = {**TEXT_STYLE, **c["text"].get("style", {})}
                c["text"]["anim"] = {**TEXT_ANIM, **c["text"].get("anim", {})}
                if c["text"].get("caption") is not None:
                    cap = c["text"]["caption"]
                    cap.setdefault("words", [])
                    cap.setdefault("style", {})
                    cap.setdefault("template", "karaoke_line")
            c["start"] = self._snap(max(0.0, c["start"]), fps)
            if self.dur(c) * fps >= 0.5:
                keep.append(c)
        order = {t["id"]: i for i, t in enumerate(p["tracks"])}
        keep.sort(key=lambda c: (order[c["track"]], c["start"]))
        p["clips"] = keep
        ids = {c["id"]: c for c in keep}
        good = []
        for x in p["transitions"]:
            a, b = ids.get(x.get("a")), ids.get(x.get("b"))
            if x.get("a") and not a or x.get("b") and not b or not (a or b):
                continue
            if a and b and (a["track"] != b["track"] or abs(end(a) - b["start"]) > half):
                continue
            limit = min([self.dur(c) for c in (a, b) if c])
            x["dur"] = round(min(max(x.get("dur", 0.5), 1 / fps), limit), 6)
            good.append(x)
        p["transitions"] = good
        p["markers"].sort(key=lambda m: m["t"])
        return p

    # ================================================================ overwrite helper
    def _clear(self, tid, a, b, exclude=()):
        """Make [a, b) empty on track tid: trims, splits or removes clips in the way."""
        a, b = self.q(a), self.q(b)
        for c in list(self.on_track(tid)):
            if c["id"] in exclude:
                continue
            s, e = c["start"], self.end(c)
            if e <= a + 1e-9 or s >= b - 1e-9:
                continue
            if s >= a and e <= b:                                   # fully covered → remove
                self.p["clips"].remove(c)
            elif s < a and e > b:                                   # spans → split around the hole
                right = copy.deepcopy(c)
                right["id"] = self._id()
                self._set_start_keep_end(right, b)
                self._set_end(c, a)
                right["link"] = None              # the linked partner isn't split, so the tail stands alone
                self.p["clips"].append(right)
            elif s < a:                                             # tail overlaps → trim end
                self._set_end(c, a)
            else:                                                   # head overlaps → trim start
                self._set_start_keep_end(c, b)

    def _set_end(self, c, t):
        t = self.q(t)
        if c["type"] == "tts" and c.get("tts", {}).get("fit"):
            c["tts"]["stale"] = True                           # fitted narration must be regenerated for the new length
        if has_dur(c):
            c["dur"] = round(t - c["start"], 6)
            if c["type"] == "text" and c["text"].get("caption"):
                captions.shift_words(c, 0.0, c["dur"])           # words past the new end go
        elif c.get("reverse"):                     # reversed: the clip's end shows the source's IN side
            c["in"] = round(c["out"] - (t - c["start"]) * c["speed"], 6)
        else:
            c["out"] = round(c["in"] + (t - c["start"]) * c["speed"], 6)

    def _set_start_keep_end(self, c, t):
        t = self.q(t)
        shift = t - c["start"]
        if c["type"] == "tts":                                  # trimming the head cuts into the generated audio
            c["in"] = round(max(0.0, c.get("in", 0.0) + shift), 6)
        if has_dur(c):
            c["dur"] = round(c["dur"] - shift, 6)
        elif c.get("reverse"):
            c["out"] = round(c["out"] - shift * c["speed"], 6)
        else:
            c["in"] = round(c["in"] + shift * c["speed"], 6)
        c["start"] = t
        self._shift_keys(c, -shift)
        if c["type"] == "text" and c["text"].get("caption"):
            captions.shift_words(c, -shift, c["dur"])            # words keep their timeline time

    @staticmethod
    def _shift_keys(c, dt):
        """Keyframes are relative to the clip start; keep them at the same timeline time when the start moves."""
        if not c.get("keys") or abs(dt) < 1e-9:
            return
        for path, ks in list(c["keys"].items()):
            c["keys"][path] = [{**k, "t": round(k["t"] + dt, 6)} for k in ks]

    def _place(self, clip, exclude=()):
        self._clear(clip["track"], clip["start"], self.end(clip), exclude={clip["id"], *exclude})

    # ================================================================ OPS (each is undoable)
    def op_add_media(self, asset, track=None, start=0.0, in_=0.0, out=None, audio_track="A1", link_audio=True,
                     still_dur=5.0):
        a = self._asset(asset)
        kind = a["kind"]
        if kind == "audio" or (track and self.track(track)["kind"] == "audio"):
            track = track or ("A2" if "/music/" in a["path"] else "A3" if "/sfx/" in a["path"] else "A1")
            c = self._new_media(asset, track, start, in_, out, a)
            self.p["clips"].append(c)
            self._place(c)
            return [c["id"]]
        track = track or "V1"
        if self.track(track)["kind"] != "video":
            raise OpError("pick a video track for video/images")
        if kind == "image":
            c = {"id": self._id(), "type": "media", "asset": asset, "track": track, "start": self.q(start),
                 "in": 0.0, "out": 0.0, "speed": 1.0, "still": True, "dur": float(still_dur)}
            self.p["clips"].append(c)
            self._place(c)
            return [c["id"]]
        v = self._new_media(asset, track, start, in_, out, a)
        self.p["clips"].append(v)
        self._place(v)
        ids = [v["id"]]
        if a.get("has_audio") and link_audio and audio_track:
            au = copy.deepcopy(v)
            au["id"], au["track"] = self._id(), audio_track
            lk = self._id("L")
            v["link"] = au["link"] = lk
            self.p["clips"].append(au)
            self._place(au)
            ids.append(au["id"])
        return ids

    def _new_media(self, asset, track, start, in_, out, a):
        d = a.get("dur") or 0
        in_ = max(0.0, float(in_ or 0))
        out = d if out is None else min(float(out), d) if d else float(out)
        if out - in_ <= 0:
            raise OpError("empty range")
        return {"id": self._id(), "type": "media", "asset": asset, "track": track, "start": self.q(start),
                "in": round(in_, 6), "out": round(out, 6), "speed": 1.0}

    def op_add_text(self, track="T1", start=0.0, dur=3.0, content="Your title", preset="title", style=None, anim=None,
                    x=0.5, y=0.5, times=None, meta=None):
        if self.track(track)["kind"] != "text":
            raise OpError("text goes on a text track (T1, T2...)")
        c = {"id": self._id(), "type": "text", "track": track, "start": self.q(start), "dur": float(dur),
             "text": {"content": content, "preset": preset, "x": x, "y": y, "times": times,
                      "style": {**TEXT_STYLE, **(style or {})}, "anim": {**TEXT_ANIM, **(anim or {})}}}
        if meta:
            c["meta"] = meta                       # e.g. subtitles: {"lang": "id", "original": "...", "translated": true}
        self.p["clips"].append(c)
        self._place(c)
        return [c["id"]]

    def op_move(self, ids, delta=0.0, track=None, ignore_link=False):
        group = ids if ignore_link else self.linked(ids)
        group = [i for i in group if not self._locked(self.clip(i))]
        if not group:
            return []
        delta = self.q(delta)
        min_start = min(self.clip(i)["start"] for i in group)
        delta = max(delta, -min_start)                              # never before 0
        if track:
            tk = self.track(track)["kind"]
            src_kind = self.track(self.clip(ids[0])["track"])["kind"]
            if tk != src_kind:
                raise OpError(f"can't move a {src_kind} clip onto a {tk} track")
            kinds = [t["id"] for t in self.p["tracks"] if t["kind"] == tk]
            shift = kinds.index(track) - kinds.index(self.clip(ids[0])["track"])
        for i in group:
            c = self.clip(i)
            c["start"] = self.q(c["start"] + delta)
            if track and self.track(c["track"])["kind"] == self.track(track)["kind"] and i in ids:
                kinds = [t["id"] for t in self.p["tracks"] if t["kind"] == self.track(c["track"])["kind"]]
                j = min(max(kinds.index(c["track"]) + shift, 0), len(kinds) - 1)
                c["track"] = kinds[j]
        for i in group:
            self._place(self.clip(i), exclude=group)
        # transitions to clips that moved away are dropped by _normalize
        return group

    def op_trim(self, id, edge, t, ripple=False, ignore_link=False):
        c = self.clip(id)
        if self._locked(c):
            raise OpError("track is locked")
        group = [id] if ignore_link else self.linked([id])
        t = self.q(t)
        old_s, old_e = c["start"], self.end(c)
        one = 1 / float(self.fps)
        for i in group:
            g = self.clip(i)
            if abs(g["start"] - old_s) > self.half_frame and edge == "start" or abs(self.end(g) - old_e) > self.half_frame and edge == "end":
                continue                                            # partner not aligned on this edge
            a = self.p["assets"].get(g.get("asset"), {})
            src_dur = a.get("dur") if g["type"] == "media" and not has_dur(g) else None
            rev = bool(g.get("reverse"))
            if edge == "start":
                nt = min(t, self.end(g) - one)
                if src_dur is not None:                              # media available before the head
                    room = (src_dur - g["out"]) if rev else g["in"]
                    nt = max(nt, g["start"] - room / g["speed"])
                nt = max(0.0, nt)
                if ripple:
                    shift = nt - g["start"]                          # trim head, keep position, pull the rest
                    self._set_start_keep_end(g, nt)
                    g["start"] = old_s
                    self._shift_after(g["track"], old_e, -shift, exclude={g["id"]})
                else:
                    self._set_start_keep_end(g, nt)
                    self._place(g)
            else:
                nt = max(t, g["start"] + one)
                if src_dur is not None:                              # media available after the tail
                    nt = min(nt, g["start"] + (g["out"] if rev else (src_dur - g["in"])) / g["speed"])
                delta = nt - self.end(g)
                if ripple:
                    self._shift_after(g["track"], old_e, delta, exclude={g["id"]})
                    self._set_end(g, nt)
                else:
                    self._set_end(g, nt)
                    self._place(g)
        return group

    def _shift_after(self, tid, t, delta, exclude=()):
        for c in self.on_track(tid):
            if c["id"] not in exclude and c["start"] >= t - self.half_frame:
                c["start"] = self.q(max(0.0, c["start"] + delta))

    def op_split(self, t, ids=None):
        t = self.q(t)
        targets = [c for c in self.p["clips"] if c["start"] + self.half_frame < t < self.end(c) - self.half_frame
                   and not self._locked(c)]
        if ids:
            allow = set(self.linked(ids))
            targets = [c for c in targets if c["id"] in allow]
        new_links, made = {}, []
        for c in targets:
            right = copy.deepcopy(c)
            right["id"] = self._id()
            self._set_start_keep_end(right, t)
            self._set_end(c, t)
            c["fade_out"], right["fade_in"] = 0.0, 0.0
            if c.get("link"):
                new_links.setdefault(c["link"], self._id("L"))
                right["link"] = new_links[c["link"]]
            if c["type"] == "text" and c["text"].get("times"):
                off = t - c["start"]
                right["text"]["times"] = [max(0.0, x - off) for x in c["text"]["times"]]
            for x in self.p["transitions"]:
                if x.get("a") == c["id"]:
                    x["a"] = right["id"]
            self.p["clips"].append(right)
            made.append(right["id"])
        return made

    def op_delete(self, ids, ripple=False, ignore_link=False):
        group = ids if ignore_link else self.linked(ids)
        removed = []
        for i in group:
            c = self.clip(i)
            if self._locked(c):
                continue
            removed.append((c["track"], c["start"], self.end(c)))
            self.p["clips"].remove(c)
        if ripple:
            for tid, s, e in sorted(removed, key=lambda r: -r[1]):
                self._shift_after(tid, e, -(e - s))
        return [r for r in group]

    def op_update(self, ids, patch, ripple_speed=True):
        ids = [ids] if isinstance(ids, str) else ids
        for i in ids:
            c = self.clip(i)
            old_end = self.end(c)
            p = copy.deepcopy(patch)
            if "speed" in p:
                sp = float(p.pop("speed"))
                if not (0.1 <= sp <= 16):
                    raise OpError("speed must be 10%..1600%")
                c["speed"] = sp
            if "text" in p and c["type"] != "text":
                p.pop("text")
            if c["type"] == "text" and c["text"].get("caption") and "content" in p.get("text", {}) \
                    and "words" not in (p["text"].get("caption") or {}):
                # edited caption text: keep the word timing, '*word*' marks emphasis
                ws = captions.retime(c["text"]["caption"]["words"], p["text"]["content"], self.dur(c))
                c["text"]["caption"]["words"] = ws
                p["text"]["content"] = captions.content_of(ws)
                c.setdefault("meta", {})["edited"] = True
            if c["type"] == "tts" and "tts" in p and any(k in p["tts"] for k in self.TTS_INPUTS) and "file" not in p["tts"]:
                p["tts"]["stale"] = True                       # inputs changed → needs regenerating
            deep_merge(c, p)
            if ripple_speed and abs(self.end(c) - old_end) > 1e-6:
                self._shift_after(c["track"], old_end, self.end(c) - old_end, exclude={c["id"]})
        return ids

    # ---------------------------------------------------------------- properties & keyframes
    @staticmethod
    def _set_path(c, path, v):
        ks = path.split(".")
        o = c
        for k in ks[:-1]:
            o = o.setdefault(k, {})
        o[ks[-1]] = v

    def op_set_props(self, ids, values: dict, t=None):
        """Set properties; animated ones (with keyframes) get a key at timeline time t instead (auto-key)."""
        ids = [ids] if isinstance(ids, str) else ids
        for i in ids:
            c = self.clip(i)
            for path, v in values.items():
                ks = (c.get("keys") or {}).get(path)
                if ks and t is not None:
                    self._put_key(c, path, t, float(v))
                else:
                    self._set_path(c, path, v)
        return ids

    def _put_key(self, c, path, t, v, e=None):
        rel = round(self.q(t) - c["start"], 6)
        ks = c.setdefault("keys", {}).setdefault(path, [])
        hit = next((k for k in ks if abs(k["t"] - rel) <= self.half_frame), None)
        if hit:
            hit["v"] = v
            if e:
                hit["e"] = e
        else:
            ks.append({"t": rel, "v": v, "e": e or "ease"})
            ks.sort(key=lambda k: k["t"])

    def op_toggle_anim(self, id, path, t):
        """Stopwatch: start animating `path` (first key = current value at t) or stop (keep the value at t)."""
        if path not in ANIMATABLE:
            raise OpError(f"{path} can't be animated")
        c = self.clip(id)
        cur = prop(c, path, t)
        if (c.get("keys") or {}).get(path):
            c["keys"].pop(path)
            self._set_path(c, path, cur)
        else:
            self._put_key(c, path, t, float(cur if cur is not None else 0.0))
        return [id]

    def op_set_key(self, id, path, t, v=None, e=None):
        if path not in ANIMATABLE:
            raise OpError(f"{path} can't be animated")
        c = self.clip(id)
        self._put_key(c, path, t, float(prop(c, path, t) if v is None else v), e)
        return [id]

    def op_remove_key(self, id, path, t):
        c = self.clip(id)
        rel = self.q(t) - c["start"]
        ks = (c.get("keys") or {}).get(path, [])
        ks[:] = [k for k in ks if abs(k["t"] - rel) > self.half_frame]
        if not ks:
            c["keys"].pop(path, None)
        return [id]

    # ---------------------------------------------------------------- time tools
    def _clip_under(self, t, kinds=("video",)):
        order = {tr["id"]: i for i, tr in enumerate(self.p["tracks"])}
        cands = [c for c in self.p["clips"] if self.track(c["track"])["kind"] in kinds and not self._locked(c)
                 and c["start"] - self.half_frame <= t < self.end(c) - self.half_frame]
        return min(cands, key=lambda c: order[c["track"]]) if cands else None    # topmost track wins

    def op_freeze_frame(self, t, id=None, dur=2.0, mode="insert"):
        """insert: split at t and insert a `dur`-second hold of that frame, pushing the rest later (video + its audio);
        rest: hold the frame at t for the remainder of the clip (Premiere 'Add Frame Hold')."""
        t = self.q(t)
        c = self.clip(id) if id else self._clip_under(t)
        if not c or c["type"] != "media" or c.get("still") or self.track(c["track"])["kind"] != "video":
            raise OpError("put the playhead over a video clip (or select one) to freeze a frame")
        a = self.p["assets"].get(c["asset"], {})
        from .render.timeline import src_time
        hold = round(src_time(c, t, a.get("fps") or 30.0), 6)
        if mode == "rest":
            if t <= c["start"] + self.half_frame:
                target = c
            else:
                made = self.op_split(t, ids=[c["id"]])
                target = next(self.clip(i) for i in made if self.clip(i)["track"] == c["track"])
            d = self.dur(target)
            target.update(hold=hold, dur=round(d, 6), link=None, keys={}, fade_in=0.0)
            return [target["id"]]
        dur = self.q(float(dur))
        tracks = {c["track"]} | {k["track"] for k in self.p["clips"] if c.get("link") and k.get("link") == c["link"]}
        if c["start"] + self.half_frame < t < self.end(c) - self.half_frame:
            self.op_split(t, ids=[c["id"]])
        for tid in tracks:
            self._shift_after(tid, t, dur)
        fz = copy.deepcopy(c)
        fz.update(id=self._id(), start=t, hold=hold, dur=dur, link=None, keys={}, fade_in=0.0, fade_out=0.0)
        self.p["clips"].append(fz)
        return [fz["id"]]

    def op_set_speed(self, ids, speed=None, duration=None, reverse=None, keep_pitch=None, blend=None, ripple=True):
        ids = [ids] if isinstance(ids, str) else ids
        group = self.linked(ids)
        targets = [self.clip(i) for i in group if self.clip(i)["type"] == "media" and not has_dur(self.clip(i))]
        if not targets:
            raise OpError("select a video or audio clip (freeze frames and stills have no speed)")
        for c in targets:
            old_end = self.end(c)
            if duration is not None:
                sp = (c["out"] - c["in"]) / max(float(duration), 1 / float(self.fps))
            else:
                sp = float(speed) if speed is not None else c.get("speed", 1.0)
            if not (0.1 <= sp <= 16):
                raise OpError("speed must be between 10% and 1600%")
            old_d = self.dur(c)
            c["speed"] = round(sp, 6)
            if reverse is not None:
                c["reverse"] = bool(reverse)
            if keep_pitch is not None:
                c["keep_pitch"] = bool(keep_pitch)
            if blend is not None:
                c["blend"] = bool(blend)
            k = self.dur(c) / max(old_d, 1e-9)                       # keep keyframes proportional to the clip
            if c.get("keys") and abs(k - 1) > 1e-6:
                c["keys"] = {p: [{**x, "t": round(x["t"] * k, 6)} for x in ks] for p, ks in c["keys"].items()}
            if ripple and abs(self.end(c) - old_end) > 1e-6:
                self._shift_after(c["track"], old_end, self.end(c) - old_end, exclude={x["id"] for x in targets})
            elif not ripple:
                self._place(c, exclude={x["id"] for x in targets})
        return [c["id"] for c in targets]

    TTS_DEFAULT = {"text": "", "voice": None, "tone": "neutral", "intensity": 0.5, "pace": 1.0, "fit": True,
                   "caption": False, "provider": "local", "file": None, "stale": True,
                   "rate": None, "pause": 1.0, "steady": True, "take": 0,     # steady pacing (app/tts/pacing.py)
                   "segs": None, "base": None, "layout": None,                # sentence timing (app/tts/layout.py)
                   "mode": None, "model": None, "ctx_prev": None, "words": None}   # mode "dialogue" = Eleven v4 conversation
    TTS_INPUTS = ("text", "voice", "tone", "intensity", "pace", "fit", "provider", "rate", "pause", "steady", "take", "mode", "model")

    def op_add_tts(self, start=0.0, dur=4.0, text="", voice=None, tone="neutral", intensity=0.5, pace=1.0, fit=True,
                   caption=False, track=None, extra=None, asset=None):
        """AI narration clip on the Narration track (generated audio is attached later by the voice engine).
        extra: more tts fields (an already generated line: file, base, segs, rate, pause …); asset: its registered id."""
        track = track or self.ensure_track("narration")
        if self.track(track)["kind"] != "audio":
            raise OpError("narration goes on an audio track")
        c = {"id": self._id(), "type": "tts", "track": track, "start": self.q(start), "dur": float(dur),
             "tts": {**self.TTS_DEFAULT, "text": text, "voice": voice, "tone": tone, "intensity": intensity, "pace": pace,
                     "fit": fit, "caption": caption, **{k: copy.deepcopy(v) for k, v in (extra or {}).items() if k in self.TTS_DEFAULT
                                                         or k in ("wpm", "pieces", "limited", "match", "fitted")}}}
        if asset:
            c["asset"], c["in"] = asset, 0.0
        self.p["clips"].append(c)
        self._place(c)
        return [c["id"]]

    def op_tts_layout(self, id, layout=None, file=None, asset=None, start=None, dur=None, in_=None):
        """Sentence timing of a narration clip (see app/tts/layout.py). file/asset = the composed audio (made by the
        server); start/dur/in_ = the clip moved/extended so every sentence stays where it was placed."""
        c = self.clip(id)
        if c["type"] != "tts" or not (c.get("tts") or {}).get("segs"):
            raise OpError("this narration has no sentence timing — regenerate it with Steady pace on")
        tt = c["tts"]
        tt["layout"] = copy.deepcopy(layout)
        if file:
            tt["file"] = file
        if asset:
            c["asset"] = asset
        if start is not None:
            c["start"] = self.q(max(0.0, float(start)))
        if in_ is not None:
            c["in"] = max(0.0, round(float(in_), 6))
        if dur is not None:
            c["dur"] = max(1 / float(self.fps), round(float(dur), 6))
        if tt.get("caption"):
            self.op_narration_captions(id)
        return [id]

    def op_narration_captions(self, id):
        """On-screen captions for a narration, word-timed from where each sentence actually plays (so they follow when
        sentences move). Replaces the narration's previous captions, keeping their template, position and track."""
        from .tts.layout import timeline_spans
        from .tts.pacing import syllables
        c = self.clip(id)
        old = [k for k in self.p["clips"] if k["type"] == "text" and (k.get("meta") or {}).get("narration") == id]
        legacy = (c.get("tts") or {}).get("caption_id")
        legacy = next((k for k in self.p["clips"] if k["id"] == legacy and not (k.get("meta") or {}).get("narration")), None)
        first = old[0] if old else None
        track = first["track"] if first else (legacy["track"] if legacy else next((t["id"] for t in self.p["tracks"] if t["kind"] == "text"), None))
        for k in old + ([legacy] if legacy else []):
            self.p["clips"].remove(k)
        if not track or not c["tts"].get("caption"):
            return []
        words = []
        spans = timeline_spans(c) or [{"text": c["tts"].get("text") or "", "t0": c["start"], "t1": self.end(c)}]   # classic mode: no sentence map
        real = c["tts"].get("words")
        if real and not c["tts"].get("layout"):         # real word times from the voice engine (dialogue mode)
            origin = c["start"] - (c.get("in") or 0.0)
            words = [{"w": w["w"], "t0": origin + w["t0"], "t1": origin + w["t1"]} for w in real]
            spans = []
        for sp in spans:
            toks = sp["text"].split()
            wts = [max(1, syllables(t)) for t in toks]
            tot, acc = float(sum(wts)) or 1.0, 0.0
            for t, wt in zip(toks, wts):
                a = sp["t0"] + (sp["t1"] - sp["t0"]) * acc / tot
                acc += wt
                words.append({"w": t, "t0": a, "t1": sp["t0"] + (sp["t1"] - sp["t0"]) * acc / tot})
        lo, hi = c["start"], self.end(c)
        words = [w for w in words if w["t1"] > lo and w["t0"] < hi]
        if not words:
            return []
        tpl = captions.template(first["text"]["caption"].get("template") if first else None)
        made = []
        lines = captions.chunk_words(words, int(tpl.get("max_words", 5)), int(tpl.get("max_chars", 28)))
        for n, ln in enumerate(lines):
            s = self.q(max(lo, ln[0]["t0"]))
            e = lines[n + 1][0]["t0"] if n + 1 < len(lines) else ln[-1]["t1"] + 0.25
            e = min(max(e if e - ln[-1]["t1"] < 0.8 else ln[-1]["t1"] + 0.3, s + 0.3), hi + 0.25)
            ws = [{"w": w["w"], "t0": round(max(0.0, w["t0"] - s), 3), "t1": round(w["t1"] - s, 3)} for w in ln]
            if first:
                k = copy.deepcopy(first)
                k["text"]["caption"]["words"] = ws
                k["text"]["content"] = captions.content_of(ws)
            else:
                k = {"type": "text", "track": track,
                     "text": {**captions.caption_text(ws, tpl), "style": dict(TEXT_STYLE), "times": None}}
            k.update(id=self._id(), start=s, dur=round(e - s, 6), meta={"narration": id})
            self.p["clips"].append(k)
            made.append(k["id"])
        c["tts"]["caption_id"] = None
        return made

    def ensure_track(self, role="narration"):
        for t in self.p["tracks"]:
            if t.get("role") == role:
                return t["id"]
        tid = self.op_add_track("audio")[0]
        self.op_set_track(tid, {"name": "Narration", "role": "narration"})
        return tid

    def op_apply_anim_preset(self, ids, name):
        W = self.p["format"]["w"]
        ids = [ids] if isinstance(ids, str) else ids
        for i in ids:
            c = self.clip(i)
            D = self.dur(c)
            keys = c.setdefault("keys", {})
            txt = c["type"] == "text"
            xk = "text.x" if txt else "motion.x"
            x0 = c["text"]["x"] if txt else c["motion"].get("x", 0)
            off = 1.0 if txt else W                       # text.x is a fraction of the width
            k = lambda *pts, e="ease": [{"t": round(min(t, D), 6), "v": v, "e": e} for t, v in pts]  # noqa: E731
            if name == "clear":
                c["keys"] = {}
            elif name == "ken_burns_in":
                keys["motion.scale"] = k((0, 1.0), (D, 1.15), e="linear")
            elif name == "ken_burns_out":
                keys["motion.scale"] = k((0, 1.15), (D, 1.0), e="linear")
            elif name == "zoom_punch":
                keys["motion.scale"] = k((0, 1.0), (0.15, 1.12), (0.45, 1.0))
            elif name in ("slide_in_left", "slide_in_right"):
                sign = -1 if name.endswith("left") else 1
                keys[xk] = k((0, x0 + sign * off), (0.5, x0), e="ease_out")
            elif name == "pop_in":
                keys["motion.scale"] = k((0, 0.6), (0.25, 1.05), (0.4, 1.0))
                keys["motion.opacity"] = k((0, 0.0), (0.15, 1.0))
            elif name == "fade_in_out":
                keys["motion.opacity"] = k((0, 0.0), (0.5, 1.0), (max(0.5, D - 0.5), 1.0), (D, 0.0))
            else:
                raise OpError(f"unknown animation preset {name}")
        return ids

    # ---------------------------------------------------------------- captions (word-timed, templated)
    def op_add_captions(self, captions_, template=None, track="T1", y=None, replace=None, unclear=None):
        """captions_: [{start, end, words:[{w, t0, t1, conf?}] (relative), lang, translated, original, review}] (absolute
        start/end). replace: [a, b] timeline range whose existing caption clips on `track` are removed first.
        unclear: [{start, end, lang}] spans with speech but no words → red review markers."""
        if self.track(track)["kind"] != "text":
            raise OpError("captions go on a text track")
        tpl = captions.template(template)
        if replace:
            a, b = replace
            for c in list(self.on_track(track)):
                if c["type"] == "text" and c["text"].get("caption") is not None and c["start"] < b and self.end(c) > a:
                    self.p["clips"].remove(c)
            self.p["markers"] = [m for m in self.p["markers"] if not (m.get("kind") == "unclear" and a <= m["t"] < b)]
        made = []
        for cap in captions_:
            words = [dict(w) for w in cap["words"] if w.get("w")]
            if not words:
                continue
            start = self.q(cap["start"])
            shift = cap["start"] - start
            for w in words:
                w["t0"], w["t1"] = round(w["t0"] + shift, 3), round(w["t1"] + shift, 3)
            dur = max(1 / float(self.fps), round(cap["end"] - start, 6))
            captions.auto_emphasis(words, self.p["settings"].get("glossary"))
            c = {"id": self._id(), "type": "text", "track": track, "start": start, "dur": dur,
                 "text": {**captions.caption_text(words, tpl, y=y, group=cap.get("group")),
                          "style": dict(TEXT_STYLE), "times": None}}
            meta = {k: cap[k] for k in ("lang", "translated", "original") if k in cap}
            meta["subtitle"] = True
            if cap.get("review"):
                meta["review"] = cap["review"]
            c["meta"] = meta
            self.p["clips"].append(c)
            self._place(c)
            made.append(c["id"])
        for u in unclear or []:
            self.p["markers"].append({"id": self._id("m"), "t": self.q(u["start"]), "label": "Unclear speech — please check",
                                      "color": "red", "kind": "unclear", "dur": round(u["end"] - u["start"], 3)})
        return made

    def _caption_ids(self, ids):
        if ids in (None, "all"):
            return [c["id"] for c in self.p["clips"] if c["type"] == "text" and c["text"].get("caption") is not None]
        ids = [ids] if isinstance(ids, str) else ids
        return [i for i in ids if self.clip(i)["type"] == "text"]

    def op_restyle_captions(self, ids=None, template=None, overrides=None, keep_position=True, keep_overrides=False):
        """Apply a caption template (and/or style overrides) to captions. Plain text clips become captions too
        (their words are spread over the clip). ids=None/'all' = every caption."""
        out = []
        for i in self._caption_ids(ids):
            c = self.clip(i)
            tx = c["text"]
            cap = tx.get("caption")
            if template:
                tpl = captions.template(template)
                words = cap["words"] if cap else captions.retime([], tx["content"].replace("\n", " "), self.dur(c))
                old = (cap or {}).get("style", {}) if keep_overrides else {}
                y = tx["y"] if (keep_position and cap) else None
                new = captions.caption_text(words, tpl, x=tx["x"] if keep_position and cap else 0.5, y=y,
                                            group=(cap or {}).get("group"))
                new["caption"]["style"].update({k: v for k, v in old.items() if k in ("color", "size")})
                tx.update(new)
                c.setdefault("meta", {})["subtitle"] = True
            if overrides and tx.get("caption"):
                deep_merge(tx["caption"]["style"], copy.deepcopy(overrides))
            out.append(i)
        return out

    def op_rechunk_captions(self, ids=None, max_words=5, max_chars=28):
        """Re-split captions into lines of a new size (words keep their timing). Captions are regrouped per
        consecutive run on one track with the same language and no gap > 0.6 s."""
        sel = sorted((self.clip(i) for i in self._caption_ids(ids) if self.clip(i)["text"].get("caption")),
                     key=lambda c: (c["track"], c["start"]))
        runs, cur = [], []
        for c in sel:
            if cur and (c["track"] != cur[-1]["track"] or c["start"] - self.end(cur[-1]) > 0.6
                        or (c.get("meta") or {}).get("lang") != (cur[-1].get("meta") or {}).get("lang")):
                runs.append(cur)
                cur = []
            cur.append(c)
        if cur:
            runs.append(cur)
        made = []
        for run in runs:
            first = run[0]
            translated = (first.get("meta") or {}).get("translated")
            words = []
            for c in run:
                for w in c["text"]["caption"]["words"]:
                    words.append({**w, "w": w["w"].strip("()") if translated else w["w"], "t0": c["start"] + w["t0"], "t1": c["start"] + w["t1"]})
            end = self.end(run[-1])
            reviews = [r for c in run for r in (c.get("meta") or {}).get("review", [])]
            for c in run:
                self.p["clips"].remove(c)
            lines = captions.chunk_words(words, int(max_words), int(max_chars))
            for n, ln in enumerate(lines):
                if translated:
                    ln[0] = {**ln[0], "w": "(" + ln[0]["w"]}
                    ln[-1] = {**ln[-1], "w": ln[-1]["w"] + ")"}
                s = self.q(ln[0]["t0"])
                e = lines[n + 1][0]["t0"] if n + 1 < len(lines) else end
                e = max(e if e - ln[-1]["t1"] < 0.8 else ln[-1]["t1"] + 0.3, s + 0.3)
                c = copy.deepcopy(first)
                c["id"], c["start"], c["dur"] = self._id(), s, round(e - s, 6)
                ws = [{**w, "t0": round(w["t0"] - s, 3), "t1": round(w["t1"] - s, 3)} for w in ln]
                c["text"]["caption"]["words"] = ws
                c["text"]["content"] = captions.content_of(ws)
                low = [w["w"] for w in ws if w.get("conf", 1) < 0.4]
                c["meta"] = {k: v for k, v in (first.get("meta") or {}).items() if k not in ("review", "review_ok")}
                other = [r for r in reviews if not r.startswith("unclear")][:1]     # misheard / translation unsure
                if low or other:
                    c["meta"]["review"] = (["unclear: " + ", ".join(low[:6])] if low and not other else []) + other
                self.p["clips"].append(c)
                self._place(c)
                made.append(c["id"])
        return made

    def op_set_review(self, ids, ok=True):
        """Mark captions as checked (removes them from the review list) or back to 'needs check'."""
        ids = [ids] if isinstance(ids, str) else ids
        for i in ids:
            if i.startswith("m"):
                self.p["markers"] = [m for m in self.p["markers"] if not (m["id"] == i and ok)]
                continue
            self.clip(i).setdefault("meta", {})["review_ok"] = bool(ok)
        return ids

    def op_add_transition(self, type, a=None, b=None, dur=0.6, track=None, t=None, params=None):
        if track is not None and t is not None:
            t = self.q(t)
            a = a or next((c["id"] for c in self.on_track(track) if abs(self.end(c) - t) <= self.half_frame), None)
            b = b or next((c["id"] for c in self.on_track(track) if abs(c["start"] - t) <= self.half_frame), None)
        if not a and not b:
            raise OpError("no clip edge there")
        if self.track(self.clip(a or b)["track"])["kind"] == "audio":
            raise OpError("transitions go on video/text tracks; use fades for audio")
        self.p["transitions"] = [x for x in self.p["transitions"] if not ((a and x.get("a") == a and (x.get("b") or None) == (b or None))
                                                                          or (b and x.get("b") == b and (x.get("a") or None) == (a or None)))]
        x = {"id": self._id("x"), "type": type, "a": a, "b": b, "dur": float(dur), "params": params or {}}
        self.p["transitions"].append(x)
        return [x["id"]]

    def op_apply_voice_fx(self, fx=None, ids=None, track=None, role=None):
        """Set voice effects on audio clips: ids, or every clip on a track, or on all tracks with a role
        ("narration" / "dialogue"). fx=None clears them."""
        tracks = {t["id"]: t for t in self.p["tracks"]}
        if track:
            ids = [c["id"] for c in self.on_track(track)]
        elif role:
            ids = [c["id"] for c in self.p["clips"] if tracks[c["track"]].get("role") == role]
        ids = [ids] if isinstance(ids, str) else (ids or [])
        out = []
        norm = voicefx.normalize(fx) if fx else None
        for i in ids:
            c = self.clip(i)
            if tracks[c["track"]]["kind"] != "audio" or c["type"] not in ("media", "tts"):
                continue
            if norm and voicefx.active(norm):
                c["voice_fx"] = copy.deepcopy(norm)
            else:
                c.pop("voice_fx", None)
            out.append(i)
        if not out:
            raise OpError("pick audio clips (narration, dialogue, music) for voice effects")
        return out

    def op_apply_look(self, ids=None, look=None, track=None):
        """Apply a look preset (color + LUT + filters, replacing the clip's current grade) to clips, or every clip on a
        track. Looks come from presets.json "looks" or the user's saved looks (presets/user_presets.json)."""
        from .render.gl import load_presets
        looks = {x["id"]: x for x in load_presets().get("looks", []) + captions.user_presets().get("looks", [])}
        if look not in looks:
            raise OpError(f"unknown look {look}")
        lk = looks[look]
        if track:
            ids = [c["id"] for c in self.on_track(track) if c["type"] == "media"]
        ids = [ids] if isinstance(ids, str) else (ids or [])
        out = []
        for i in ids:
            c = self.clip(i)
            if c["type"] != "media" or self.track(c["track"])["kind"] != "video":
                continue
            c["color"] = copy.deepcopy(lk.get("color", {}))
            c["filters"] = copy.deepcopy(lk.get("filters", []))
            c.setdefault("meta", {})["look"] = look
            out.append(i)
        if not out:
            raise OpError("select video clips for the look")
        return out

    def op_apply_transition_pack(self, pack, track="V1", ids=None, dur=None, items=None):
        """Put a transition on every cut (clip end touching the next clip's start) of a track — or only between the
        selected clips — cycling through the pack's transitions so they vary. Replaces transitions already on those cuts."""
        if items is None:
            from .render.gl import load_presets
            packs = {p["id"]: p for p in load_presets().get("transition_packs", [])}
            if pack not in packs:
                raise OpError(f"unknown transition pack {pack}")
            items, dur = packs[pack]["items"], dur or packs[pack]["dur"]
        dur = float(dur or 0.6)
        if ids:
            sel = [self.clip(i) for i in ids]
            tracks = {c["track"] for c in sel}
            clips = sorted((c for c in sel if self.track(c["track"])["kind"] != "audio"), key=lambda c: (c["track"], c["start"]))
        else:
            tracks = {track}
            clips = sorted(self.on_track(track), key=lambda c: c["start"])
        cuts = [(a, b) for a, b in zip(clips, clips[1:]) if a["track"] == b["track"] and abs(self.end(a) - b["start"]) <= self.half_frame]
        if not cuts:
            raise OpError("no cuts there — clips must touch (end of one = start of the next)" + ("" if ids else f" on {track}"))
        made = []
        for n, (a, b) in enumerate(cuts):
            self.p["transitions"] = [x for x in self.p["transitions"] if not (x.get("a") == a["id"] and x.get("b") == b["id"])]
            x = {"id": self._id("x"), "type": items[n % len(items)], "a": a["id"], "b": b["id"], "dur": dur, "params": {}}
            self.p["transitions"].append(x)
            made.append(x["id"])
        return made

    def op_update_transition(self, id, patch):
        for x in self.p["transitions"]:
            if x["id"] == id:
                deep_merge(x, patch)
                return [id]
        raise OpError(f"no transition {id}")

    def op_remove_transition(self, id):
        self.p["transitions"] = [x for x in self.p["transitions"] if x["id"] != id]
        return [id]

    def op_unlink(self, ids):
        for i in self.linked(ids):
            self.clip(i)["link"] = None
        return ids

    def op_link(self, ids):
        lk = self._id("L")
        for i in ids:
            self.clip(i)["link"] = lk
        return ids

    def op_add_marker(self, t, label="", color="amber"):
        m = {"id": self._id("m"), "t": self.q(t), "label": label, "color": color}
        self.p["markers"].append(m)
        return [m["id"]]

    def op_update_marker(self, id, patch):
        for m in self.p["markers"]:
            if m["id"] == id:
                deep_merge(m, patch)
                return [id]
        raise OpError(f"no marker {id}")

    def op_remove_marker(self, id):
        self.p["markers"] = [m for m in self.p["markers"] if m["id"] != id]
        return [id]

    def op_set_track(self, id, patch):
        deep_merge(self.track(id), patch)
        return [id]

    def op_add_track(self, kind):
        same = [t for t in self.p["tracks"] if t["kind"] == kind]
        prefix = {"video": "V", "audio": "A", "text": "T"}[kind]
        n = max([int(t["id"][1:]) for t in same] + [0]) + 1
        t = _track(f"{prefix}{n}", kind, {"video": "Video", "audio": "Audio", "text": "Text"}[kind] + f" {n}")
        if kind == "audio":
            idx = max(i for i, x in enumerate(self.p["tracks"]) if x["kind"] == "audio") + 1
        else:  # new video/text tracks stack above the existing ones of that kind
            idx = min(i for i, x in enumerate(self.p["tracks"]) if x["kind"] == kind)
        self.p["tracks"].insert(idx, t)
        return [t["id"]]

    def op_remove_track(self, id):
        if any(c["track"] == id for c in self.p["clips"]):
            raise OpError("track isn't empty")
        self.p["tracks"] = [t for t in self.p["tracks"] if t["id"] != id]
        return [id]

    def op_set_format(self, preset):
        if preset not in FORMATS:
            raise OpError(f"format must be one of {list(FORMATS)}")
        w, h = FORMATS[preset]
        self.p["format"].update(preset=preset, w=w, h=h)
        if preset in FORMAT_FPS and self.p["format"].get("fps") != FORMAT_FPS[preset]:
            self.p["format"]["fps"] = FORMAT_FPS[preset]
            fps = float(Fraction(FORMAT_FPS[preset]))
            for c in self.p["clips"]:                  # keep every clip on the new frame grid
                c["start"] = self._snap(c["start"], fps)
        return [preset]

    def op_set_brand(self, **patch):
        """Watermark / logo over the whole video: {asset, enabled, position, size, opacity, margin}."""
        br = self.p["settings"].setdefault("brand", dict(BRAND_DEFAULT))
        if patch.get("asset"):
            a = self._asset(patch["asset"])               # registers it in the project (exports need it)
            if a["kind"] != "image":
                raise OpError("pick an image (transparent PNG works best) for the watermark")
            patch.setdefault("enabled", True)
        br.update({k: v for k, v in patch.items() if k in BRAND_DEFAULT})
        return []

    def op_set_settings(self, patch):
        deep_merge(self.p["settings"], patch)
        return []

    def op_paste(self, clips, t, track_offset=0):
        if not clips:
            return []
        t = self.q(t)
        base = min(c["start"] for c in clips)
        links, made = {}, []
        for src in clips:
            c = copy.deepcopy(src)
            c["id"] = self._id()
            c["start"] = self.q(t + (src["start"] - base))
            if src.get("link"):
                links.setdefault(src["link"], self._id("L"))
                c["link"] = links[src["link"]]
            self.track(c["track"])
            if c.get("asset") and c["asset"] not in self.p["assets"]:
                self._asset(c["asset"])
            self.p["clips"].append(c)
            made.append(c)
        for c in made:
            self._place(c)
        return [c["id"] for c in made]

    def op_close_gap(self, track, t):
        """Ripple-delete the empty gap at time t on a track."""
        t = self.q(t)
        clips = self.on_track(track)
        prev_end = max([self.end(c) for c in clips if self.end(c) <= t + self.half_frame] + [0.0])
        nxt = [c for c in clips if c["start"] >= t - self.half_frame]
        if not nxt:
            return []
        gap = nxt[0]["start"] - prev_end
        if gap <= 0:
            return []
        self._shift_after(track, nxt[0]["start"], -gap)
        return [c["id"] for c in nxt]
