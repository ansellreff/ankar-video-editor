"""build_from_plan / style_test: the approved edit plan (JSON) → the builder engine → the live timeline.

Plan format:
{"settings": {"look": "clean_natural" | null, "caption": "karaoke_pill" | null, "logo": "<logo strip file>" | null,
              "colors": {"Name": "#hex"}, "footage_db": -10.46, "breathe": 1.5, "big_logo": ["<file>"]},
 "items": [
   {"type": "music", "file": "<song file>", "at": 0, "src": 0, "db": -8, "fade_in": 0.8},          # at null = now
   {"type": "typed", "line1": "Friday, October 30th 2026", "line2": "05:00 PM", "length": 3.4, "full": false},
   {"type": "logos"},                                                                                # logo strip from here
   {"type": "beat", "shots": [{"clip": "Scene 3_9_2", "from": 4.6, "dur": null, "mode": "fill|native|blur", "x": 0,
                               "speed": 1, "weight": 1, "night": false, "zoom": 1, "keep_sound": false, "crop": null}],
    "lines": ["s03_01"], "min": 0, "lead": 0.25, "tail": 0.45, "breathe": null, "transition": "whip_pan", "tdur": 0.4,
    "texts": [{"content": "SANTORINI", "at": 0.3, "dur": 2.6, "kind": "tag|name|hook|big|sub", "y": 0.205, "color": "#hex"}],
    "sfx": [["whoosh_2", -0.15, -12]], "logo_pop": null, "snap": true, "line_at": {"s03_02": 9.58},
    "cut_at_lines": false, "exact_cuts": false, "free_order": false, "song": null | ["<file or null>", 0.11]},
   {"type": "fade_out", "dur": 0.25}]}
Lines = ids from docs/edit/narration.json (make_narration)."""
from __future__ import annotations

import json
import time


def to_edl(plan: dict):
    from scripts.having_fun.builder import Beat, FadeOut, Mark, Music, S, Typed
    items = plan.get("items") or []
    if not items:
        raise ValueError("the plan has no items")
    edl = []
    for k, it in enumerate(items):
        t = it.get("type")
        if t == "music":
            edl.append(Music(it["file"], at=it.get("at"), src=float(it.get("src", 0)), db=float(it.get("db", -8)),
                             fade_in=float(it.get("fade_in", 0.8))))
        elif t == "typed":
            edl.append(Typed(it.get("line1", ""), it.get("line2", ""), float(it.get("length", 3.0)), bool(it.get("full"))))
        elif t == "logos":
            edl.append(Mark("logos"))
        elif t == "fade_out":
            edl.append(FadeOut(float(it.get("dur", 1.0))))
        elif t == "beat":
            shots = []
            for s in it.get("shots") or []:
                shots.append(S(s["clip"], float(s.get("from", 0)), d=s.get("dur"), mode=s.get("mode", "fill"),
                               x=float(s.get("x", 0)), speed=float(s.get("speed", 1)), db=float(s.get("db", -14)),
                               w=float(s.get("weight", 1)), night=bool(s.get("night")), zoom=float(s.get("zoom", 1)),
                               keep_sound=bool(s.get("keep_sound")), crop=s.get("crop")))
            if not shots:
                raise ValueError(f"item {k}: a beat needs at least one shot")
            song = it.get("song")
            edl.append(Beat(shots=shots, lines=list(it.get("lines") or []), min=float(it.get("min", 0)),
                            lead=float(it.get("lead", 0.25)), tail=float(it.get("tail", 0.45)), breathe=it.get("breathe"),
                            trans=it.get("transition"), tdur=float(it.get("tdur", 0.5)), texts=list(it.get("texts") or []),
                            sfx=[tuple(x) for x in it.get("sfx") or []], logo_pop=it.get("logo_pop"),
                            snap=bool(it.get("snap", True)), line_at=it.get("line_at"),
                            cut_at_lines=bool(it.get("cut_at_lines")), exact_cuts=bool(it.get("exact_cuts")),
                            free_order=bool(it.get("free_order")), song=tuple(song) if song else None))
        else:
            raise ValueError(f"item {k}: unknown type {t!r} (music, typed, logos, beat, fade_out)")
    return edl


def estimate(edl, narr: dict, breathe: float) -> float:
    from scripts.having_fun.builder import Beat, Typed
    total = 0.0
    for it in edl:
        if isinstance(it, Typed):
            total += it.length
        elif isinstance(it, Beat):
            lens = [max((x["dur"] for x in narr.get(l, [{"dur": 0}])), default=0) for l in it.lines]
            narr_len = (it.lead + sum(lens) + 0.14 * max(0, len(lens) - 1)) if lens else 0
            br = it.breathe if it.breathe is not None else (breathe if it.lines else 0)
            fixed = sum(s.d for s in it.shots if s.d)
            total += max(it.min, narr_len + it.tail + br, fixed + (0.8 if any(s.d is None for s in it.shots) else 0))
    return total


