"""Edit builder for "Having Fun in Taiwan": turns an edit decision list (edl.py) into editor ops on the LIVE timeline
(the user watches it happen in the editor). Narration lines come from docs/edit/narration.json (already generated →
placed with /api/tts/place, no regeneration). Beat lengths follow the real narration; cuts snap to the music's beats.

Tracks: V1 main / split bottom / blurred background · V2 split top / fit foreground · V3 logo strip · V4 big logo
        T1 captions + typed text line 1 · T2 overlays + typed line 2 · A1 natural sound · A2 music · A3 SFX
        A4 narration · A5 narration (second voice for lines spoken together)
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import api
from .. import claude_progress as cp

ROOT = Path(__file__).resolve().parents[2]
EDIT = ROOT / "projects" / "Having Fun in Taiwan" / "docs" / "edit"
FPS = 30.0
W, H = 1080, 1920
FOOTAGE_DB = -10.46   # user (2026-11-07): footage's own sound at 30% volume so it never covers the narration
BREATHE = 1.5      # user (2026-11-06): fast viral pace, but let each shot play 1–2 s after the voice; scenery 3–4 s
COLORS = {"Karina": "#FF5FB0", "Ansell": "#38B6FF"}


# ---------------------------------------------------------------- EDL vocabulary
@dataclass
class S:                       # one shot
    clip: str                  # file name without extension is fine ("Scene 3_9_2")
    a: float = 0.0             # source in (s)
    d: float | None = None     # fixed duration on the timeline (None = share of the beat)
    mode: str = "fill"         # fill (crop to 9:16) | native (vertical clip) | blur (fit + blurred background)
    x: float = 0.0             # horizontal offset in frame px for fill crops (− = show more of the right side)
    speed: float = 1.0
    db: float = -14.0          # natural sound level
    w: float = 1.0             # weight when sharing the beat
    night: bool = False
    zoom: float = 1.0          # extra scale
    keep_sound: bool = False   # keep the footage's own sound at full level (default: 30%, user's rule)
    crop: dict | None = None   # {l,t,r,b} fractions — e.g. black bars baked into the file


@dataclass
class Beat:
    shots: list
    lines: list = field(default_factory=list)    # narration line ids in order
    min: float = 0.0
    lead: float = 0.25
    tail: float = 0.45
    breathe: float | None = None   # extra seconds after the narration (None = BREATHE for beats with narration)
    trans: str | None = None   # transition INTO this beat's first shot
    tdur: float = 0.5
    texts: list = field(default_factory=list)    # [dict(content, at, dur, kind)]
    sfx: list = field(default_factory=list)      # [(file name, at, db)]
    split: list | None = None  # scene-1 split screen: list of (top shots, bottom shots) — replaces `shots`
    logo_pop: float | None = None                # big E-DA logo at this offset
    snap: bool = True
    line_at: dict | None = None                  # {line id: offset in the beat} instead of one after another
    cut_at_lines: bool = False                   # shot k starts with line k (e.g. the T-rex appears on "…with a T-rex")
    exact_cuts: bool = False                     # shots with a duration cut exactly there (not nudged to a beat): word-timed cuts
    free_order: bool = False                     # hook / "previously" / glimpse: allowed outside the scene-number order
    song: tuple | None = None                    # (file, lead s): a song just for this beat; the main music fades out under it
    #                                              (file None = no song, the music just fades out for the clip's own sound)


@dataclass
class FadeOut:                 # picture + sound fade out at the very end
    dur: float = 1.5


@dataclass
class Typed:                   # black screen + typed date/time
    l1: str
    l2: str
    length: float
    full: bool = False         # the approved 8 s v3 intro (server generator)


@dataclass
class Music:
    file: str
    at: float | None = None    # timeline start (None = now)
    src: float = 0.0           # song offset
    db: float = -7.0
    fade_in: float = 0.0


@dataclass
class Mark:                    # logo strip from here on
    what: str


# ---------------------------------------------------------------- helpers
def scene_key(clip):
    """'Scene 3_20_1' → ('', (3, 20, 1)); 'Intro Ansell Scene 1_4' → ('Intro Ansell', (1, 4)); None if not numbered.
    The user's footage names ARE the chronological order (Scene <scene>_<shot>[_<part>])."""
    import re
    m = re.match(r"^(.*?)\s*Scene (\d+(?:_\d+)*)\b", clip.rsplit(".", 1)[0])
    if not m:
        return None
    return m.group(1).strip(), tuple(int(x) for x in m.group(2).split("_"))


def q(t):
    return round(round(t * FPS) / FPS, 6)


FONT_FILES = {("Poppins", 500): "Poppins-Medium.ttf", ("Poppins", 600): "Poppins-SemiBold.ttf", ("Poppins", 700): "Poppins-Bold.ttf",
              ("Poppins", 800): "Poppins-ExtraBold.ttf", ("Poppins", 900): "Poppins-Black.ttf", ("Anton", 400): "Anton-Regular.ttf"}


