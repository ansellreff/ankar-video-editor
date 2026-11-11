"""make_narration: the approved script → AI narration lines (ElevenLabs Eleven v4 Text to Dialogue).

Each scene is performed in one go (natural conversation), every line is cut at the quietest point and checked with
Whisper; a failed line gets a new take of the scene (seeds 7–10), then a take of that line alone with the previous
line as context. Result: projects/<name>/docs/edit/narration.json with stable ids s<scene>_<line> (the builder reads
it). Shows the lines + credit estimate first and runs only after Approve."""
from __future__ import annotations

import json
import re
import time

from ..paths import GENERATED_NARRATION, VOICES, rel

LINE = re.compile(r"^\$([^$]+)\$\s*(?:\{(\w+)\})?\s*(.+?)\s*$")
TAGS = re.compile(r"\s*\[((?:[A-Z0-9]{1,6}\s*)+)\]\s*$")
MODEL = "eleven_v4"


def parse_script(text: str) -> list[dict]:
    """→ scenes [{index, title, lines:[{k, speakers, tone, text, versions}]}] from the script format."""
    scenes, cur = [], None
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("## "):
            cur = {"index": len(scenes) + 1, "title": s[3:].strip(), "lines": []}
            scenes.append(cur)
            continue
        m = LINE.match(s)
        if not m:
            continue
        if cur is None:
            cur = {"index": 1, "title": "Scene", "lines": []}
            scenes.append(cur)
        body = re.sub(r"\s*⚠.*$", "", m.group(3))
        body = re.sub(r"\s*\*\(same as before\)\*\s*", " ", body).strip()
        versions = []
        tm = TAGS.search(body)
        if tm:
            versions = tm.group(1).split()
            body = body[:tm.start()].strip()
        speakers = [x.strip() for x in m.group(1).split("&") if x.strip()]
        cur["lines"].append({"k": len(cur["lines"]) + 1, "speakers": speakers, "tone": m.group(2) or "cheerful",
                             "text": body, "versions": versions})
    return [sc for sc in scenes if sc["lines"]]


def voice_ids() -> dict:
    out = {}
    if VOICES.exists():
        for d in VOICES.iterdir():
            try:
                j = json.loads((d / "voice.json").read_text(encoding="utf-8"))
                if (j.get("elevenlabs") or {}).get("id"):
                    out[d.name] = j["elevenlabs"]["id"]
            except (OSError, ValueError):
                continue
    return out