def build(ctx, a: dict, test: bool):
    from scripts import claude_progress as cp
    from scripts.having_fun import api as hapi
    from scripts.having_fun.builder import Builder
    from .tools import R, ToolError, _fmt_t
    plan = a.get("plan") or {}
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except ValueError:
            raise ToolError("plan must be JSON")
    try:
        edl = to_edl(plan)
    except (ValueError, KeyError, TypeError) as e:
        raise ToolError(f"plan problem: {e}")
    hapi.URL = ctx.http.base                                     # the builder talks to this server
    cp.URL = ctx.http.base
    st = plan.get("settings") or {}
    picks = {"look": st.get("look"), "caption": st.get("caption")}
    opts = {"edit_dir": str(ctx.pdir / "docs" / "edit"), "footage_db": float(st.get("footage_db", -10.46)),
            "breathe": float(st.get("breathe", 1.5)), "colors": st.get("colors") or {},
            "logo_asset": st.get("logo"), "big_logo_assets": st.get("big_logo") or [], "shared_narration": False}
    b = Builder(ctx.project, picks, edl, "AI Editor", "ai_build", opts)
    missing, order, unused = b.check()
    if missing:
        return R("The plan can't be built yet — missing: " + "; ".join(missing), error=True)
    est = estimate(edl, b.narr, opts["breathe"])
    tgt = ctx.style.duration_target()
    nb = sum(1 for x in edl if type(x).__name__ == "Beat")
    nshots = sum(len(x.shots) for x in edl if type(x).__name__ == "Beat")
    nlines = sum(len(x.lines) for x in edl if type(x).__name__ == "Beat")
    title = ("Style test: " + (a.get("label") or "one section")) if test else ("Build the timeline: " + (a.get("summary") or "the approved plan"))
    summary = (("Builds this section on the timeline, renders a short preview to exports/draft/, then puts the timeline "
                "back exactly as it was." if test else
                "Clears the timeline and builds the approved plan live (a checkpoint is saved first; one click back with Undo / checkpoint).")
               + (f"\nOrder notes: {'; '.join(order[:5])}" if order else ""))
    res = ctx.propose("build", title, summary, [f"{nb} beats · {nshots} shots · {nlines} narration lines"],
                      length=f"≈{_fmt_t(est)} estimated" + (f" · target {tgt}" if tgt and not test else ""),
                      actions=["approve", "decline", "change"])
    if res["status"] != "approved":
        from .tools import Tools
        return Tools(ctx)._declined(res)
    ck = ctx.http.post("/api/projects/checkpoint", {"label": "Before AI style test" if test else "Before AI build"})["file"]
    cp.start("AI Editor: " + ("style test" if test else "build"), [{"id": "ai_build", "title": title, "est": 300 if test else 900}])
    cp.step("ai_build", "active")
    ctx.activity("🛠 Building on the timeline…")
    t0 = time.time()
    try:
        b.run()
    except SystemExit as e:
        return R(str(e), error=True)
    cp.step("ai_build", "done")
    built = max((c["start"] + (c.get("dur") or (c["out"] - c["in"]) / (c.get("speed") or 1))
                 for c in ctx.http.state()["project"]["clips"]), default=0.0)
    holes = getattr(b, "holes", [])
    if not test:
        cp.finish("Built")
        return R(f"Built in {time.time() - t0:.0f} s: timeline {_fmt_t(built)}" + (f" (target {tgt})" if tgt else "")
                 + (f". ⚠ gaps without picture: {holes}" if holes else ". No gaps.")
                 + "\nNow check it (look_at_timeline, check_edit) and report with a short Suggestions list.")
    from .exporting import _render
    last = _render(ctx, "draft", False, "Style test")
    n = 1
    draft = ctx.pdir / "exports" / "draft"
    draft.mkdir(parents=True, exist_ok=True)
    while (draft / f"style_test_{n}.mp4").exists():
        n += 1
    out = None
    if last.get("file"):
        src = ctx.pdir / "exports" / last["file"]
        out = draft / f"style_test_{n}.mp4"
        src.replace(out)
        snap = src.with_suffix(".project.json")
        if snap.exists():
            snap.replace(draft / f"style_test_{n}.project.json")
    ctx.http.post("/api/projects/revert", {"file": ck})
    cp.finish("Style test ready")
    if out:
        ctx.activity(f"🎬 Style test preview: exports/draft/{out.name} (open it from Export ▸ Versions)")
    return R((f"Style test rendered → exports/draft/{out.name} ({_fmt_t(built)}); the timeline is back as it was. "
              if out else "The style test preview didn't render; the timeline is back as it was. ")
             + "Ask the editor to watch it and approve the feel (set_stage style_test) or say what to change.")
