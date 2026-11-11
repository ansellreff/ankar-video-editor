"""The AI Editor's tools — the ONLY things Claude can do. All of them work on the open project.

Kinds: read (free) · doc (writes review files in docs/, never overwrites the editor's edits) · ui (asks the editor) ·
proposal (changes the video or spends credits: shows an Approve card and runs ONLY after Approve).
There is no shell, code, general web or general file tool. Paths are confined to the project's docs/ folder."""
from __future__ import annotations

import io
import json
import math
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw

from ..paths import MEDIA_CACHE, ROOT
from . import style as style_mod
from .workflow import DocError, STAGE_IDS

# ops the edit tool may use (no project/settings/voice/key operations)
ALLOWED_OPS = {"add_media", "add_text", "move", "trim", "split", "delete", "update", "set_props", "toggle_anim",
               "set_key", "remove_key", "freeze_frame", "set_speed", "apply_anim_preset", "add_transition",
               "update_transition", "remove_transition", "add_marker", "update_marker", "remove_marker", "set_track",
               "apply_look", "apply_transition_pack", "restyle_captions", "rechunk_captions", "narration_captions",
               "apply_voice_fx", "close_gap", "link", "unlink", "tts_layout", "add_captions"}
ASK_FIRST_OPS = {"delete"}       # (everything in edit asks anyway; these are named in the card)


class ToolError(Exception):
    pass


def R(text="", images=None, error=False):
    return {"text": text, "images": images or [], "error": error}


def _num(v, name, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a number")
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ToolError(f"{name} must be between {lo} and {hi}")
    return x


def _end(c):
    return c["start"] + (c.get("dur") or (c["out"] - c["in"]) / (c.get("speed") or 1))


def _fmt_t(s):
    return f"{int(s // 60)}:{s % 60:05.2f}"


def _scene_key(name):
    m = re.match(r"^(.*?)\s*Scene (\d+(?:_\d+)*)\b", name.rsplit(".", 1)[0])
    return (m.group(1).strip(), tuple(int(x) for x in m.group(2).split("_"))) if m else None


def _jpeg(img: Image.Image, q=80) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=q)
    return b.getvalue()