def fit_size(text, font, weight, size, spacing=0, max_w=960):
    """Largest size ≤ `size` at which every line of `text` is at most max_w px wide (measured with the real font)."""
    from PIL import ImageFont
    f = ROOT / "library" / "fonts" / FONT_FILES.get((font, weight), "Poppins-Bold.ttf")
    try:
        ft = ImageFont.truetype(str(f), size)
    except OSError:
        return size
    widest = max(ft.getlength(line) + spacing * max(0, len(line) - 1) for line in text.split("\n"))
    return size if widest <= max_w else max(24, int(size * max_w / widest))


class Builder:
    def __init__(self, project: str, picks: dict, edl: list, label: str, step_id: str, opts: dict | None = None):
        """opts (used by the AI Editor for any project; the Taiwan builds pass none → today's behaviour):
        edit_dir (narration.json / beats), footage_db, breathe, colors {speaker: hex}, logo_asset (None = no strip),
        big_logo_assets [names], shared_narration (also read the Taiwan narration.json, default only without edit_dir)."""
        self.project, self.picks, self.edl, self.label, self.step = project, picks, edl, label, step_id
        o = self.opts = opts or {}
        self.edit = Path(o["edit_dir"]) if o.get("edit_dir") else EDIT
        self.footage_db = o.get("footage_db", FOOTAGE_DB)
        self.breathe_default = o.get("breathe", BREATHE)
        self.colors = {**COLORS, **(o.get("colors") or {})}
        self.narr = {}
        if o.get("shared_narration", not o.get("edit_dir")) and (EDIT / "narration.json").exists():
            self.narr = json.loads((EDIT / "narration.json").read_text(encoding="utf-8"))
        own = ROOT / "projects" / project / "docs" / "edit" / "narration.json"    # e.g. the POV monologues (a01…, k01…)
        if own.exists() and own.resolve() != (EDIT / "narration.json").resolve():
            self.narr.update(json.loads(own.read_text(encoding="utf-8")))
        self.beats = {}
        for k in ("mamma_mia", "latch"):
            f = self.edit / f"beats_{k}.json"
            if f.exists():
                self.beats[k] = json.loads(f.read_text())
        self.grid = []                 # timeline beat times of the music currently playing
        self.t = 0.0
        self.cuts = []                 # (time, type, dur) transitions on V1
        self.logo_from = None
        self.music = []                # [(Music, start)]
        self.typed_ranges = []         # black typed-date screens (no logo strip there)
        self._true_out = {}            # (track, start) → source out point for sped-up shots
        self.text_busy = {}            # overlay text track → [(start, end)]
        self.songs = []                # [(file, start, end)] beat-only songs (main music ducks out)
        self.fade_end = None
        self.end = 0.0

    # ------------------------------------------------ server helpers
    def asset(self, name):
        A = self.A
        n = name.lower()
        for cand in (n, n + ".mp4", n + ".mov", n + ".png", n + ".mp3", n + ".wav"):
            if cand in A:
                return A[cand]
        raise KeyError(f"asset not found: {name}")

    def batch(self, ops, label):
        if not ops:
            return []
        return api.batch(ops, label)["result"]

    def progress(self, frac, detail, log=None):
        cp.step(self.step, frac=min(0.97, frac), detail=detail, log=log)

    # ------------------------------------------------ music grid
    def beats_for(self, file: str) -> dict:
        """Beats of a song: the Taiwan files (beats_mamma_mia / beats_latch), else docs/edit/beats/<asset id>.json
        (the AI Editor's detect_beats), else analysed now and cached there."""
        n = file.lower()
        if "mamma" in n and "mamma_mia" in self.beats:
            return self.beats["mamma_mia"]
        if "latch" in n and "latch" in self.beats:
            return self.beats["latch"]
        try:
            a = self.asset(file)
        except (KeyError, AttributeError):
            return {}
        f = self.edit / "beats" / f"{a['id']}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        if not self.opts:                                 # Taiwan builds: unchanged (no beats file → no grid)
            return {}
        from app.beats import analyze_file
        info = analyze_file(str(ROOT / a["path"]))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(info), encoding="utf-8")
        return info

    def set_music(self, m: Music, start: float):
        if not self.opts:
            key = "mamma_mia" if "mamma" in m.file.lower() else "latch"
            info = self.beats.get(key, {})
        else:
            info = self.beats_for(m.file)
        self.grid = [start + (x - m.src) for x in info.get("beats", []) if x >= m.src]
        self.down = [start + (x - m.src) for x in info.get("downbeats", []) if x >= m.src]
        self.period = 60.0 / info["bpm"] if info.get("bpm") else 0.5

    def snap_up(self, t, slack=None, down=False):
        """Musical end point at/after t without forcing it: a scene change goes to the next DOWNBEAT (bar start) if one
        is within ~1.3 beats, otherwise any cut goes to the next beat within half a beat; else t stays."""
        if not self.grid:
            return q(t)
        if down and getattr(self, "down", None):
            i = bisect.bisect_left(self.down, t - 0.06)
            if i < len(self.down) and self.down[i] - t <= 1.3 * self.period:
                return q(max(t, self.down[i]))
        slack = 0.5 * self.period if slack is None else slack
        i = bisect.bisect_left(self.grid, t - 0.06)
        if i < len(self.grid) and self.grid[i] - t <= slack:
            return q(max(t, self.grid[i]))
        return q(t)

    BIG = {"inward_wipe": 2.0, "dip_black": 2.0, "light_leak_flash": 2.0, "cross_dissolve": 1.0}   # length in beats
    QUICK = {"whip_pan": 0.5, "zoom_in": 0.5, "flash": 0.5, "glitch": 0.5}

    def trans_len(self, typ, fallback):
        beats = self.BIG.get(typ) or self.QUICK.get(typ)
        if not beats or not self.grid:
            return fallback
        return round(min(1.0, max(0.2, beats * self.period)), 3)

    def snap_near(self, t, slack=0.25):
        if not self.grid:
            return q(t)
        i = bisect.bisect_left(self.grid, t)
        best = min((g for g in self.grid[max(0, i - 1):i + 1]), key=lambda g: abs(g - t), default=t)
        return q(best if abs(best - t) <= slack else t)

    # ------------------------------------------------ narration
    def line_len(self, lid):
        e = self.narr.get(lid)
        if not e:
            raise KeyError(f"narration {lid} not generated")
        return max(x["dur"] for x in e)

    # ------------------------------------------------ footage check (before anything is touched)
    def check(self):
        """Every clip / song / sound the edit list names must exist in the project (a renamed file would otherwise stop
        the build halfway, after the timeline was cleared). Also reports shots out of the user's scene-number order
        (rule: chronological) and project footage the edit doesn't use (e.g. a newly added clip).
        Returns (missing, order, unused); missing comes with the closest file names."""
        import difflib
        self.A = api.assets_by_name()
        names = sorted({a["name"].rsplit(".", 1)[0] for a in self.A.values()})
        need = []
        for item in self.edl:
            if isinstance(item, Music):
                need.append(item.file)
            elif isinstance(item, Beat):
                for s in self.beat_shots(item):
                    need.append(s.clip)
                need += [sf[0] for sf in item.sfx]
                if item.song and item.song[0]:
                    need.append(item.song[0])
        missing = [f"narration line {lid} (not generated)" for item in self.edl if isinstance(item, Beat)
                   for lid in item.lines if lid not in self.narr]
        for n in dict.fromkeys(need):
            try:
                self.asset(n)
            except KeyError:
                # renumbered into parts first ("Scene 3_20" → "Scene 3_20_1", "_2"), then look-alikes
                close = [x for x in names if x.lower().startswith(n.lower() + "_")]
                close += [x for x in difflib.get_close_matches(n, names, n=3, cutoff=0.6) if x not in close]
                close = close[:3]
                missing.append(f"{n}" + (f" (did you mean: {', '.join(close)}?)" if close else ""))
        # chronological order: within one camera series ("Intro Ansell Scene 1_x" …) the full number must not go
        # back; across series only the scene number (1, 2, 3 …) must not go back
        order, last, last_by = [], None, {}
        for item in self.edl:
            if not isinstance(item, Beat) or item.free_order:
                continue
            for s in self.beat_shots(item):
                k = scene_key(s.clip)
                if not k:
                    continue
                series, num = k
                prev = last_by.get(series)
                if prev and num < prev[1]:
                    order.append(f"{s.clip} comes after {prev[0]}")
                if last and num[0] < last[1][0]:
                    order.append(f"{s.clip} (scene {num[0]}) comes after {last[0]} (scene {last[1][0]})")
                last_by[series] = (s.clip, num)
                last = (s.clip, num)
        used = {self.asset(n)["id"] for n in need if not any(n in m for m in missing)}
        proj_video = [a for a in self.A.values() if a["path"].startswith(f"projects/{self.project}/assets/video/")]
        unused = sorted(a["name"] for a in proj_video if a["id"] not in used)
        return missing, order, unused

    @staticmethod
    def beat_shots(b):
        if b.split:
            return [s for top, bot in b.split for s in top + bot]
        return list(b.shots)

    # ------------------------------------------------ main
    def run(self):
        st = api.state()
        if st["project_name"] != self.project:
            api.post("/api/projects/open", {"name": self.project})
        missing, order, unused = self.check()
        for o in order:
            print("  ⚠ order:", o)
        if unused:
            print("  footage not in this edit:", ", ".join(unused))
        if missing:
            msg = "Build stopped before touching the timeline: not in the project → " + "; ".join(missing)
            cp.step(self.step, "error", detail=msg[:200], log=msg[:200])
            raise SystemExit(msg)
        st = api.state()
        if st["project"]["clips"]:
            api.batch([("delete", {"ids": [c["id"] for c in st["project"]["clips"]], "ignore_link": True})], "Clear timeline")
        tracks = {t["id"]: t for t in api.state()["project"]["tracks"]}
        if "V4" not in tracks:
            api.op("add_track", "Add overlay track", kind="video")
        if "A5" not in tracks:
            r = api.op("add_track", "Add 2nd narration track", kind="audio")
        tracks = {t["id"]: t for t in api.state()["project"]["tracks"]}
        api.batch([("set_track", {"id": "A5", "patch": {"name": "Narration 2"}})] if "A5" in tracks else [], "Name track")
        self.A = api.assets_by_name()
        self.look = next((l for l in api.state()["presets"]["looks"] if l["id"] == self.picks.get("look")),
                         {"color": {}, "filters": []})    # no look chosen → footage colors as they are
        self.overlay_tracks = sorted(t["id"] for t in api.state()["project"]["tracks"] if t["kind"] == "text" and t["id"] != "T1")
        n = len(self.edl)
        for i, item in enumerate(self.edl):
            if isinstance(item, Music):
                self.music.append((item, self.t if item.at is None else item.at))
                self.set_music(item, self.t if item.at is None else item.at)
            elif isinstance(item, Mark):
                self.logo_from = self.t
            elif isinstance(item, FadeOut):
                self.fade_end = item.dur
            elif isinstance(item, Typed):
                self.typed(item)
            elif isinstance(item, Beat):
                nxt = next((x for x in self.edl[i + 1:] if isinstance(x, (Beat, Typed))), None)
                scene_change = isinstance(nxt, Typed) or (isinstance(nxt, Beat) and nxt.trans in self.BIG)
                self.beat(item, i, scene_change)
            self.progress(0.05 + 0.6 * (i + 1) / n, f"Timeline {self.t:.0f} s built", None)
        self.end = self.t
        self.finish()

    # ------------------------------------------------ typed date
    def typed(self, ty: Typed):
        start = self.t
        self.typed_ranges.append((start, q(start + ty.length)))
        self.text_busy.setdefault("T2", []).append((start, start + ty.length))      # typed line 2 lives on T2
        if ty.full:
            api.post("/api/generate/typed_intro", {"start": start, "pack": "slim",
                                                  "lines": [{"text": ty.l1, "weight": 500, "size": 80, "y": 860 / 1920, "spacing": 1, "track": "T1"},
                                                            {"text": ty.l2, "weight": 700, "size": 107, "y": 1040 / 1920, "spacing": 4, "track": "T2"}]})
            self.t = q(start + ty.length)
            return
        from app import generators as g
        size1 = fit_size(ty.l1, "Poppins", 500, 80, spacing=1, max_w=940)   # long dates ("Sunday, November 1st…") must fit
        lines = [{"text": ty.l1, "weight": 500, "size": size1, "y": 860 / 1920, "spacing": 1, "track": "T1"},
                 {"text": ty.l2, "weight": 700, "size": 107, "y": 1040 / 1920, "spacing": 4, "track": "T2"}]
        speedup = min(1.0, (ty.length - 1.0) / 5.6)
        times = g.schedule(lines, gap=0.095 * speedup, jit=0.03 * speedup, first=0.25, line_pause=0.35 * speedup + 0.1)
        last = max(ts[-1] for ts in times)
        fade_end = ty.length - 0.05
        fade_start = max(last + 0.45, fade_end - 0.45)
        letters = [(t, ch) for ln, ts in zip(lines, times) for t, ch in zip(ts, ln["text"])]
        key = hashlib.sha1(json.dumps([lines, ty.length]).encode()).hexdigest()[:8]
        local = ROOT / "projects" / self.project / "assets" / "audio" / "sfx" / f"typed_{key}.wav"
        if not local.exists():
            from scipy.io import wavfile
            local.parent.mkdir(parents=True, exist_ok=True)
            wavfile.write(local, g.keys_real.SR, g.keys_real.make_track(letters, pack="slim", lufs=-28.5, dur=ty.length))
            api.post("/api/rescan")
            self.A = api.assets_by_name()
        ops = []
        for ln, ts in zip(lines, times):
            ops.append(("add_text", {"track": ln["track"], "start": start, "dur": fade_end, "content": ln["text"], "preset": "typewriter",
                                     "x": 0.5, "y": ln["y"], "times": ts,
                                     "style": {"font": "Poppins", "weight": ln["weight"], "size": ln["size"], "outline": 0, "spacing": ln["spacing"]},
                                     "anim": {"in": "typewriter", "in_dur": 0.0, "out": "fade", "out_dur": round(fade_end - fade_start, 2)}}))
        ops.append(("add_media", {"asset": self.asset(local.name)["id"], "track": "A3", "start": start}))
        self.batch(ops, f"Typed date: {ty.l1}")
        self.t = q(start + ty.length)

    # ------------------------------------------------ one beat
    def beat(self, b: Beat, idx, scene_change=False):
        start = self.t
        lens = []
        for lid in b.lines:
            lens.append(self.line_len(lid))
        # where each line starts (one after another, or at a fixed moment of the beat)
        starts, t = [], start + b.lead
        for lid, ln in zip(b.lines, lens):
            if b.line_at and lid in b.line_at:
                t = start + b.line_at[lid]
            starts.append(t)
            t += ln + 0.14
        narr_end = (starts[-1] + lens[-1] - start) if lens else 0.0
        breathe = b.breathe if b.breathe is not None else (self.breathe_default if b.lines else 0.0)
        fixed = sum(s.d for s in b.shots if s.d) if b.shots else 0
        D = max(b.min, narr_end + b.tail + breathe, fixed + (0.8 if any(s.d is None for s in (b.shots or [])) else 0))
        end = self.snap_up(start + D, down=scene_change) if b.snap else q(start + D)
        D = end - start
        if b.split:
            self.place_split(b.split, start, D)
        elif b.cut_at_lines and len(b.shots) > 1:
            cuts = [start] + [q(s - 0.1) for s in starts[1:len(b.shots)]] + [end]
            self.place_shots_at(b.shots, cuts)
        else:
            self.place_shots(b.shots, start, D, exact=b.exact_cuts)
        if b.trans:
            self.cuts.append((start, b.trans, self.trans_len(b.trans, b.tdur)))
        if b.song:
            self.songs.append((b.song[0], start - b.song[1], end))
        # narration
        for lid, t0 in zip(b.lines, starts):
            self.place_line(lid, t0)
        # overlays
        for tx in b.texts:
            at = D - tx["from_end"] if "from_end" in tx else tx.get("at", 0.0)
            self.add_text(start + at, tx.get("dur", D - at), tx)
        for sf in b.sfx:
            f, at, db = sf[:3]
            self.add_sfx(f, start + at, db, fade_in=sf[3] if len(sf) > 3 else 0.0)
        if b.logo_pop is not None:
            self.big_logo(start + b.logo_pop, min(2.6, D - b.logo_pop))
        self.t = end

    # ------------------------------------------------ shots
    def shot_ops(self, s: S, track, start, d, audio=True):
        a = self.asset(s.clip)
        src_len = (a["meta"].get("dur") or 1e9)
        need = d * s.speed
        speed = s.speed
        if s.a + need > src_len - 0.01:                 # not enough source: slow it down a little (never < 0.4)
            speed = max(0.4, (src_len - 0.01 - s.a) / d)  # (only 10 ms margin: a clip's last frames can matter — 5_18's hand)
            need = d * speed
        # added at normal speed with exactly the timeline length d (never overlaps the next shot); the real source
        # range + speed are set afterwards in ONE update (style_shots), so nothing gets trimmed in between
        args = {"asset": a["id"], "track": track, "start": q(start), "in_": round(s.a, 3), "out": round(min(src_len, s.a + d), 3),
                "link_audio": bool(audio and a["meta"].get("has_audio"))}
        self._true_out[(track, q(start))] = round(min(src_len, s.a + need), 3)
        return args, speed

    def place_shots(self, shots, start, D, exact=False):
        fixed = sum(s.d for s in shots if s.d)
        free = [s for s in shots if not s.d]
        wsum = sum(s.w for s in free) or 1.0
        rest = max(0.0, D - fixed)
        t = start
        plan = []
        for i, s in enumerate(shots):
            d = s.d if s.d else rest * s.w / wsum
            e = start + D if i == len(shots) - 1 else (q(t + d) if exact and s.d else self.snap_near(t + d))
            e = max(e, t + 0.4)
            plan.append((s, t, e - t))
            t = e
        adds, meta = [], []
        for s, t0, d in plan:
            if s.mode == "blur":
                bg, _ = self.shot_ops(s, "V1", t0, d, audio=False)
                fg, sp = self.shot_ops(s, "V2", t0, d, audio=True)
                adds += [("add_media", bg), ("add_media", fg)]
                meta += [(s, "bg", sp), (s, "fg", sp)]
            else:
                ar, sp = self.shot_ops(s, "V1", t0, d)
                adds.append(("add_media", ar))
                meta.append((s, "main", sp))
        res = self.batch(adds, "Shots " + ", ".join(sorted({p[0].clip.replace("Scene ", "") for p in plan})))
        self.style_shots(res, meta)

    def place_shots_at(self, shots, cuts):
        """Shot k from cuts[k] to cuts[k+1] (used when a shot must change exactly with a line)."""
        adds, meta = [], []
        for s, a, b in zip(shots, cuts[:-1], cuts[1:]):
            ar, sp = self.shot_ops(s, "V1", a, b - a)
            adds.append(("add_media", ar))
            meta.append((s, "main", sp))
        res = self.batch(adds, "Shots " + ", ".join(sorted({s.clip.replace("Scene ", "") for s in shots})))
        self.style_shots(res, meta)

    def place_split(self, pairs, start, D):
        """pairs = [(top shots, bottom shots)] laid out one after another; each half cut independently."""
        seg = D / len(pairs)
        adds, meta = [], []
        for k, (top, bot) in enumerate(pairs):
            t0 = start + seg * k
            for shots, track, half in ((top, "V2", "top"), (bot, "V1", "bottom")):
                tt = t0
                for j, s in enumerate(shots):
                    d = seg / len(shots)
                    e = t0 + seg if j == len(shots) - 1 else min(t0 + seg - 0.5, max(tt + 0.5, self.snap_near(tt + d)))
                    ar, sp = self.shot_ops(s, track, tt, e - tt, audio=(half == "bottom"))   # one sound source (A1)
                    adds.append(("add_media", ar))
                    meta.append((s, half, sp))
                    tt = e
        res = self.batch(adds, "Split screen: Karina top, Ansell bottom")
        self.style_shots(res, meta)

    def style_shots(self, res, meta):
        ups = []
        look = self.look
        byid = {c["id"]: c for c in api.state()["project"]["clips"]}
        alive = set(byid)
        for ids, (s, role, speed) in zip(res, meta):
            vid = ids[0]
            aud = ids[1] if len(ids) > 1 and ids[1] in alive else None
            if vid not in alive:
                print(f"  (clip {vid} was replaced by a later shot — skipped)")
                continue
            filters = copy.deepcopy(look.get("filters", []))
            if s.night:
                filters.append({"type": "night_boost", "amount": 0.5})
            motion = {"fit": "fill", "x": s.x, "y": 0.0, "scale": s.zoom}
            crop = {"l": 0, "t": 0, "r": 0, "b": 0}
            if role == "bg":
                filters = filters + [{"type": "gaussian_blur", "radius": 34}]
                motion = {"fit": "fill", "x": 0, "y": 0, "scale": 1.15}
            elif role == "fg":
                motion = {"fit": "fit", "x": 0, "y": -40, "scale": 1.0 * s.zoom}
            elif role in ("top", "bottom"):
                motion = {"fit": "fill", "x": s.x, "y": -480 if role == "top" else 480, "scale": 1.0}
                crop = {"l": 0, "t": 0.25, "r": 0, "b": 0.25}
            elif s.mode == "native":
                motion = {"fit": "fill", "x": 0, "y": 0, "scale": s.zoom}
            if s.crop and role not in ("top", "bottom"):
                crop = {"l": 0, "t": 0, "r": 0, "b": 0, **s.crop}
            patch = {"motion": motion, "crop": crop, "color": copy.deepcopy(look.get("color", {})), "filters": filters}
            sp_patch = {}
            if abs(speed - 1.0) > 1e-3:
                c = byid.get(vid)
                tout = self._true_out.get((c["track"], q(c["start"]))) if c else None
                if tout:
                    sp_patch = {"speed": round(speed, 4), "out": tout, "keep_pitch": True}
            ups.append(("update", {"ids": [vid], "patch": {**patch, **sp_patch}, "ripple_speed": False}))
            if aud:
                vol = 0.0 if s.keep_sound else self.footage_db
                ups.append(("update", {"ids": [aud], "patch": {"volume_db": vol, **sp_patch}, "ripple_speed": False}))
        self.batch(ups, "Frame, color look and sound levels")

    # ------------------------------------------------ narration placement
    def place_line(self, lid, t):
        entries = sorted(self.narr[lid], key=lambda e: e["speaker"] != "Karina")   # Karina first when both speak
        both = len(entries) > 1
        for k, e in enumerate(entries):
            track = "A5" if (both and k == 1) else "A4"
            t0 = round(t + (0.03 if k else 0), 3)
            # the 2nd voice of a "both" line is placed far away first, then moved onto its own track — placing it on
            # the narration track at t0 would overwrite (cut) the 1st voice's clip there
            at = t0 if track == "A4" else 9000.0 + 10 * k
            st = api.post("/api/tts/place", {"file": e["file"], "start": at, "text": e["text"], "voice": e["speaker"],
                                             "tone": e["tone"], "intensity": e.get("emotion", 0.6), "steady": False})["project"]
            new = [c for c in st["clips"] if c["type"] == "tts" and c["tts"].get("file") == e["file"] and abs(c["start"] - at) < 0.05]
            if not new:
                print(f"  ⚠ narration {lid} {e['speaker']} not found after placing")
                continue
            cid = new[-1]["id"]
            if e.get("mode") == "dialogue":            # natural conversation line: editable Emotion + regenerate in the Inspector
                api.op("update", "Conversation voice", ids=[cid], ripple_speed=False,
                       patch={"tts": {"file": e["file"], "mode": "dialogue", "model": e.get("model"), "words": e.get("words"),
                                      "ctx_prev": e.get("ctx_prev"), "stale": False}})
            if track != "A4":
                api.op("move", "Narration track", ids=[cid], delta=round(t0 - at, 4), track=track)
            if both:                                     # two voices at once ≈ double the peak → each 4 dB lower
                api.op("update", "Together line level", ids=[cid], patch={"volume_db": -4.0}, ripple_speed=False)
            if k == 0:                                   # one caption per line (the first voice)
                self.captions_for(cid, "Karina & Ansell" if both else e["speaker"])

    def captions_for(self, cid, speaker):
        col = self.colors.get(speaker, "#FFD54A")
        tpl = self.picks.get("caption")
        if not tpl:                                       # captions off in the style
            return
        ov = {"word_pop": {"active": {"color": col}},
              "karaoke_pill": {"active": {"color": "#FFFFFF", "scale": 1.0, "box": col + "FF"}},
              "keyword_highlight": {"emph_color": col}}.get(tpl, {"active": {"color": col}})
        api.op("update", "Caption on", ids=[cid], patch={"tts": {"caption": True}}, ripple_speed=False)
        made = api.op("narration_captions", "Narration captions", id=cid)["result"] or []
        if made:
            api.batch([("restyle_captions", {"ids": made, "template": tpl, "keep_position": False}),
                       ("restyle_captions", {"ids": made, "overrides": ov})], f"Caption style ({speaker})")

    # ------------------------------------------------ overlays
    def add_text(self, start, dur, tx):
        kind = tx.get("kind", "tag")
        if kind == "hook":
            style = {"font": "Poppins", "weight": 800, "size": 70, "color": "#FFFFFF", "outline": 7, "outline_color": "#000000",
                     "shadow": 6, "line_height": 1.15}
            anim, y = {"in": "pop", "in_dur": 0.25, "out": "fade", "out_dur": 0.2}, tx.get("y", 0.33)
        elif kind == "big":
            style = {"font": "Anton", "weight": 400, "size": 150, "color": "#FFFFFF", "outline": 0, "shadow": 10, "spacing": 4}
            anim, y = {"in": "pop", "in_dur": 0.3, "out": "fade", "out_dur": 0.25}, tx.get("y", 0.42)
        elif kind == "sub":
            style = {"font": "Poppins", "weight": 700, "size": 46, "color": "#FFFFFF", "outline": 5, "shadow": 4}
            anim, y = {"in": "slide_up", "in_dur": 0.3, "out": "fade", "out_dur": 0.25}, tx.get("y", 0.52)
        elif kind == "name":
            style = {"font": "Poppins", "weight": 800, "size": 54, "color": "#FFFFFF", "outline": 0, "box": True,
                     "box_color": tx.get("color", "#000000") + "E6"}
            anim, y = {"in": "pop", "in_dur": 0.25, "out": "fade", "out_dur": 0.25}, tx["y"]
        else:                                             # location tag
            style = {"font": "Poppins", "weight": 700, "size": 40, "color": "#1A1203", "outline": 0, "box": True,
                     "box_color": "#FFFFFFE8", "spacing": 2}
            anim, y = {"in": "pop", "in_dur": 0.25, "out": "fade", "out_dur": 0.3}, tx.get("y", 0.205)
        style["size"] = fit_size(tx["content"], style["font"], style["weight"], style["size"], style.get("spacing", 0),
                                 max_w=900 if style.get("box") else 960)
        api.op("add_text", f"Text: {tx['content'][:30]}", track=self.text_track(start, start + dur), start=q(start), dur=round(dur, 3),
               content=tx["content"], preset="title", x=tx.get("x", 0.5), y=y, style=style, anim=anim)
        if kind in ("tag", "name"):
            self.add_sfx("pop_1", start, -16)

    def song_track(self):
        """Own track for beat-only songs (TikTok trend), NOT ducked: the footage's sound under it would duck it."""
        tr = api.state()["project"]["tracks"]
        t = next((t for t in tr if t.get("name") == "TikTok song"), None)
        if t:
            return t["id"]
        before = {t["id"] for t in tr}
        api.op("add_track", "Add TikTok song track", kind="audio")
        tid = next(t["id"] for t in api.state()["project"]["tracks"] if t["id"] not in before)
        api.op("set_track", "TikTok song track", id=tid, patch={"name": "TikTok song", "duck": False})
        return tid

    def music_track2(self):
        tr = api.state()["project"]["tracks"]
        t2 = next((t for t in tr if t.get("name") == "Music 2"), None)
        if t2:
            return t2["id"]
        before = {t["id"] for t in tr}
        api.op("add_track", "Add Music 2 track", kind="audio")
        tid = next(t["id"] for t in api.state()["project"]["tracks"] if t["id"] not in before)
        api.op("set_track", "Music 2 track", id=tid, patch={"name": "Music 2", "duck": True})
        return tid

    def text_track(self, start, end):
        """A text track that is free over [start, end) (texts on one track would replace each other); T1 = captions."""
        for tid in self.overlay_tracks:
            if all(e <= start + 1e-3 or s >= end - 1e-3 for s, e in self.text_busy.get(tid, [])):
                self.text_busy.setdefault(tid, []).append((start, end))
                return tid
        before = {t["id"] for t in api.state()["project"]["tracks"]}
        api.op("add_track", "Add text track", kind="text")
        tid = next(t["id"] for t in api.state()["project"]["tracks"] if t["id"] not in before)
        self.overlay_tracks.append(tid)
        self.text_busy[tid] = [(start, end)]
        return tid

    def add_sfx(self, name, t, db=-10, fade_in=0.0):
        try:
            a = self.asset(name)
        except KeyError:
            return
        r = api.op("add_media", f"SFX {name}", asset=a["id"], track="A3", start=q(t))["result"]
        if r and (db or fade_in):
            api.op("update", "SFX level", ids=r, patch={"volume_db": db, "fade_in": fade_in}, ripple_speed=False)

    def big_logo(self, t, dur):
        names = self.opts.get("big_logo_assets") or ["EDA Logo backed.png", "EDA Logo.png"]   # Taiwan: a 30% white circle behind it
        a = None
        for nm in names:
            try:
                a = self.asset(nm)
                break
            except KeyError:
                continue
        if a is None:
            return
        r = api.op("add_media", "E-DA logo", asset=a["id"], track="V4", start=q(t), still_dur=round(dur, 3))["result"]
        api.op("update", "E-DA logo size", ids=r, patch={"motion": {"fit": "fit", "scale": 0.62, "y": -60}, "fade_out": 0.25},
               ripple_speed=False)
        api.op("apply_anim_preset", "E-DA logo pop", ids=r, name="pop_in")

    # ------------------------------------------------ finishing passes
    def finish(self):
        st = api.state()["project"]
        self.progress(0.7, "Transitions, logos, music")
        # transitions on V1 at recorded cuts
        v1 = sorted([c for c in st["clips"] if c["track"] == "V1" and c["type"] == "media"], key=lambda c: c["start"])
        ops = []
        for t, typ, dur in self.cuts:
            a = next((c for c in v1 if abs(c["start"] + (c["out"] - c["in"]) / c.get("speed", 1) - t) < 0.04), None)
            b = next((c for c in v1 if abs(c["start"] - t) < 0.04), None)
            if a or b:
                ops.append(("add_transition", {"type": typ, "a": a["id"] if a else None, "b": b["id"] if b else None, "dur": dur}))
        for o in ops:
            try:
                api.batch([o], f"Transition {o[1]['type']}")
            except RuntimeError as e:
                print("  transition skipped:", e)
        # logo strip
        logo_name = self.opts["logo_asset"] if "logo_asset" in self.opts else f"logo_strip_{self.picks.get('logo')}.png"
        if self.logo_from is not None and logo_name:
            strip = self.asset(logo_name)
            spans, a = [], self.logo_from
            for s, e in sorted(self.typed_ranges):
                if e <= a:
                    continue
                if s > a:
                    spans.append((a, s))
                a = max(a, e)
            if self.end > a:
                spans.append((a, self.end))
            for s, e in spans:
                if e - s < 0.5:
                    continue
                r = api.op("add_media", "Logo strip", asset=strip["id"], track="V3", start=q(s), still_dur=round(e - s, 3))["result"]
                api.op("update", "Logo strip fit", ids=r, patch={"motion": {"fit": "fit"}, "fade_in": 0.3, "fade_out": 0.2}, ripple_speed=False)
        # music
        XF = 1.6                                         # crossfade between songs (the next one fades in meanwhile)
        for k, (m, at) in enumerate(self.music):
            last = k + 1 >= len(self.music)
            nxt = self.end if last else self.music[k + 1][1]
            track = "A2"
            if k % 2 == 1:                               # 2nd song on its own track so the two can overlap
                track = self.music_track2()
            a = self.asset(m.file)
            start = q(max(0.0, at - (XF / 2 if k else 0)))
            stop = nxt + (0 if last else XF / 2)
            # beat-only songs (TikTok trend): the main song fades out before them and back in after, at the same
            # musical position (it keeps running underneath), so every later cut is still on its beat
            pieces, s0 = [], start
            for f, ss, se in sorted(self.songs, key=lambda x: x[1]):
                if s0 < ss < stop:
                    pieces.append((s0, ss + 0.35))
                    s0 = se - 0.25
            pieces.append((s0, stop))
            for j, (p0, p1) in enumerate(pieces):
                if p1 - p0 < 0.3:
                    continue
                r = api.op("add_media", f"Music {m.file[:24]}", asset=a["id"], track=track, start=q(p0),
                           in_=round(m.src + (p0 - start), 3), out=round(m.src + (p1 - start), 3))["result"]
                fi = max(m.fade_in, XF if k else 0.0) if j == 0 else 0.6
                fo = (2.5 if last else XF) if j == len(pieces) - 1 else 0.45
                api.op("update", "Music level + fades", ids=r, patch={"volume_db": m.db, "fade_in": fi, "fade_out": fo}, ripple_speed=False)
        for f, ss, se in self.songs:
            if f is None:                                # song=(None, 0): only the music fades out (clip's own sound)
                continue
            a = self.asset(f)
            tr = self.song_track()
            src_len = a["meta"].get("dur") or (se - ss)
            r = api.op("add_media", f"Song {f[:24]}", asset=a["id"], track=tr, start=q(max(0.0, ss)),
                       in_=round(max(0.0, -ss), 3), out=round(min(src_len, se - ss + 0.2), 3))["result"]
            api.op("update", "Song level", ids=r, patch={"volume_db": 0.0, "fade_in": 0.08, "fade_out": 0.4}, ripple_speed=False)
        if self.fade_end:                                # picture + sound fade out at the very end
            st = api.state()["project"]
            v1 = sorted([c for c in st["clips"] if c["track"] == "V1" and c["type"] == "media"], key=lambda c: c["start"])
            if v1:
                try:
                    api.batch([("add_transition", {"type": "dip_black", "a": v1[-1]["id"], "b": None, "dur": self.fade_end})], "Fade out at the end")
                except RuntimeError as e:
                    print("  fade-out skipped:", e)
            lastc = [c for c in st["clips"] if c["track"] in ("V2", "V3", "A1") and c["start"] + (c.get("dur") or (c["out"] - c["in"]) / c.get("speed", 1)) > self.end - 0.1]
            if lastc:
                api.batch([("update", {"ids": [c["id"] for c in lastc], "patch": {"fade_out": self.fade_end}, "ripple_speed": False})], "Fade out sound + overlays")
        # safety net: any moment without picture (outside the black typed-date screens) is reported
        st = api.state()["project"]
        spans = sorted((c["start"], c["start"] + (c.get("dur") or (c["out"] - c["in"]) / c.get("speed", 1.0)))
                       for c in st["clips"] if c["track"] in ("V1", "V2") and c["type"] == "media")
        holes, t = [], 0.0
        for s, e in spans:
            if s > t + 0.07:
                holes.append((t, s))
            t = max(t, e)
        if self.end > t + 0.07:
            holes.append((t, self.end))
        holes = [(a, b) for a, b in holes if not any(ts - 0.05 <= a and b <= te + 0.05 for ts, te in self.typed_ranges)]
        self.holes = holes
        for a, b in holes:
            print(f"  ⚠ no picture from {a:.2f} to {b:.2f} s")
            cp.step(self.step, log=f"⚠ gap without picture {a:.1f}–{b:.1f} s")
        self.progress(0.95, "Timeline done")
