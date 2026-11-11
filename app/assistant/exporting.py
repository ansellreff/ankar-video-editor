"""Exports for the AI Editor (after Approve): drafts → exports/draft/; finals → "<title> - FINAL.mp4" (+ "(no music)"),
earlier finals → exports/draft/ ("earlier FINAL (date)"). Every final is checked: length, format, loudness/peak, music
really removed (no-music copy), no black frames outside intended black text screens."""
from __future__ import annotations

import re
import time
from pathlib import Path


def _wait(ctx, label):
    time.sleep(1.0)
    while True:
        j = ctx.http.state()["export_job"]
        if not j["running"]:
            return j.get("last") or {}
        if ctx.stop.is_set():
            ctx.http.post("/api/export/cancel", {})
        p = j.get("progress") or {}
        ctx.svc.emit(ctx.chat, "progress", text=f"{label}: {p.get('stage', '')} {round(100 * float(p.get('value') or 0))}%")
        time.sleep(3)


def _render(ctx, quality="high", no_music=False, label="Rendering"):
    st = ctx.http.state()
    music = [t for t in st["project"]["tracks"] if t["kind"] == "audio" and (t["id"] == "A2" or t.get("name") in ("Music", "Music 2"))]
    if no_music:
        for t in music:
            ctx.http.post("/api/op", {"op": "set_track", "args": {"id": t["id"], "patch": {"mute": True}}, "label": "Mute music for export"})
    try:
        ctx.http.post("/api/export", {"quality": quality})
        return _wait(ctx, label)
    finally:
        if no_music:
            for t in music:
                ctx.http.post("/api/op", {"op": "set_track", "args": {"id": t["id"], "patch": {"mute": False}}, "label": "Unmute music"})


def _dark_ranges(path: Path) -> list[tuple[float, float]]:
    import av
    import numpy as np
    dark = []
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        nxt = 0.5
        for fr in c.decode(s):
            if fr.time is None or fr.time < nxt:
                continue
            nxt = fr.time + 1.0
            if fr.to_ndarray(format="gray", width=64, height=114).mean() < 8:
                dark.append(round(float(fr.time), 1))
    rng = []
    for t in dark:
        if rng and t - rng[-1][1] <= 1.05:
            rng[-1][1] = t
        else:
            rng.append([t, t])
    return [(a, b) for a, b in rng]


def run(ctx, kind: str, title: str, no_music: bool) -> str:
    from ..render.compositor import file_drafts
    ex = ctx.pdir / "exports"
    draft = ex / "draft"
    draft.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]+', "", title).strip() or "Video"
    if kind == "draft":
        last = _render(ctx, "high", False, "Draft")
        if not last.get("file"):
            return f"The export didn't finish ({last.get('error') or 'cancelled'})."
        file_drafts(ex)
        ctx.activity(f"🎬 Draft exported: exports/draft/{last['file']}")
        return (f"Draft: exports/draft/{last['file']} · {last.get('seconds', '?')} s render · {last.get('lufs')} LUFS, "
                f"peak {last.get('peak_db')} dB. Check it with the editor.")
    file_drafts(ex)                                           # earlier vNN drafts → draft/
    stamp = time.strftime("%Y-%m-%d %H%M")
    for f in ex.glob(f"{safe} - FINAL*"):                     # earlier finals → draft/
        f.replace(draft / f.name.replace(" - FINAL", f" - earlier FINAL ({stamp})"))
    out = []
    for nm, quiet in [(f"{safe} - FINAL", False)] + ([(f"{safe} - FINAL (no music)", True)] if no_music else []):
        last = _render(ctx, "high", quiet, nm)
        if not last.get("file"):
            out.append(f"{nm}: the export didn't finish ({last.get('error') or 'cancelled'})")
            break
        src = ex / last["file"]
        dst = ex / f"{nm}.mp4"
        src.replace(dst)
        snap = ex / f"{Path(last['file']).stem}.project.json"
        if snap.exists():
            snap.replace(ex / f"{nm}.project.json")
        import av
        with av.open(str(dst)) as c:
            dur = c.duration / 1e6
            v = c.streams.video[0]
            fmt = f"{v.codec_context.width}×{v.codec_context.height} {float(v.average_rate):.0f} fps"
        dark = _dark_ranges(dst)
        out.append(f"{dst.name}: {dur:.1f} s · {fmt} · {last.get('lufs')} LUFS, peak {last.get('peak_db')} dB · "
                   f"near-black seconds: {dark or 'none'}")
        ctx.activity(f"🎬 Exported {dst.name}")
    tgt = ctx.style.duration_target()
    return ("Final export done (earlier finals moved to exports/draft/):\n" + "\n".join(out)
            + (f"\nTarget duration: {tgt}" if tgt else "") + "\nTell the editor which file to post and anything to check by eye "
            "(near-black seconds are fine if they are intended black text screens).")