def make(ctx, a: dict):
    from .. import config
    from .tools import R, ToolError
    try:
        doc = ctx.wf.read_doc(a.get("script", ""))
    except Exception as e:  # noqa: BLE001
        raise ToolError(str(e))
    scenes = parse_script(doc["text"])
    want = [w.lower() for w in (a.get("scenes") or [])]
    if want:
        scenes = [sc for sc in scenes if any(w in sc["title"].lower() for w in want)]
    ver = (a.get("version") or "").strip()
    if ver:
        for sc in scenes:
            sc["lines"] = [ln for ln in sc["lines"] if not ln["versions"] or ver in ln["versions"]]
        scenes = [sc for sc in scenes if sc["lines"]]
    if not scenes:
        raise ToolError("no narration lines found ($Name$ {tone} text) in that script / scenes")
    vmap = a.get("voices") or {}
    vids = voice_ids()
    names = sorted({sp for sc in scenes for ln in sc["lines"] for sp in ln["speakers"]})
    missing = [n for n in names if vmap.get(n, n) not in vids]
    if missing:
        raise ToolError(f"no ElevenLabs voice for: {', '.join(missing)}. Voices in the library: {', '.join(vids) or 'none'} "
                        f"(pass voices={{script name: library voice}}, or make one in AI Voice ▸ Voice from Video)")
    key = config.get_secret("elevenlabs_api_key")
    if not key:
        raise ToolError("No ElevenLabs key — the editor can add it in the AI Voice tab (settings).")
    emotion = max(0.0, min(1.0, float(a.get("emotion", 0.2))))
    chars = sum(len(ln["text"]) * len(ln["speakers"]) for sc in scenes for ln in sc["lines"])
    nlines = sum(len(sc["lines"]) for sc in scenes)
    details = [f"{sc['title']}: {len(sc['lines'])} lines" for sc in scenes][:30]
    sample = "\n".join(f"- ${' & '.join(ln['speakers'])}$ {{{ln['tone']}}} {ln['text']}" for ln in scenes[0]["lines"][:6])
    res = ctx.propose("credits", f"Generate the narration: {nlines} lines in {len(scenes)} scenes",
                      f"From {doc['path']} (your version) · voices: " + ", ".join(f"{n} → {vmap.get(n, n)}" for n in names)
                      + f" · emotion {emotion}\n{sample}", details,
                      cost=f"≈{int(chars * 1.3):,} ElevenLabs credits ({chars:,} characters + retakes)",
                      actions=["approve", "decline", "change"])
    if res["status"] != "approved":
        from .tools import Tools
        return Tools(ctx)._declined(res)
    from ..subtitles import _get_model
    from ..tts import dialogue
    from ..tts import elevenlabs as el
    from ..tts.linecut import check, cut_line
    from ..tts.manager import SR, normalize, save_wav
    try:
        used0 = el.account(key).get("used")
    except Exception:  # noqa: BLE001
        used0 = None
    whisper = _get_model()
    out_file = ctx.pdir / "docs" / "edit" / "narration.json"
    narr = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
    stab = dialogue.stability_for(emotion)
    report = []
    for si, sc in enumerate(scenes):
        if ctx.stop.is_set():
            break
        ctx.activity(f"🎙 Narration: {sc['title']} ({len(sc['lines'])} lines)")
        turns, owners = [], []
        for ln in sc["lines"]:
            for who in ln["speakers"]:
                turns.append({"voice_id": vids[vmap.get(who, who)], "text": dialogue.tag(ln["text"], ln["tone"], emotion),
                              "display": ln["text"]})
                owners.append((ln, who))
        best = [None] * len(owners)
        for seed in (7, 8, 9, 10):
            todo = [i for i, b in enumerate(best) if b is None]
            if not todo:
                break
            r = dialogue.generate(key, turns, model=MODEL, stability=stab, seed=seed)
            got = {x["i"]: x for x in r["lines"]}
            for i in todo:
                seg = got.get(i)
                if not seg or not seg["words"]:
                    continue
                s, e = seg["words"][0]["t0"], seg["words"][-1]["t1"]
                pe = got[i - 1]["words"][-1]["t1"] if i and got.get(i - 1) and got[i - 1]["words"] else None
                ns = got[i + 1]["words"][0]["t0"] if got.get(i + 1) and got[i + 1]["words"] else None
                y, origin = cut_line(r["audio"], r["sr"], s, e, pe, ns)
                words = [{"w": w["w"], "t0": round(w["t0"] - origin, 3), "t1": round(w["t1"] - origin, 3)} for w in seg["words"]]
                ok, heard, probs = check(whisper, y, r["sr"], owners[i][0]["text"], words)
                if ok:
                    best[i] = (y, words, heard, seed)
        for i, b in enumerate(best):                     # still failing → that line alone, previous line as context
            if b is not None:
                continue
            ln, who = owners[i]
            prev = owners[i - 1][0]["text"] if i else None
            for seed in (21, 22, 23):
                r = dialogue.generate(key, [turns[i]], model=MODEL, stability=stab, seed=seed, previous_text=prev)
                seg = (r["lines"] or [None])[0]
                if not seg or not seg["words"]:
                    continue
                y, origin = cut_line(r["audio"], r["sr"], seg["words"][0]["t0"], seg["words"][-1]["t1"])
                words = [{"w": w["w"], "t0": round(w["t0"] - origin, 3), "t1": round(w["t1"] - origin, 3)} for w in seg["words"]]
                ok, heard, probs = check(whisper, y, r["sr"], ln["text"], words)
                if ok or seed == 23:
                    best[i] = (y, words, heard + ("" if ok else "  ⚠ check by ear"), seed)
                    break
        prev_text = None
        for i, ((ln, who), b) in enumerate(zip(owners, best)):
            lid = f"s{sc['index']:02d}_{ln['k']:02d}"
            if b is None:
                report.append(f"{lid} {who}: FAILED — no usable take")
                continue
            y, words, heard, seed = b
            f = GENERATED_NARRATION / f"ai_{ctx.project[:20]}_{lid}_{who[:10]}_s{seed}.wav".replace(" ", "_")
            save_wav(f, normalize(y))
            dur = round(len(y) / SR, 3)
            entry = {"speaker": who, "file": rel(f), "dur": dur, "tone": ln["tone"], "text": ln["text"], "words": words,
                     "mode": "dialogue", "model": MODEL, "emotion": emotion, "ctx_prev": (prev_text or "")[-100:] or None,
                     "engine": "elevenlabs", "heard": heard}
            lst = [x for x in narr.get(lid, []) if x.get("speaker") != who] if ln["speakers"].index(who) else []
            narr[lid] = lst + [entry]
            prev_text = ln["text"]
            report.append(f"{lid} {who:10s} {dur:5.2f}s  “{ln['text'][:70]}”  (heard: {heard[:60]})")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(narr, indent=1, ensure_ascii=False), encoding="utf-8")
    time.sleep(3)
    try:
        used = el.account(key).get("used") - used0 if used0 is not None else None
    except Exception:  # noqa: BLE001
        used = None
    return R(f"Narration saved to docs/edit/narration.json (line ids for the plan: s<scene>_<line>)"
             + (f" · ≈{used:,} credits used" if used else "") + ":\n" + "\n".join(report))