class Tools:
    def __init__(self, ctx):
        self.ctx = ctx

    # ============================================================ helpers
    def state(self):
        st = self.ctx.http.state()
        if st.get("project_name") != self.ctx.project:
            raise ToolError(f"The editor switched to another project ({st.get('project_name')}). This chat belongs to "
                            f"'{self.ctx.project}' — ask them to open it again before continuing.")
        return st

    def assets(self, st=None):
        st = st or self.state()
        return [a for a in st["assets"] if a["path"].startswith(f"projects/{self.ctx.project}/")]

    def find_asset(self, name, st=None):
        n = (name or "").lower().strip()
        al = self.assets(st)
        for a in al:
            if a["name"].lower() == n or a["name"].rsplit(".", 1)[0].lower() == n:
                return a
        cands = [a["name"] for a in al if n and n in a["name"].lower()]
        raise ToolError(f"no file named '{name}' in this project" + (f" (did you mean: {', '.join(cands[:4])}?)" if cands else ""))

    def project_length(self, st):
        cl = st["project"]["clips"]
        return max((_end(c) for c in cl), default=0.0)

    # ============================================================ read tools
    def project_overview(self, a):
        st = self.state()
        p = st["project"]
        fmt = p.get("format", {})
        tracks = []
        for t in p["tracks"]:
            n = sum(1 for c in p["clips"] if c["track"] == t["id"])
            extra = " muted" if t.get("mute") else ""
            tracks.append(f"{t['id']} {t.get('name', '')} ({t['kind']}): {n} clips{extra}" +
                          (f", {t['volume_db']:+.1f} dB" if t.get("volume_db") else ""))
        rows = []
        for x in sorted(self.assets(st), key=lambda x: (x["kind"], x["name"])):
            m = x.get("meta") or {}
            sk = _scene_key(x["name"])
            dims = f" {m.get('w')}×{m.get('h')}" if m.get("w") else ""
            rows.append(f"- {x['name']} · {x['kind']} · {m.get('dur', 0):.1f}s{dims}"
                        f"{' · ' + str(round(m['fps'])) + 'fps' if m.get('fps') else ''}{' · sound' if m.get('has_audio') else ''}"
                        f"{' · ' + x.get('folder', '') if x.get('folder') else ''}")
        tts = [c for c in p["clips"] if c["type"] == "tts"]
        wf = self.ctx.wf.public()
        txt = [f"Project: {st['project_name']} · format {fmt.get('w')}×{fmt.get('h')} {fmt.get('preset', '')} · timeline "
               f"{_fmt_t(self.project_length(st))} · {len(p['clips'])} clips ({len(tts)} narration) · "
               f"{len(p.get('transitions', []))} transitions · {len(p.get('markers', []))} markers",
               f"Workflow stage: {wf['stage']} · approved: {', '.join(s['id'] for s in wf['stages'] if s['approved']) or 'none'}"
               + (f" · needs update: {', '.join(s['id'] for s in wf['stages'] if s['needs_update'])}" if any(s['needs_update'] for s in wf['stages']) else ""),
               "Tracks: " + " | ".join(tracks), f"Files ({len(rows)}):", *rows,
               "Review documents: " + (", ".join(d["path"] + (" (edited by the editor)" if d["edited_by_you"] else "")
                                               for d in self.ctx.wf.list_docs()) or "none")]
        tgt = self.ctx.style.duration_target()
        if tgt:
            txt.append(f"Target duration (style sheet): {tgt}")
        return R("\n".join(txt))

    def timeline(self, a):
        st = self.state()
        t0 = _num(a.get("t0", 0), "t0", 0)
        t1 = _num(a.get("t1", t0 + 60), "t1", 0)
        tracks = set(a.get("tracks") or [])
        names = {x["id"]: x["name"] for x in st["assets"]}
        rows = []
        for c in sorted(st["project"]["clips"], key=lambda c: (c["start"], c["track"])):
            if _end(c) < t0 or c["start"] > t1 or (tracks and c["track"] not in tracks):
                continue
            if c["type"] == "tts":
                what = f"narration ({(c.get('tts') or {}).get('voice')}): “{(c.get('tts') or {}).get('text', '')[:70]}”"
            elif c["type"] == "text":
                cap = (c.get("text") or {}).get("caption")
                what = ("caption: " if cap else "text: ") + f"“{(c.get('text') or {}).get('content', '')[:50]}”"
            else:
                what = names.get(c.get("asset"), c.get("asset", "?"))
                if c.get("in") is not None:
                    what += f" [{c['in']:.2f}–{c['out']:.2f}]"
            sp = c.get("speed") or 1
            vol = c.get("volume_db")
            spd = f" x{sp:.2f}" if abs(sp - 1) > 1e-3 else ""
            lvl = f" {vol:+.1f}dB" if vol else ""
            rows.append(f"{c['id']} {c['track']:3s} {c['start']:7.2f}–{_end(c):7.2f}{spd}{lvl}  {what}")
            if len(rows) >= 220:
                rows.append("… (more — ask for a shorter range)")
                break
        tr = [f"transition {x['type']} {x.get('a')}→{x.get('b')} {x.get('dur')}s" for x in st["project"].get("transitions", [])
              if any(r.startswith((x.get('a') or '-') + ' ') or r.startswith((x.get('b') or '-') + ' ') for r in rows)]
        return R(f"Timeline {t0:.1f}–{t1:.1f} s (id track start–end speed level what):\n" + "\n".join(rows)
                 + ("\n" + "\n".join(tr[:60]) if tr else ""))

    def look_at_footage(self, a):
        names = a.get("clips") or []
        if not names:
            raise ToolError("give clip names")
        frames = int(_num(a.get("frames", 6), "frames", 2, 12))
        st = self.state()
        rows, labels = [], []
        for n in names[:12]:
            x = self.find_asset(n, st)
            if x["kind"] not in ("video", "image"):
                raise ToolError(f"{x['name']} is not a video")
            rows.append(self._clip_row(x, frames))
            labels.append(x["name"])
        imgs = []
        for i in range(0, len(rows), 6):
            part = rows[i:i + 6]
            W = max(r.width for r in part)
            H = sum(r.height for r in part)
            g = Image.new("RGB", (W, H), "black")
            y = 0
            for r in part:
                g.paste(r, (0, y))
                y += r.height
            imgs.append(_jpeg(g, 78))
        self.ctx.activity(f"👀 Looking at {', '.join(labels[:4])}{'…' if len(labels) > 4 else ''}")
        return R(f"Contact sheet(s): one row per clip, {frames} frames evenly spaced, source times in yellow. Clips: "
                 + ", ".join(labels), imgs)

    def _clip_row(self, x, frames):
        cache = MEDIA_CACHE / x["id"] / f"aisheet_{frames}.jpg"
        if cache.exists():
            return Image.open(cache).copy()
        import av
        src = MEDIA_CACHE / x["id"] / "proxy.mp4"
        src = src if src.exists() else ROOT / x["path"]
        dur = float((x.get("meta") or {}).get("dur") or 1)
        th = 150
        tiles = []
        with av.open(str(src)) as c:
            s = c.streams.video[0]
            for k in range(frames):
                t = dur * (k + 0.5) / frames
                c.seek(int(t / s.time_base), stream=s, backward=True)
                for fr in c.decode(s):
                    if fr.time is not None and fr.time >= t - 0.05:
                        im = fr.to_image()
                        im = im.resize((max(1, int(im.width * th / im.height)), th))
                        ImageDraw.Draw(im).text((3, 2), f"{t:.1f}s", fill="yellow")
                        tiles.append(im)
                        break
        label_w = 170
        W = label_w + sum(t.width for t in tiles)
        row = Image.new("RGB", (W, th), (20, 20, 20))
        ImageDraw.Draw(row).text((4, th // 2 - 12), f"{x['name'][:26]}\n{dur:.1f}s", fill="white")
        xx = label_w
        for t in tiles:
            row.paste(t, (xx, 0))
            xx += t.width
        try:
            row.save(cache, "JPEG", quality=80)
        except OSError:
            pass
        return row

    def listen_to_clip(self, a):
        st = self.state()
        x = self.find_asset(a.get("clip"), st)
        if not (x.get("meta") or {}).get("has_audio"):
            return R(f"{x['name']} has no sound.")
        dur = float((x.get("meta") or {}).get("dur") or 0)
        t0 = _num(a.get("t0", 0), "t0", 0)
        t1 = min(dur, _num(a.get("t1", dur), "t1", 0))
        cache = MEDIA_CACHE / x["id"] / "aiwords.json"
        key = f"{t0:.2f}-{t1:.2f}"
        got = {}
        if cache.exists():
            try:
                got = json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                got = {}
        if key not in got:
            self.ctx.activity(f"👂 Listening to {x['name']}")
            from .. import subtitles
            utts = subtitles.transcribe_words(str(ROOT / x["path"]), t0, t1)
            got[key] = [{"t": round(t0 + (u["words"][0]["t0"] if u.get("words") else 0), 2), "lang": u.get("lang"),
                         "text": " ".join(w["w"] for w in u.get("words", [])) or ("(" + (u.get("original") or "") + ")"),
                         "unheard": bool(u.get("unheard"))} for u in utts]
            try:
                cache.write_text(json.dumps(got), encoding="utf-8")
            except OSError:
                pass
        lines = [f"[{u['t']:.1f}s {u.get('lang') or ''}] " + ("(no clear words — sounds / music / mumbling)" if u["unheard"] else u["text"])
                 for u in got[key]]
        return R(f"{x['name']} {t0:.1f}–{t1:.1f}s:\n" + ("\n".join(lines) or "(no speech found)"))

    def look_at_timeline(self, a):
        st = self.state()
        L = self.project_length(st)
        times = [float(t) for t in (a.get("times") or [])]
        if not times:
            t0 = _num(a.get("t0", 0), "t0", 0)
            t1 = min(L, _num(a.get("t1", L), "t1", 0))
            step = _num(a.get("step", max(0.5, (t1 - t0) / 12)), "step", 0.1)
            times = [round(t0 + 0.25 + i * step, 2) for i in range(int(max(1, (t1 - t0) // step)) + 1) if t0 + 0.25 + i * step < t1]
        times = times[:24]
        if not times:
            return R("The timeline is empty.")
        tiles = []
        for t in times:
            r = self.ctx.http.post("/api/snapshot", {"t": t})
            p = ROOT / r["path"]
            im = Image.open(p).convert("RGB")
            im = im.resize((216, int(216 * im.height / im.width)))
            p.unlink(missing_ok=True)
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 70, 22], fill=(0, 0, 0))
            d.text((4, 4), f"{t:.2f}s", fill="yellow")
            tiles.append(im)
        cols = 6
        th = tiles[0].height
        g = Image.new("RGB", (cols * 216, ((len(tiles) + cols - 1) // cols) * th), (30, 30, 30))
        for i, im in enumerate(tiles):
            g.paste(im, ((i % cols) * 216, (i // cols) * th))
        self.ctx.activity(f"🎞 Checking {len(times)} frames of the timeline")
        return R(f"Rendered frames at {', '.join(f'{t:.2f}' for t in times)} s (timeline length {_fmt_t(L)}).", [_jpeg(g)])

    def check_edit(self, a):
        st = self.state()
        p = st["project"]
        names = {x["id"]: x["name"] for x in st["assets"]}
        L = self.project_length(st)
        out = [f"Timeline length {_fmt_t(L)}" + (f" · target {self.ctx.style.duration_target()}" if self.ctx.style.duration_target() else "")]
        vids = sorted([c for c in p["clips"] if c["track"] in ("V1", "V2") and c["type"] == "media"], key=lambda c: c["start"])
        texts = [c for c in p["clips"] if c["type"] == "text"]
        t, holes = 0.0, []
        for c in vids:
            if c["start"] > t + 0.07:
                black_title = any(x["start"] <= t + 0.1 and _end(x) >= c["start"] - 0.1 for x in texts)
                holes.append(f"{t:.2f}–{c['start']:.2f}" + (" (text on black — intended?)" if black_title else ""))
            t = max(t, _end(c))
        out.append("Gaps without picture: " + (", ".join(holes) if holes else "none"))
        last, last_by, order = None, {}, []
        for c in [c for c in vids if c["track"] == "V1"]:
            k = _scene_key(names.get(c.get("asset"), ""))
            if not k:
                continue
            series, num = k
            pv = last_by.get(series)
            if pv and num < pv[1]:
                order.append(f"{names.get(c.get('asset'))} at {c['start']:.1f}s comes after {pv[0]}")
            last_by[series] = (names.get(c.get("asset")), num)
        out.append("Out of file-number order (fine for hooks / recaps / teasers): " + ("; ".join(order[:12]) if order else "none"))
        used = {c.get("asset") for c in p["clips"]}
        unused = [x["name"] for x in self.assets(st) if x["kind"] == "video" and x["id"] not in used]
        out.append("Footage not used: " + (", ".join(unused[:40]) if unused else "none"))
        over = []
        by_tr = {}
        for c in sorted([c for c in p["clips"] if c["type"] == "tts"], key=lambda c: c["start"]):
            pv = by_tr.get(c["track"])
            if pv and c["start"] < _end(pv) - 0.02:
                over.append(f"{c['track']} {c['start']:.2f}s overlaps the previous line")
            by_tr[c["track"]] = c
        out.append("Narration overlaps: " + ("; ".join(over[:10]) if over else "none"))
        out.append(self._ripple_check(p))
        return R("\n".join(out))

    def _ripple_check(self, p):
        """Compare with the newest checkpoint: did the video move while narration/text stayed (a one-track ripple)?"""
        ck = sorted((self.ctx.pdir / "checkpoints").glob("*.json"), key=lambda f: f.stat().st_mtime)
        if not ck:
            return "Sync vs last checkpoint: no checkpoint to compare."
        try:
            old = {c["id"]: c for c in json.loads(ck[-1].read_text(encoding="utf-8"))["clips"]}
        except (OSError, ValueError, KeyError):
            return "Sync vs last checkpoint: couldn't read it."
        v_d, o_d = [], []
        for c in p["clips"]:
            o = old.get(c["id"])
            if not o:
                continue
            d = round(c["start"] - o["start"], 3)
            (v_d if c["track"] in ("V1", "A1") else o_d).append(d)
        moved_v = [d for d in v_d if abs(d) > 0.02]
        moved_o = [d for d in o_d if abs(d) > 0.02]
        if moved_v and not moved_o and len(moved_v) > 3:
            from collections import Counter
            d, n = Counter(moved_v).most_common(1)[0]
            return (f"⚠ Sync vs checkpoint '{ck[-1].stem}': {len(moved_v)} video/footage-sound clips moved (mostly {d:+.2f} s) "
                    f"but narration, text, music and overlays did not — likely a one-track ripple. Propose re-syncing.")
        return f"Sync vs checkpoint '{ck[-1].stem}': OK"

    def detect_beats(self, a):
        x = self.find_asset(a.get("music"))
        from ..beats import analyze_file
        cache = self.ctx.pdir / "docs" / "edit" / "beats" / f"{x['id']}.json"
        if cache.exists():
            b = json.loads(cache.read_text(encoding="utf-8"))
        else:
            self.ctx.activity(f"🥁 Finding the beats of {x['name']}")
            b = analyze_file(str(ROOT / x["path"]))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(b), encoding="utf-8")
        return R(f"{x['name']}: {b['bpm']} BPM, {len(b['beats'])} beats, beat period {60 / b['bpm']:.3f} s. First downbeats: "
                 + ", ".join(f"{t:.2f}" for t in b["downbeats"][:8]) + " s (song time). Saved for the build.")

    # ============================================================ review documents
    def list_docs(self, a):
        d = self.ctx.wf.list_docs()
        return R("\n".join(f"{x['path']} ({x['size']} bytes){' — edited by the editor' if x['edited_by_you'] else ''}" for x in d) or "No documents yet.")

    def read_doc(self, a):
        try:
            r = self.ctx.wf.read_doc(a.get("path"))
        except DocError as e:
            raise ToolError(str(e))
        head = f"{r['path']} (written by {r['written_by']})"
        if r.get("edited_by_you"):
            head += "\nTHE EDITOR EDITED THIS FILE — their version is the source of truth. Their changes vs. your version:\n" + r["your_changes"]
        return R(head + "\n---\n" + r["text"][:60000])

    def write_doc(self, a):
        text = a.get("text") or ""
        if len(text) > 200000:
            raise ToolError("document too long")
        try:
            r = self.ctx.wf.write_doc(a.get("path"), text)
        except DocError as e:
            raise ToolError(str(e))
        self.ctx.activity(f"📝 Wrote {r['path']}", link=r["path"])
        return R(f"Saved {r['path']} ({r['chars']} characters). The editor can open and edit it from the chat.")

    def log_feedback(self, a):
        from .. import changelog as cl
        notes = a.get("notes") or []
        if not notes:
            raise ToolError("give the notes")
        title = a.get("round_title") or "Review round"
        ck = self.ctx.http.post("/api/projects/checkpoint", {"label": f"Before {title}"})["file"]
        cl.new_round(self.ctx.project, title, ck)
        for n in notes:
            cl.add(self.ctx.project, n.get("video", "All"), n.get("item", ""), n.get("decision", "change"),
                   n.get("reason", ""), id=n.get("id"), status="todo")
        self.ctx.activity(f"🗒 Logged {len(notes)} notes in the change log", link="docs/changelog.md")
        return R(f"Logged round '{title}' with {len(notes)} notes (checkpoint before saved). Propose the fixes next.")

    # ============================================================ workflow / UI
    def set_stage(self, a):
        stage = a.get("stage")
        if stage not in STAGE_IDS:
            raise ToolError(f"stage must be one of {', '.join(STAGE_IDS)}")
        names = dict((s["id"], s["label"]) for s in self.ctx.wf.public()["stages"])
        res = self.ctx.propose("stage", f"Approve: {names[stage]}", a.get("summary", ""), a.get("files") or [],
                               actions=["approve", "decline", "change"])
        if res["status"] == "approved":
            self.ctx.wf.approve(stage, note=a.get("summary", ""), files=a.get("files") or [])
            if stage == "style":
                self.ctx.style.sync_from_md()
            return R(f"The editor approved '{names[stage]}'. Next stage: {self.ctx.wf.data['stage']}.")
        return self._declined(res)

    def ask_user(self, a):
        q = a.get("question") or ""
        val = self.ctx.ask("question", {"question": q, "options": (a.get("options") or [])[:8], "allow_text": a.get("allow_text", True)})
        return R(f"The editor answered: {val}")

    def ask_style_round(self, a):
        rid = a.get("round")
        spec = style_mod.round_spec(rid)
        recs = a.get("recommendations") or {}
        unknown = [f for f in recs if f not in {x["id"] for x in spec["fields"]}]
        if unknown:
            raise ToolError(f"unknown choices for this round: {', '.join(unknown)}")
        missing = [x["id"] for x in spec["fields"] if x["id"] not in recs]
        if missing:
            raise ToolError("pre-fill EVERY choice of the round (with a reason); missing: " + ", ".join(missing))
        for f, r in recs.items():
            if not str(r.get("value", "")).strip() or not str(r.get("reason", "")).strip() and not r.get("from_brief"):
                raise ToolError(f"'{f}' needs a value and a one-line reason")
        answers = self.ctx.ask("style_round", {"round": spec, "recommendations": recs,
                                               "samples": a.get("samples") or {}})
        if not isinstance(answers, dict):
            return R(f"The editor didn't answer the round ({answers}).")
        self.ctx.style.set_round(rid, answers.get("values") or {}, recs)
        changed = [f for f, v in (answers.get("values") or {}).items() if str(v).strip() != str(recs.get(f, {}).get("value", "")).strip()]
        note = answers.get("note") or ""
        return R(f"Round '{spec['title']}' answered. Changed by the editor: {', '.join(changed) or 'nothing (all suggestions accepted)'}."
                 + (f" Their note: {note}" if note else "") + f"\nStyle so far:\n{self.ctx.style.summary()}")

    def my_styles(self, a):
        act = a.get("action", "list")
        if act == "list":
            ps = style_mod.list_presets()
            return R("\n".join(f"- {p['name']} ({'my style' if p['mine'] else 'built-in'}){': ' + p.get('note', '') if p.get('note') else ''}"
                               for p in ps))
        if act == "show":
            p = style_mod.get_preset(a.get("name", ""))
            if not p:
                raise ToolError("no such style")
            return R(f"{p['name']} — values to PRE-FILL the rounds (the editor still confirms each round):\n"
                     + "\n".join(f"- {k}: {v}" for k, v in p["values"].items()))
        if act == "save":
            name = (a.get("name") or "").strip()
            if not name:
                raise ToolError("give a name")
            r = style_mod.save_preset(name, self.ctx.style)
            return R(f"Saved the style as '{r['name']}' ({r['fields']} choices). It will be offered first next time.")
        raise ToolError("action must be list, show or save")

    def analyze_reference(self, a):
        from . import reference as ref
        src = (a.get("source") or "").strip()
        tmp = None
        if ref.URL_RE.match(src):
            res = self.ctx.propose("reference", "Download a reference video for analysis",
                                   f"{src}\nIt's used only to measure the style (never as footage) and deleted right after. "
                                   f"Please make sure this respects the platform's terms.", [], actions=["approve", "decline"])
            if res["status"] != "approved":
                return self._declined(res)
            self.ctx.activity("⬇️ Downloading the reference video…")
            try:
                tmp = ref.fetch(src)
            except ref.FetchError as e:
                return R(str(e), error=True)
            path, label = tmp, src
        else:
            x = self.find_asset(src)
            path, label = ROOT / x["path"], x["name"]
        try:
            self.ctx.activity("📐 Measuring the reference style")
            res = ref.analyze(Path(path), label)
        finally:
            if tmp:
                ref.cleanup(tmp)
        n = 1
        while (self.ctx.pdir / "docs" / "edit" / f"reference_{n}.md").exists():
            n += 1
        self.ctx.wf.write_doc(f"edit/reference_{n}.md", res["markdown"])
        self.ctx.activity(f"📝 Wrote docs/edit/reference_{n}.md", link=f"docs/edit/reference_{n}.md")
        return R(f"Measured (saved as docs/edit/reference_{n}.md — add your reading of the contact sheet to it with "
                 f"write_doc to a new name or tell the editor in chat):\n" + json.dumps(res["numbers"], ensure_ascii=False),
                 [res["sheet"]] if res["sheet"] else [])

    def propose_samples(self, a):
        kind = a.get("kind")
        st = self.state()
        clip = self.find_asset(a["clip"], st) if a.get("clip") else None
        if kind in ("looks", "transitions", "luts"):
            r = self.ctx.http.post("/api/previews", {"kind": kind, "asset": clip["id"] if clip else None})
            items = r.get("items") or {}
            want = a.get("options") or list(items)[:5]
            tiles = []
            for oid in want[:6]:
                url = items.get(oid)
                if not url:
                    continue
                p = ROOT / url.replace("/files/", "", 1).split("?")[0]
                if p.exists():
                    im = Image.open(p).convert("RGB")
                    if kind == "transitions":                      # sprite of frames → take the middle frame
                        n = r.get("frames") or 6
                        w = im.width // n
                        im = im.crop((w * (n // 2), 0, w * (n // 2 + 1), im.height))
                    im.thumbnail((260, 460))
                    ImageDraw.Draw(im).rectangle([0, 0, im.width, 20], fill=(0, 0, 0))
                    ImageDraw.Draw(im).text((4, 4), str(oid)[:30], fill="white")
                    tiles.append(im)
            if not tiles:
                return R("No sample could be rendered (no poster frame yet?).", error=True)
            g = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)), (25, 25, 25))
            x = 0
            for t in tiles:
                g.paste(t, (x, 0))
                x += t.width
            data = _jpeg(g)
            self.ctx.show_image(data, f"{kind} samples on {clip['name'] if clip else 'your footage'}")
            return R(f"Showed {len(tiles)} {kind} samples to the editor: {', '.join(want[:6])}.", [data])
        if kind == "captions":
            return self._caption_samples(a, st, clip)
        if kind == "voices":
            text = (a.get("text") or "").strip()[:240]
            voices = a.get("options") or []
            if not text or not voices:
                raise ToolError("give the sample text and the voice names (options)")
            credits = len(text) * len(voices)
            res = self.ctx.propose("credits", f"Voice samples ({len(voices)} voices)",
                                   f"“{text}” read by: {', '.join(voices)}", [], cost=f"≈{credits} ElevenLabs credits",
                                   actions=["approve", "decline"])
            if res["status"] != "approved":
                return self._declined(res)
            made = []
            for v in voices[:6]:
                r = self.ctx.http.post("/api/tts/quick", {"text": text, "voice": v, "tone": a.get("tone", "cheerful")})
                made.append(f"{v}: {r.get('id', 'started')}")
            self.ctx.activity("🔊 Voice samples are being generated — they appear in AI Voice ▸ Try it")
            return R("Voice samples started: " + ", ".join(made) + ". The editor can listen in the AI Voice tab.")
        raise ToolError("kind must be looks, transitions, luts, captions or voices")

    def _caption_samples(self, a, st, clip):
        from ..render import caption as cap
        tpls = self.ctx.http.get("/api/captions/templates")
        tpls = tpls.get("templates", tpls) if isinstance(tpls, dict) else tpls
        want = a.get("options") or [t["id"] for t in tpls][:5]
        words = (a.get("text") or "This is how your captions look").split()[:6]
        base = None
        if clip:
            pv = MEDIA_CACHE / clip["id"] / "poster.jpg"
            if pv.exists():
                base = Image.open(pv).convert("RGB")
        fmt = st["project"].get("format", {})
        W, H = int(fmt.get("w", 1080)), int(fmt.get("h", 1920))
        tiles = []
        for tid in want[:6]:
            t = next((x for x in tpls if x["id"] == tid), None)
            if not t:
                continue
            bg = (base.resize((W, H)) if base else Image.new("RGB", (W, H), (60, 70, 80))).copy()
            c = {"start": 0.0, "dur": 3.0, "type": "text", "text": {"content": " ".join(words), "x": 0.5, "y": 0.7,
                 "caption": {"template": tid, "style": t.get("style", {}),
                             "words": [{"w": w, "t0": i * 0.3, "t1": i * 0.3 + 0.28} for i, w in enumerate(words)]}}}
            try:
                rgba = cap.render_caption(c, 0.95, W, H)
            except Exception:  # noqa: BLE001 — a template the sampler can't draw is skipped
                rgba = None
            if rgba is not None:
                ov = Image.fromarray(rgba, "RGBA")
                bg.paste(ov, (0, 0), ov)
            bg.thumbnail((260, 460))
            ImageDraw.Draw(bg).rectangle([0, 0, bg.width, 20], fill=(0, 0, 0))
            ImageDraw.Draw(bg).text((4, 4), t.get("name", tid)[:30], fill="white")
            tiles.append(bg)
        if not tiles:
            return R("No caption sample could be rendered.", error=True)
        g = Image.new("RGB", (sum(t.width for t in tiles), max(t.height for t in tiles)), (25, 25, 25))
        x = 0
        for t in tiles:
            g.paste(t, (x, 0))
            x += t.width
        data = _jpeg(g)
        self.ctx.show_image(data, "Caption samples")
        return R(f"Showed {len(tiles)} caption templates: {', '.join(want[:6])}.", [data])

    def suggest_covers(self, a):
        times = [float(t) for t in (a.get("times") or [])][:5]
        if not times:
            raise ToolError("give 3–5 timeline times for cover candidates")
        r = self.look_at_timeline({"times": times})
        choice = self.ctx.ask("question", {"question": "Which frame should be the cover?",
                                           "options": [f"{t:.2f} s" for t in times], "allow_text": True})
        m = re.search(r"([\d.]+)", str(choice))
        if not m:
            return R(f"The editor answered: {choice}")
        t = float(m.group(1))
        snap = self.ctx.http.post("/api/snapshot", {"t": t})
        src = ROOT / snap["path"]
        dst = self.ctx.pdir / "exports" / "cover.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        Image.open(src).convert("RGB").save(dst, "JPEG", quality=92)
        src.unlink(missing_ok=True)
        self.ctx.activity("🖼 Saved the cover: exports/cover.jpg")
        return R(f"Cover saved from {t:.2f} s → exports/cover.jpg. (Title text on the cover: add it as a text clip at "
                 f"that time before exporting, with approval, if the editor wants one.)", r["images"])

    def progress(self, a):
        from .. import claude_progress as cp
        act = a.get("action")
        try:
            if act == "start":
                cp.start(a.get("title", "AI Editor"), a.get("steps") or [], a.get("detail", ""))
            elif act == "step":
                cp.step(a.get("id"), a.get("status"), a.get("detail"), a.get("frac"), a.get("log"))
            elif act == "finish":
                cp.finish(a.get("detail", ""))
        except Exception as e:  # noqa: BLE001 — progress display is best effort
            return R(f"(progress not updated: {e})")
        return R("ok")

    # ============================================================ proposals (change the video / spend credits)
    def _declined(self, res):
        st = res["status"]
        if st == "change":
            return R(f"The editor wants changes before approving: {res.get('value')}. Adjust and propose again.")
        if st == "declined":
            return R("The editor declined. Nothing was changed. Ask what they'd like instead.")
        return R(f"Not approved ({st}). Nothing was changed.")

    def edit(self, a):
        ops = a.get("ops") or []
        if not ops or not isinstance(ops, list):
            raise ToolError("give ops")
        bad = [o.get("op") for o in ops if o.get("op") not in ALLOWED_OPS]
        if bad:
            raise ToolError(f"these operations are not allowed for the AI Editor: {', '.join(map(str, bad))}")
        summary = (a.get("summary") or "").strip()
        if not summary:
            raise ToolError("give a plain-language summary of the change")
        st = self.state()
        L = self.project_length(st)
        details = a.get("details") or [f"{o['op']} {json.dumps(o.get('args', {}), ensure_ascii=False)[:140]}" for o in ops][:40]
        res = self.ctx.propose("edit", summary, a.get("why", ""), details,
                               length=(a.get("length_change") or f"timeline now {_fmt_t(L)}"),
                               actions=["approve", "decline", "change"])
        if res["status"] != "approved":
            return self._declined(res)
        self.ctx.http.post("/api/projects/checkpoint", {"label": f"Before AI: {summary[:40]}"})
        try:
            r = self.ctx.http.batch(ops, f"AI: {summary[:60]}")
        except RuntimeError as e:
            return R(f"The edit failed and nothing was applied: {e}", error=True)
        L2 = self.project_length(r if "project" in r else self.state())
        self.ctx.activity(f"✂️ Applied: {summary} (one Undo step)")
        return R(f"Applied as one Undo step. Created/affected ids: {json.dumps(r.get('result'))[:600]}. "
                 f"Timeline length {_fmt_t(L)} → {_fmt_t(L2)}. Check it (look_at_timeline / check_edit).")

    def undo_last(self, a):
        h = self.state().get("history") or {}
        res = self.ctx.propose("edit", "Undo the last change", f"Undo: {h.get('undo') or 'last step'}", [],
                               actions=["approve", "decline"])
        if res["status"] != "approved":
            return self._declined(res)
        r = self.ctx.http.post("/api/undo", {})
        return R(f"Undone: {r.get('label')}")

    def go_back_to_checkpoint(self, a):
        name = a.get("checkpoint") or ""
        cks = sorted((self.ctx.pdir / "checkpoints").glob("*.json"), key=lambda f: -f.stat().st_mtime)
        target = next((c for c in cks if name and name.lower() in c.stem.lower()), None)
        if not target:
            return R("Checkpoints: " + ", ".join(c.stem for c in cks[:15]) + ". Which one?")
        res = self.ctx.propose("edit", f"Go back to checkpoint '{target.stem}'",
                               "The timeline returns to how it was then (a checkpoint of now is saved first).", [],
                               actions=["approve", "decline"])
        if res["status"] != "approved":
            return self._declined(res)
        self.ctx.http.post("/api/projects/checkpoint", {"label": "Before going back (AI)"})
        self.ctx.http.post("/api/projects/revert", {"file": target.name})
        return R(f"Back to '{target.stem}'.")

    def export(self, a):
        kind = a.get("kind", "draft")
        if kind not in ("draft", "final"):
            raise ToolError("kind must be draft or final")
        st = self.state()
        L = self.project_length(st)
        title = (a.get("title") or st["project_name"]).strip()
        no_music = bool(a.get("also_no_music")) and kind == "final"
        est = int(L * 3.4 / 60) + 1
        res = self.ctx.propose("export", f"Export {'FINAL' if kind == 'final' else 'a draft'}: {title}",
                               ("Files: “" + title + " - FINAL.mp4”" + (" + “(no music)”" if no_music else "") +
                                "; earlier finals move to exports/draft/") if kind == "final" else "Saved in exports/draft/",
                               [], length=f"{_fmt_t(L)} · about {est * (2 if no_music else 1)} min to render",
                               actions=["approve", "decline"])
        if res["status"] != "approved":
            return self._declined(res)
        from . import exporting
        out = exporting.run(self.ctx, kind, title, no_music)
        return R(out)

    def make_narration(self, a):
        gate = self.ctx.wf.gate("make_narration")
        if gate:
            raise ToolError(gate)
        from . import narration
        return narration.make(self.ctx, a)

    def build_from_plan(self, a):
        gate = self.ctx.wf.gate("build_from_plan")
        if gate:
            raise ToolError(gate)
        from . import planbuild
        return planbuild.build(self.ctx, a, test=False)

    def style_test(self, a):
        gate = self.ctx.wf.gate("style_test")
        if gate:
            raise ToolError(gate)
        from . import planbuild
        return planbuild.build(self.ctx, a, test=True)


# ================================================================ tool definitions (sent to Claude)
def _obj(props, req=()):
    return {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}


S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
ARR = lambda item: {"type": "array", "items": item}  # noqa: E731
FREE = {"type": "object", "additionalProperties": True}

DEFS = [
    ("project_overview", "read", "Overview of the open project: format, timeline length, tracks, ALL files (name, kind, length, size, fps, sound), workflow stage, review documents, target duration.", _obj({})),
    ("timeline", "read", "Compact table of the timeline clips between t0 and t1 seconds (ids, tracks, times, speed, level, file/text).", _obj({"t0": N, "t1": N, "tracks": ARR(S)})),
    ("look_at_footage", "read", "Contact sheets of source clips (one row per clip, evenly spaced frames with source times) as images. Use before writing a script or plan.", _obj({"clips": ARR(S), "frames": N}, ["clips"])),
    ("listen_to_clip", "read", "Transcript (Whisper) of a clip's speech with times; non-speech is reported as such.", _obj({"clip": S, "t0": N, "t1": N}, ["clip"])),
    ("look_at_timeline", "read", "Rendered frames of the TIMELINE (the edit) at given times or every `step` seconds in t0–t1, as one image (max 24 frames). Use to check your work.", _obj({"times": ARR(N), "t0": N, "t1": N, "step": N})),
    ("check_edit", "read", "Checks the edit: length vs target, gaps without picture, file-number order, unused footage, narration overlaps, one-track-ripple desync vs the last checkpoint.", _obj({})),
    ("detect_beats", "read", "Tempo, beats and downbeats of a music file in the project (cached for the build).", _obj({"music": S}, ["music"])),
    ("list_docs", "read", "List the review documents in the project's docs/ (and which ones the editor edited).", _obj({})),
    ("read_doc", "read", "Read a review document (docs/…md). If the editor edited it, you get their changes — their version is the source of truth.", _obj({"path": S}, ["path"])),
    ("write_doc", "doc", "Create or update a review document in docs/ (script_vN.md, script_log.md, edit_plan.md, …). Never overwrites a file the editor wrote or edited — then write a new version file.", _obj({"path": S, "text": S}, ["path", "text"])),
    ("log_feedback", "doc", "Log a review round in the change log BEFORE editing: each note with an id, the item, your decision and reason. Saves a checkpoint.", _obj({"round_title": S, "notes": ARR(_obj({"id": S, "item": S, "decision": S, "reason": S, "video": S}, ["item"]))}, ["notes"])),
    ("set_stage", "proposal", "Ask the editor to approve a workflow stage (brief, script, style, style_test, plan, narration, build, review, export). Only when that stage's work is done and shown.", _obj({"stage": S, "summary": S, "files": ARR(S)}, ["stage", "summary"])),
    ("ask_user", "ui", "Ask the editor a question with option buttons (and free text).", _obj({"question": S, "options": ARR(S), "allow_text": B}, ["question"])),
    ("ask_style_round", "ui", "One round of the creative style (round: goal | story | look_sound | text_brand). Pre-fill EVERY choice: {field: {value, reason, options:[alternatives], from_brief}}. Optional samples: {field: 'what was shown'}.", _obj({"round": S, "recommendations": {"type": "object", "additionalProperties": _obj({"value": S, "reason": S, "options": ARR(S), "from_brief": B}, ["value"])}, "samples": {"type": "object", "additionalProperties": S}}, ["round", "recommendations"])),
    ("my_styles", "read", "The editor's saved styles and the built-in presets: action list | show (name) | save (name = save the current style sheet).", _obj({"action": S, "name": S}, ["action"])),
    ("analyze_reference", "read", "Measure the style of a reference video: a file name in the project, or a TikTok / Reels / YouTube link (asks the editor first; used for analysis only, deleted after). Returns numbers + a contact sheet and saves docs/edit/reference_N.md.", _obj({"source": S}, ["source"])),
    ("propose_samples", "ui", "Show samples on the editor's own footage: kind looks | luts | transitions | captions (free), voices (credits → approval). options = ids/names to show (≈5), clip = a project file for the background, text = caption / voice sample text.", _obj({"kind": S, "options": ARR(S), "clip": S, "text": S, "tone": S}, ["kind"])),
    ("suggest_covers", "ui", "Show 3–5 timeline frames as cover candidates; the editor picks one → exports/cover.jpg.", _obj({"times": ARR(N)}, ["times"])),
    ("progress", "ui", "Update the progress pop-up for long jobs: action start (title, steps:[{id,title,est}]) | step (id, status, detail, frac, log) | finish.", _obj({"action": S, "title": S, "steps": ARR(FREE), "id": S, "status": S, "detail": S, "frac": N, "log": S}, ["action"])),
    ("edit", "proposal", "Propose editor operations as ONE change (shown to the editor; runs only after Approve, as one Undo step). ops: [{op, args}] from the allowed list. Give a plain summary, why, and the expected length change. A ripple only moves one track — include the moves for the other tracks.", _obj({"summary": S, "why": S, "ops": ARR(_obj({"op": S, "args": FREE}, ["op"])), "details": ARR(S), "length_change": S}, ["summary", "ops"])),
    ("undo_last", "proposal", "Propose undoing the last change.", _obj({})),
    ("go_back_to_checkpoint", "proposal", "Propose returning the timeline to a saved checkpoint (by name).", _obj({"checkpoint": S})),
    ("make_narration", "proposal", "Generate the AI narration for the approved script (shows the lines and credit estimate first; runs after Approve). script = docs path of the approved script; scenes = which scene headings (empty = all); voices = {script name: voice name in the library}; emotion 0–1.", _obj({"script": S, "scenes": ARR(S), "voices": {"type": "object", "additionalProperties": S}, "emotion": N, "version": S}, ["script"])),
    ("style_test", "proposal", "Build a 15–20 s style test of ONE section with the approved style, render a preview to exports/draft/, then restore the timeline. plan = the same format as build_from_plan but only that section.", _obj({"plan": FREE, "label": S}, ["plan"])),
    ("build_from_plan", "proposal", "Build the timeline from the approved edit plan (runs after Approve; clears the timeline first; checkpoint saved). plan = {settings:{...}, items:[{type: music|typed|logos|beat|fade_out, ...}]} — the plan format in section 9 of your instructions.", _obj({"plan": FREE, "summary": S}, ["plan"])),
    ("export", "proposal", "Export: kind draft (→ exports/draft/) or final (→ '<title> - FINAL.mp4', earlier finals → draft/), also_no_music for a no-music copy. Runs after Approve.", _obj({"kind": S, "title": S, "also_no_music": B}, ["kind"])),
]
TOOL_KINDS = {n: k for n, k, _, _ in DEFS}


def api_tools() -> list[dict]:
    """Tool list for the Claude API (stable order → cacheable)."""
    return [{"name": n, "description": d, "input_schema": s} for n, _, d, s in DEFS]
