"""AnKar Video Editor server: `python -m app.server` (or "Start AnKar Video Editor.bat") → http://localhost:8765"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
import traceback
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import av
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from scipy.io import wavfile
from watchfiles import awatch

from . import captions, config, generators, luts, subtitles
from .library import Library
from .paths import EFFECTS, GENERATED_NARRATION, LIBRARY, LUTS, PROJECTS, ROOT, VOICES, WEB, absp, rel
from .project import DEFAULT_FORMAT, FORMATS, OpError
from .projects import ProjectManager
from .render import compositor
from .render.gl import load_presets as _load_presets
from .render import voicefx as voicefx_mod
from .render.timeline import clip_dur


def load_presets() -> dict:
    """Effect presets + caption templates + looks (built-in and the user's saved ones)."""
    p = _load_presets()
    user_looks = [dict(x, user=True) for x in captions.user_presets().get("looks", [])]
    return {**p, "caption_templates": captions.templates(), "looks": p.get("looks", []) + user_looks}

PORT = int(os.environ.get("VLOG_PORT", "8765"))


class Hub:
    """Server-sent events to every open browser tab."""

    def __init__(self):
        self.clients: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def emit(self, kind, data=None):
        from .keystore import redact
        msg = redact(json.dumps({"type": kind, "data": data}))   # safety net: no API key ever reaches a browser
        if self.loop is None:
            return
        for q in list(self.clients):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)


hub = Hub()
lib = Library(notify=hub.emit)
lock = threading.RLock()
pm = ProjectManager(asset_info=lib.get)
lib.project = pm.name                                  # the library shows the open project's assets/ + the shared library/
export_job = {"running": False, "cancel": False, "progress": None, "last": None}


def ed():
    return pm.editor


def state():
    with lock:
        return {"project": ed().p, "history": ed().history(), "project_name": pm.name, "project_path": rel(pm.path)}


def push(source, client=None, **extra):
    st = state()
    hub.emit("project", {**st, "source": source, "client": client, **extra})
    return st


async def watch_files():
    async for changes in awatch(LIBRARY, PROJECTS, debounce=600, recursive=True):
        paths = {str(Path(p).resolve()) for _, p in changes}
        imp, ass = str(pm.import_dir.resolve()), str(pm.assets.resolve())
        if any(p.startswith(imp) for p in paths):
            await asyncio.to_thread(lib.sort_import)
        if any(p.startswith(ass) or p.startswith(str(LIBRARY.resolve())) for p in paths):
            await asyncio.to_thread(lib.scan)
        if str(pm.path.resolve()) in paths:
            with lock:
                changed = ed().check_external()
            if changed:
                hub.emit("toast", {"text": "Project updated from outside the app (e.g. by Claude)", "kind": "claude"})
                push("external")


@asynccontextmanager
async def lifespan(app):
    hub.loop = asyncio.get_running_loop()

    def quiet(loop, ctx):          # Windows prints a harmless traceback whenever a browser tab closes abruptly
        if isinstance(ctx.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
            return
        loop.default_exception_handler(ctx)
    hub.loop.set_exception_handler(quiet)
    await asyncio.to_thread(lib.sort_import)
    await asyncio.to_thread(lib.scan)
    task = asyncio.create_task(watch_files())
    if os.environ.get("VLOG_OPEN", "1") == "1":
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    yield
    task.cancel()


class FreshStatic(StaticFiles):
    """App code must never come from a stale browser cache (otherwise new features don't show up after an update)."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app = FastAPI(title="AnKar Video Editor", lifespan=lifespan)
app.mount("/web", FreshStatic(directory=WEB), name="web")
app.mount("/effects", FreshStatic(directory=EFFECTS), name="effects")


@app.exception_handler(OpError)
async def op_error(_, e: OpError):
    return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/files/{path:path}")
def files(path: str):
    """Serve workspace media (projects/<name>/…, library/, cache/) with Range support for video seeking."""
    if not path.split("/")[0] in ("projects", "library", "cache"):
        raise HTTPException(403)
    try:
        p = absp(path)
    except ValueError:
        raise HTTPException(403)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/state")
def api_state():
    return {**state(), "assets": lib.list(), "presets": load_presets(), "exports": list_exports(),
            "packs": generators.keys_real.PACK_INFO, "export_job": export_job, "projects": pm.list(),
            "checkpoints": pm.checkpoints(), "voices": Voices.list(), "tts": tts.status(), "tts_jobs": tts.jobs,
            "luts": luts.list_luts(), "ambience": voicefx_mod.ambience_list()}


@app.get("/api/changelog")
def api_changelog(project: str | None = None):
    """Feedback & Change Log of a project (default: the open one)."""
    from . import changelog
    name = project or pm.name
    return {"project": name, **changelog.load(name)}


@app.post("/api/changelog")
def api_changelog_set(body: dict):
    from . import changelog
    name = body.get("project") or pm.name
    try:
        d = changelog.update(name, body)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    hub.emit("changelog", {"project": name, **d})
    return {"project": name, **d}


@app.get("/api/claude/progress")
def api_claude_progress():
    """Claude's current editing job (steps, %, time left) + finished jobs — for the 'Claude' pop-up."""
    from . import claude_progress
    return claude_progress.get()


@app.post("/api/claude/progress")
def api_claude_progress_set(body: dict):
    """Claude reports progress: {action: start|step|add|log|finish|clear, ...} (see app/claude_progress.py)."""
    from . import claude_progress
    try:
        r = claude_progress.update(body)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    hub.emit("claude_progress", r)
    return r


@app.get("/api/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    hub.clients.add(q)

    async def gen():
        try:
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.clients.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ edits
@app.post("/api/op")
def api_op(body: dict):
    if "batch" not in body and "op" not in body:
        raise HTTPException(400, "send {op, args} or {batch: [...]}")
    with lock:
        if "batch" in body:
            result = ed().apply_batch([(o["op"], o.get("args", {})) for o in body["batch"]], body.get("label", "Edit"))
        else:
            result = ed().apply(body["op"], body.get("args", {}), body.get("label"))
    return {**push("op", body.get("client")), "result": result}


@app.post("/api/undo")
def api_undo(body: dict | None = None):
    with lock:
        label = ed().undo()
    return {**push("undo", (body or {}).get("client")), "label": label}


@app.post("/api/redo")
def api_redo(body: dict | None = None):
    with lock:
        label = ed().redo()
    return {**push("redo", (body or {}).get("client")), "label": label}


# ------------------------------------------------------------------ projects
def switched():
    if lib.project != pm.name:                         # each project has its own assets/
        lib.set_project(pm.name)
    st = state()
    extra = {"exports": list_exports(), "projects": pm.list(), "checkpoints": pm.checkpoints(), "assets": lib.list()}
    hub.emit("project_switched", {**st, **extra})
    return {**st, **extra}


@app.get("/api/projects")
def api_projects():
    return {"projects": pm.list(), "current": pm.name, "checkpoints": pm.checkpoints()}


@app.post("/api/projects/{action}")
def api_project_action(action: str, body: dict):
    with lock:
        if action == "new":
            pm.new(body["name"], body.get("format") or DEFAULT_FORMAT)
        elif action == "copy_assets":                  # e.g. bring the brand logo/watermark over from another project
            copied = pm.copy_assets_from(body["from"], tuple(body.get("folders") or ("brand",)))
            lib.scan()
            return {"copied": copied, "assets": lib.list()}
        elif action == "open":
            pm.open(body["name"])
        elif action == "save_as":
            pm.save_as(body["name"])
        elif action == "rename":
            pm.rename(body.get("name", pm.name), body["new"])
        elif action == "duplicate":
            pm.duplicate(body.get("name", pm.name), body["new"])
        elif action == "delete":
            pm.delete(body["name"])
        elif action == "checkpoint":
            f = pm.checkpoint(body.get("label", ""))
            hub.emit("toast", {"text": f"Saved checkpoint {f[:15]}", "kind": "ok"})
            return {"file": f, "checkpoints": pm.checkpoints()}
        elif action == "revert":
            pm.revert(body["file"])
            return {**push("revert"), "checkpoints": pm.checkpoints()}
        else:
            raise HTTPException(404)
    return switched()


@app.post("/api/rescan")
def api_rescan():
    moved = lib.sort_import()
    lib.scan()
    return {"moved": moved, "count": len(lib.list())}


@app.post("/api/open")
def api_open(body: dict):
    a = pm.assets
    target = {"assets": a, "import": pm.import_dir, "exports": pm.exports, "project": pm.path.parent, "docs": pm.docs,
              "script": pm.docs / "script", "video": a / "video", "audio": a / "audio", "music": a / "audio" / "music",
              "photos": a / "photos", "images": a / "photos", "brand": a / "brand", "library": LIBRARY,
              "voices": VOICES, "luts": LUTS, "ambience": LIBRARY / "ambience"}.get(body.get("target"), pm.path.parent)
    target.mkdir(parents=True, exist_ok=True)
    os.startfile(target)  # noqa: S606 - opens Explorer on the user's own folder
    return {"ok": True}


# ------------------------------------------------------------------ generators / subtitles / recording / snapshot
@app.post("/api/generate/typed_intro")
def api_typed_intro(body: dict):
    r = generators.typed_intro(lines=body.get("lines"), start=0.0, pack=body.get("pack", "slim"))
    entry = lib.register(ROOT / r["wav"])
    start = float(body.get("start", 0.0))
    ops = [("add_text", {**t, "start": start}) for t in r["texts"]]
    ops.append(("add_media", {"asset": entry["id"], "track": body.get("sfx_track", "A3"), "start": start}))
    with lock:
        ed().apply_batch(ops, "Add Typed Intro")
    return push("op")


@app.post("/api/subtitles/import")
def api_sub_import(body: dict):
    a = lib.get(body["asset"])
    if not a or a["kind"] != "subtitle":
        raise HTTPException(400, "pick a .srt/.ass/.vtt file")
    lines = subtitles.parse(ROOT / a["path"])
    return _add_subs([{"start": s, "end": e, "text": t} for s, e, t in lines], float(body.get("start", 0.0)),
                     body.get("track", "T1"), f"Import {a['name']}")


@app.post("/api/subtitles/transcribe")
def api_transcribe(body: dict):
    """Multilingual: English kept as is, other languages translated to English and wrapped in ( )."""
    with lock:
        c = ed().clip(body["clip"])
        glossary = ed().p["settings"].get("glossary", [])
    a = lib.get(c.get("asset"))
    if not a:
        raise HTTPException(400, "clip has no media")
    try:
        lines = subtitles.transcribe_multilingual(str(ROOT / a["path"]), c["in"], c["out"], (a.get("meta") or {}).get("start", 0.0),
                                                  glossary=glossary, progress=lambda v: hub.emit("task", {"name": "Transcribing", "value": v}))
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    sp = c.get("speed", 1.0)
    for ln in lines:
        ln["start"], ln["end"] = ln["start"] / sp, ln["end"] / sp
        ln["asset"] = a["id"]
    return _add_subs(lines, c["start"], body.get("track", "T1"), "Transcribe")


@app.post("/api/subtitles/redo")
def api_sub_redo(body: dict):
    """Re-transcribe one subtitle line as a given language (fixes a wrong language detection)."""
    with lock:
        c = ed().clip(body["clip"])
        glossary = ed().p["settings"].get("glossary", [])
    meta = c.get("meta") or {}
    a = lib.get(meta.get("asset"))
    if not a or not meta.get("src"):
        raise HTTPException(400, "this subtitle wasn't made by Transcribe, so its audio is unknown")
    lang = body.get("lang", "en")
    lines = subtitles.transcribe_multilingual(str(ROOT / a["path"]), meta["src"][0], meta["src"][1],
                                              (a.get("meta") or {}).get("start", 0.0), glossary=glossary, force_lang=lang)
    if not lines:
        raise HTTPException(400, "no speech recognised in that part")
    text = " ".join(ln["text"].strip("() ") for ln in lines)
    text = f"({text})" if lang != "en" else text
    with lock:
        ed().apply("update", {"ids": [c["id"]], "patch": {"text": {"content": text},
                   "meta": {**meta, "lang": lang, "translated": lang != "en", "original": lines[0].get("original")}}},
                   f"Redo subtitle as {subtitles.LANG_NAMES.get(lang, lang)}")
    return push("op")


# ------------------------------------------------------------------ auto captions (word-timed templates)
POSITIONS = {"middle": 0.5, "top": 0.2}


def _caption_sources(p, scope, ids):
    """Clips whose speech becomes captions: [(clip, abs audio path, src t0, src t1, file start offset)]."""
    tracks = {t["id"]: t for t in p["tracks"]}
    by_id = {c["id"]: c for c in p["clips"]}
    if scope == "clip":
        picked = []
        for i in ids or []:
            c = by_id.get(i)
            if c and c["type"] == "media" and tracks[c["track"]]["kind"] == "video" and c.get("link"):
                c = next((x for x in p["clips"] if x.get("link") == c["link"] and tracks[x["track"]]["kind"] == "audio"), c)
            if c:
                picked.append(c)
    else:
        roles = ("dialogue",) if scope == "dialogue" else ("dialogue", "narration")
        picked = [c for c in p["clips"] if tracks[c["track"]]["kind"] == "audio" and tracks[c["track"]].get("role") in roles
                  and c.get("enabled", True) and not tracks[c["track"]].get("mute")]
    out, seen = [], set()
    for c in picked:
        if c["type"] == "tts":
            f = (c.get("tts") or {}).get("file")
            if f and (ROOT / f).exists():
                out.append((c, str(ROOT / f), c.get("in", 0.0), c.get("in", 0.0) + c["dur"], 0.0))
            continue
        if c["type"] != "media" or c.get("hold") is not None or c.get("reverse") or c.get("still"):
            continue
        a = lib.get(c.get("asset"))
        if not a or not (a.get("meta") or {}).get("has_audio", a["kind"] == "audio"):
            continue
        key = (a["id"], round(c["in"], 3), round(c["out"], 3), round(c["start"], 3))
        if key in seen:
            continue
        seen.add(key)
        out.append((c, str(ROOT / a["path"]), c["in"], c["out"], (a.get("meta") or {}).get("start", 0.0)))
    return out


@app.post("/api/captions/auto")
def api_captions_auto(body: dict):
    """Transcribe speech (English kept, other languages translated in ( )) → word-timed captions in a template.
    body: {scope: clip|dialogue|timeline, ids, template, max_words, max_chars, position: bottom|middle|top, replace, track}"""
    with lock:
        p = json.loads(json.dumps(ed().p))
    glossary = p["settings"].get("glossary", [])
    srcs = _caption_sources(p, body.get("scope", "clip"), body.get("ids"))
    if not srcs:
        raise HTTPException(400, "nothing to caption: pick a clip with speech (or put dialogue on the Dialogue track)")
    tpl = captions.template(body.get("template"))
    mw, mc = int(body.get("max_words") or tpl.get("max_words", 5)), int(body.get("max_chars") or tpl.get("max_chars", 28))
    pos = body.get("position", "bottom")
    y = POSITIONS.get(pos) if isinstance(pos, str) else float(pos)
    all_caps, unclear, n = [], [], len(srcs)
    try:
        for k, (c, path, t0, t1, off) in enumerate(srcs):
            name = f"Auto captions {k + 1}/{n}" if n > 1 else "Auto captions"
            hub.emit("task", {"name": name, "value": k / n, "stage": "Listening for speech"})
            sp = c.get("speed", 1.0) if c["type"] == "media" else 1.0

            def prog(v, k=k, name=name):
                hub.emit("task", {"name": name, "value": (k + v) / n, "stage": "Transcribing & translating"})
            utts = subtitles.transcribe_words(path, t0, t1, off, glossary=glossary, progress=prog)
            group = f"g{c['id']}"
            for u in utts:                                    # source seconds → timeline seconds
                for w in u.get("words", []):
                    w["t0"], w["t1"] = c["start"] + w["t0"] / sp, c["start"] + w["t1"] / sp
                if u.get("unheard"):
                    unclear.append({"start": c["start"] + u["start"] / sp, "end": c["start"] + u["end"] / sp, "lang": u["lang"]})
            for cap in subtitles.chunk_captions(utts, max_words=mw, max_chars=mc):
                cap["group"] = group
                all_caps.append(cap)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    hub.emit("task", {"name": "Auto captions", "value": 1, "stage": "Building captions"})
    if not all_caps and not unclear:
        raise HTTPException(400, "no speech recognised")
    span = [min(c["start"] for c, *_ in srcs), max(c["start"] + clip_dur(c) for c, *_ in srcs)]
    with lock:
        made = ed().apply("add_captions", {"captions_": all_caps, "template": tpl["id"], "track": body.get("track", "T1"),
                                           "y": y, "replace": span if body.get("replace", True) else None, "unclear": unclear},
                          f"Auto captions ({tpl['name']})")
    review = sum(1 for c in all_caps if c.get("review")) + len(unclear)
    hub.emit("task", {"name": "Auto captions", "value": 1, "stage": "Done", "done": True})
    return {**push("op"), "captions": len(made), "review": review, "ids": made}


_preview_lock = threading.Lock()


def _preview_posters(asset=None):
    """Poster frames to render thumbnails on: the chosen asset first, then the user's own footage, then samples."""
    vids = [a for a in lib.list() if a["kind"] in ("video", "image")]
    vids.sort(key=lambda a: (a["id"] != asset, "_samples" in a["path"], a["path"]))
    out = []
    for a in vids:
        p = lib.cache_dir(a["id"]) / "poster.jpg"
        if p.exists():
            out.append(p)
        if len(out) == 2:
            break
    return out


@app.post("/api/previews")
def api_previews(body: dict):
    """{kind: filters|luts|looks|transitions, asset?} → {items: {id: url}} thumbnails made with the real shaders."""
    from . import previews
    kind = body.get("kind", "filters")
    posters = _preview_posters(body.get("asset"))
    if not posters:
        return {"items": {}}
    pres = load_presets()
    if kind == "filters":
        items = [f for f in pres["filters"] if not f.get("lut")]
    elif kind == "luts":
        items = [{"id": l["file"], "file": l["file"]} for l in luts.list_luts() if not l.get("error")]
    elif kind == "looks":
        items = pres["looks"]
    elif kind == "transitions":
        items = pres["transitions"]
    else:
        raise HTTPException(400, "kind must be filters, luts, looks or transitions")
    with _preview_lock:
        return {"items": previews.render(kind, posters, pres, items), "frames": previews.FRAMES}


def _save_user(section, entry=None, remove=None):
    data = captions.user_presets()
    data.setdefault(section, [])
    if remove:
        data[section] = [x for x in data[section] if x["id"] != remove]
    if entry:
        data[section] = [x for x in data[section] if x["id"] != entry["id"]] + [entry]
    captions.USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
    captions.USER_PRESETS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    hub.emit("presets", {"looks": load_presets()["looks"], "caption_templates": captions.templates()})


@app.post("/api/looks/save_preset")
def api_look_save(body: dict):
    """Save a clip's grade (color + LUT + filters) as one of 'My looks' (shared by all projects)."""
    with lock:
        c = ed().clip(body["clip"])
    if not (c.get("filters") or c.get("color")):
        raise HTTPException(400, "this clip has no color or filters to save")
    name = (body.get("name") or "My look").strip()[:40]
    lid = "user_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    _save_user("looks", {"id": lid, "name": name, "desc": "Saved from a clip", "user": True,
                         "color": c.get("color", {}), "filters": c.get("filters", [])})
    return {"id": lid, "looks": load_presets()["looks"]}


@app.post("/api/looks/delete_preset")
def api_look_delete(body: dict):
    _save_user("looks", remove=body["id"])
    return {"looks": load_presets()["looks"]}


@app.get("/api/luts")
def api_luts():
    """LUTs in library/luts/ (built-in pack from scripts/make_luts.py + the user's own .cube files)."""
    return {"luts": luts.list_luts()}


@app.get("/api/captions/templates")
def api_caption_templates():
    return {"templates": captions.templates()}


@app.post("/api/captions/save_preset")
def api_caption_save_preset(body: dict):
    """Save a caption's current look as 'My preset' (shared by all projects)."""
    with lock:
        c = ed().clip(body["clip"])
    cap = c["text"].get("caption")
    if not cap:
        raise HTTPException(400, "not a caption")
    data = captions.user_presets()
    name = (body.get("name") or "My caption style").strip()[:40]
    pid = "user_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    base = captions.template(cap.get("template"))
    entry = {**cap["style"], "id": pid, "name": name, "desc": "Saved from a caption", "y": c["text"]["y"],
             "anim": c["text"]["anim"], "max_words": base.get("max_words", 5), "max_chars": base.get("max_chars", 28)}
    data["captions"] = [x for x in data.get("captions", []) if x["id"] != pid] + [entry]
    captions.USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
    captions.USER_PRESETS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    hub.emit("presets", {"caption_templates": captions.templates()})
    return {"id": pid, "templates": captions.templates()}


@app.post("/api/captions/delete_preset")
def api_caption_delete_preset(body: dict):
    data = captions.user_presets()
    data["captions"] = [x for x in data.get("captions", []) if x["id"] != body["id"]]
    captions.USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
    captions.USER_PRESETS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    hub.emit("presets", {"caption_templates": captions.templates()})
    return {"templates": captions.templates()}


def _add_subs(lines, offset, track, label):
    pres = {p["id"]: p for p in load_presets()["text_presets"]}["subtitle"]["defaults"]
    ops = [("add_text", {"track": track, "start": offset + ln["start"], "dur": max(0.3, ln["end"] - ln["start"]), "content": ln["text"],
                         "preset": "subtitle", "x": pres["x"], "y": pres["y"], "style": pres["style"], "anim": pres["anim"],
                         **({"meta": {k: ln[k] for k in ("lang", "original", "translated", "src", "asset") if k in ln}} if "lang" in ln else {})})
           for ln in lines]
    if not ops:
        raise HTTPException(400, "no speech found")
    with lock:
        ed().apply_batch(ops, label)
    return {**push("op"), "lines": len(ops)}


@app.post("/api/upload")
async def api_upload(request: Request):
    """Upload a file from the browser (streamed to disk) into the open project's assets/video or assets/audio/voiceover."""
    import re as _re
    from . import media as media_mod
    raw = request.query_params.get("name", "upload.mp4")
    name = _re.sub(r"[^\w\-. ()]+", "_", Path(raw).name).strip() or "upload.mp4"
    kind = media_mod.kind_of(Path(name))
    if kind not in ("video", "audio"):
        raise HTTPException(400, "upload a video or audio file (mp4, mov, m4a, mp3, wav…)")
    folder = pm.assets / "video" if kind == "video" else pm.assets / "audio" / "voiceover"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    i = 2
    while dest.exists():
        dest = folder / f"{Path(name).stem} ({i}){Path(name).suffix}"
        i += 1
    tmp = dest.with_name(dest.name + ".part")
    size = 0
    try:
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                size += len(chunk)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    entry = await asyncio.to_thread(lib.register, dest)
    return {"asset": entry["id"], "path": rel(dest), "size": size, "name": dest.name}


@app.post("/api/record")
async def api_record(request: Request):
    """Microphone voiceover from the browser → <project>/assets/audio/voiceover/rec_*.wav, placed on the Narration track."""
    data = await request.body()
    start = float(request.query_params.get("start", 0))
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        chunks = []
        with av.open(tmp) as c:
            rs = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
            for fr in c.decode(audio=0):
                chunks += [r.to_ndarray() for r in rs.resample(fr)]
            chunks += [r.to_ndarray() for r in rs.resample(None)]
    finally:
        os.unlink(tmp)
    if not chunks:
        raise HTTPException(400, "no audio was recorded")
    x = np.concatenate(chunks, axis=1)
    out = pm.assets / "audio" / "voiceover" / f"rec_{datetime.now():%Y%m%d_%H%M%S}.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out, 48000, (np.clip(x.T, -1, 1) * 32767).astype(np.int16))
    entry = await asyncio.to_thread(lib.register, out)
    with lock:
        tid = ed().ensure_track("narration")
        ed().apply("add_media", {"asset": entry["id"], "track": tid, "start": start}, "Record Voiceover")
    return {**push("op"), "path": rel(out)}


@app.post("/api/snapshot")
def api_snapshot(body: dict):
    with lock:
        proj = json.loads(json.dumps(ed().p))
    assets = {aid: lib.get(aid) for aid in proj["assets"]}
    t = float(body.get("t", 0))
    d = pm.exports / "frames"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"frame_{int(t // 60):02d}m{t % 60:06.3f}s.png".replace(".", "_", 1)
    compositor.snapshot(proj, assets, t, f)
    return {"path": rel(f)}


_reverse_busy: set = set()


@app.post("/api/reverse_proxy")
def api_reverse_proxy(body: dict):
    """Background-build a reversed preview proxy for a clip's source range; replies with its URL when it exists."""
    from . import media as media_mod
    a = lib.get(body["asset"])
    if not a or not (a.get("derived") or {}).get("proxy"):
        raise HTTPException(400, "proxy not ready")
    t0, t1 = round(float(body["in"]), 3), round(float(body["out"]), 3)
    d = lib.cache_dir(a["id"])
    out = d / f"rev_{t0:.3f}_{t1:.3f}.mp4"
    url = f"/files/{rel(out)}"
    if out.exists():
        return {"url": url, "ready": True}
    key = str(out)
    if key not in _reverse_busy:
        _reverse_busy.add(key)

        def run():
            try:
                media_mod.reversed_proxy(d / "proxy.mp4", out, t0, t1, (a.get("meta") or {}).get("fps_frac", "30000/1001"))
                hub.emit("reverse_ready", {"asset": a["id"], "in": t0, "out": t1, "url": url})
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                _reverse_busy.discard(key)
        threading.Thread(target=run, daemon=True).start()
    return {"url": url, "ready": False}


# ------------------------------------------------------------------ voices + AI narration
from .tts.manager import TTSManager, Voices, to_mono48  # noqa: E402


_quick_fx: dict = {}


def _tts_done(cid, res):
    if cid.startswith("quick_"):                       # quick test line: no timeline change, just an MP3 to play/download
        try:
            mp3 = _mp3_for(res["file"], "voice_test", _quick_fx.pop(cid, None))
            hub.emit("quick_tts", {"id": cid, **res, **mp3, "wav_url": f"/files/{res['file']}"})
        except Exception as e:  # noqa: BLE001
            hub.emit("quick_tts", {"id": cid, "error": str(e)})
        return
    from .tts import layout as tlay
    entry = lib.register(ROOT / res["file"])
    with lock:
        try:
            c = ed().clip(cid)
        except OpError:
            return                                     # clip was deleted meanwhile
        tt = c["tts"]
        segs = res.get("segs") or None
        file, asset, keep = res["file"], entry["id"], None
        if segs and tt.get("layout") and len(tt["layout"]) == len(segs) and len(tt.get("segs") or []) == len(segs):
            keep = tlay.clean(segs, tt["layout"])      # same sentences, new words/voice: keep where the user put them
            if tlay.is_natural(segs, keep):
                keep = None
            else:
                f = tlay.compose(ROOT / res["file"], segs, keep, GENERATED_NARRATION)
                file, asset = rel(f), lib.register(f)["id"]
        ops = []
        in0 = (c.get("in") or 0.0) if keep else 0.0    # kept timing: same file origin → sentences stay put on the timeline
        if keep:                                       # the clip must still reach the last sentence
            need = tlay.end_of(segs, keep) + tlay.TAIL - in0
            if need > c["dur"] + 1e-3:
                ops.append(("trim", {"id": cid, "edge": "end", "t": c["start"] + need}))
        elif res.get("fitted") is False and res.get("natural"):      # too different to stretch: resize the clip to the speech
            ops.append(("trim", {"id": cid, "edge": "end", "t": c["start"] + res["natural"]}))
        ops.append(("update", {"ids": [cid], "patch": {"asset": asset, "in": in0,                # after the trim (it marks stale)
                                                        "tts": {"file": file, "base": res["file"], "segs": segs, "layout": keep,
                                                                "stale": False, "fitted": res.get("fitted", True),
                                                                "wpm": res.get("wpm"), "pieces": res.get("pieces"),
                                                                "limited": res.get("limited", False), "match": res.get("match"),
                                                                "words": res.get("words")}},
                               "ripple_speed": False}))
        if tt.get("caption"):
            ops.append(("narration_captions", {"id": cid}))
        ed().apply_batch(ops, "Generate Narration")
    push("tts")


tts = TTSManager(notify=hub.emit, on_done=_tts_done)


@app.get("/api/voices")
def api_voices():
    return {"voices": Voices.list(), "tts": tts.status()}


@app.post("/api/voices/create")
def api_voice_create(body: dict):
    try:
        name = Voices.create(body.get("name", ""), bool(body.get("consent")), body.get("note", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.emit("voices", Voices.list())
    return {"name": name, "voices": Voices.list()}


@app.post("/api/voices/sample")
def api_voice_sample(body: dict):
    """Cut a voice sample from a timeline clip (its visible part or a timeline range) or from an asset (source range)."""
    from .render.audio import decode_range
    if body.get("clip"):
        with lock:
            c = ed().clip(body["clip"])
        a = lib.get(c.get("asset"))
        if not a or not (a.get("meta") or {}).get("has_audio"):
            raise HTTPException(400, "that clip has no audio")
        t0 = max(c["start"], float(body.get("t0", c["start"])))
        t1 = min(c["start"] + (c["out"] - c["in"]) / c.get("speed", 1.0), float(body.get("t1", 1e9)))
        sp = c.get("speed", 1.0)
        s0, s1 = c["in"] + (t0 - c["start"]) * sp, c["in"] + (t1 - c["start"]) * sp
    else:
        a = lib.get(body.get("asset"))
        if not a:
            raise HTTPException(400, "pick a clip or an audio/video file")
        s0, s1 = float(body.get("t0", 0)), float(body.get("t1", (a.get("meta") or {}).get("dur") or 0))
    if s1 - s0 < 2:
        raise HTTPException(400, "pick at least 2 seconds of speech")
    if s1 - s0 > 90:
        s1 = s0 + 90
    x = decode_range(str(ROOT / a["path"]), s0, s1, (a.get("meta") or {}).get("start", 0.0)).mean(axis=0)
    try:
        f = Voices.add_sample(body["voice"], body.get("mood", "neutral"), to_mono48(x, 48000), clean=bool(body.get("clean")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.emit("voices", Voices.list())
    return {"file": f, "voices": Voices.list()}


@app.post("/api/voices/speakers")
def api_find_speakers(body: dict):
    """Detect who speaks when in a clip or file; returns speakers with talk time, turns and preview snippets."""
    from .tts import speakers
    if body.get("clip"):
        with lock:
            c = ed().clip(body["clip"])
        a = lib.get(c.get("asset"))
        t0, t1 = c["in"], c["out"]
    else:
        a = lib.get(body.get("asset"))
        t0 = float(body.get("t0") or 0)
        t1 = float(body.get("t1") or (a or {}).get("meta", {}).get("dur") or 0)
    if not a or not (a.get("meta") or {}).get("has_audio"):
        raise HTTPException(400, "pick a video or audio file that has sound")
    t1 = min(t1, t0 + 600)                                      # analyse at most 10 minutes at a time
    try:
        job = speakers.detect(str(ROOT / a["path"]), t0, t1, (a.get("meta") or {}).get("start", 0.0), tts.embed,
                              n_speakers=body.get("n") or None,
                              progress=lambda v, stage=None: hub.emit("task", {"name": "Extracting voices", "value": v, "stage": stage}),
                              isolate_fn=tts.isolate if body.get("isolate", True) else None)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    hub.emit("task", {"name": "Extracting voices", "value": 1, "stage": "Done"})
    return {**{k: v for k, v in job.items() if k != "src"}, "asset": a["id"], "asset_name": a["name"], "t0": t0}


@app.post("/api/voices/from_speaker")
def api_voice_from_speaker(body: dict):
    """Make (or extend) a voice from one detected speaker's speech."""
    from .tts import speakers
    name = (body.get("voice") or "").strip()
    info = {}
    try:
        x = speakers.speaker_audio(body["job"], body["speaker"], max_sec=float(body.get("max_sec", 150)),
                                   source=body.get("source", "auto"), info=info)
        exists = any(v["name"] == name for v in Voices.list())
        if not exists:
            name = Voices.create(name, bool(body.get("consent")))
        elif body.get("replace"):                          # rebuild from scratch: old samples → cache/trash
            for s in next(v for v in Voices.list() if v["name"] == name)["samples"]:
                Voices.delete_sample(s["file"])
        f = Voices.add_sample(name, body.get("mood", "neutral"), x, clean=bool(body.get("clean", False)))
        job = speakers.JOBS.get(body["job"]) or {}
        Voices.add_source(name, {"path": rel(Path(job["src"]["path"])) if job.get("src", {}).get("path") else None,
                                 "speaker": body["speaker"], **info})
    except ValueError as e:
        raise HTTPException(400, str(e))
    hub.emit("voices", Voices.list())
    return {"voice": name, "file": f, "voices": Voices.list(), "extract": info}


@app.post("/api/tts/quick")
def api_tts_quick(body: dict):
    """Generate a line without the timeline (try a voice / get an MP3). Result arrives as SSE 'quick_tts'."""
    import uuid
    if not (body.get("text") or "").strip():
        raise HTTPException(400, "type something to say")
    qid = f"quick_{uuid.uuid4().hex[:8]}"
    if body.get("fx"):
        _quick_fx[qid] = body["fx"]
    tts.submit({"id": qid, "dur": 0, "tts": {"text": body["text"], "voice": body.get("voice") or None, "tone": body.get("tone", "neutral"),
                                             "intensity": body.get("intensity", 0.5), "pace": body.get("pace", 1.0), "fit": False,
                                             "rate": body.get("rate"), "pause": body.get("pause", 1.0),
                                             "steady": body.get("steady", True), "take": body.get("take", 0)}})
    return {"id": qid}


@app.post("/api/tts/place")
def api_tts_place(body: dict):
    """Put a generated line (from Voice from Video / Try it) on the Narration track at `start`."""
    from .tts.manager import GENERATED
    p = absp(body["file"])
    if not str(p).startswith(str(GENERATED)) or not p.exists():
        raise HTTPException(400, "unknown narration file")
    entry = lib.register(p)
    meta = p.with_suffix(".json")
    pinfo = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    text = (body.get("text") or "").strip()
    sr, x = wavfile.read(p)
    dur = round(len(x) / sr, 3)
    with lock:
        if text:                                      # a real narration clip: editable text, voice and sentence timing
            f = rel(p)
            extra = {"file": f, "base": f, "segs": pinfo.get("segs"), "stale": False, "fitted": True,
                     "wpm": pinfo.get("wpm"), "pieces": pinfo.get("pieces"),
                     **{k: body[k] for k in ("rate", "pause", "steady", "take") if k in body}}
            ed().apply("add_tts", {"start": float(body.get("start", 0)), "dur": dur, "text": text, "voice": body.get("voice") or None,
                                   "tone": body.get("tone", "neutral"), "intensity": float(body.get("intensity", 0.5)),
                                   "pace": float(body.get("pace", 1.0)), "fit": False, "extra": extra, "asset": entry["id"]},
                       "Add Narration")
        else:
            tid = ed().ensure_track("narration")
            ed().apply("add_media", {"asset": entry["id"], "track": tid, "start": float(body.get("start", 0))}, "Add Narration")
    return push("op")


# ---------------------------------------------------------------- narration timing (sentences, Match to video)
def _track_room(c) -> tuple[float, float]:
    """Free space around clip c on its track: (earliest start, latest end) without covering a neighbour."""
    lo, hi = 0.0, 1e9
    for k in ed().p["clips"]:
        if k["track"] != c["track"] or k["id"] == c["id"]:
            continue
        ks, ke = k["start"], k["start"] + clip_dur(k)
        if ke <= c["start"] + 1e-3:
            lo = max(lo, ke)
        elif ks >= c["start"]:
            hi = min(hi, ks)
    return lo, hi


def _narration(cid):
    c = ed().clip(cid)
    tt = c.get("tts") or {}
    if c["type"] != "tts" or not tt.get("segs") or not (tt.get("base") or tt.get("file")):
        raise HTTPException(400, "This narration has no sentence timing yet — generate it (with Steady pace on) first.")
    if not (ROOT / (tt.get("base") or tt["file"])).exists():
        raise HTTPException(400, "The original narration audio is missing (cache cleared?) — press Regenerate.")
    return c, tt


def _apply_layout(cid, starts, speeds, label, start=None, end=None):
    """Put the sentences of narration clip `cid` at timeline times `starts` (speeds 0.88–1.12): composes the audio and
    applies one undoable op. The clip grows (left or right) when a visible sentence is moved outside it; start/end
    force the clip to a range (Match to video). Must be called with the lock held."""
    from .tts import layout as tlay
    c, tt = _narration(cid)
    segs = tt["segs"]
    lay = tlay.clean(segs, [{"at": float(t), "speed": float(s)} for t, s in zip(starts, speeds)])
    T = [l["at"] for l in lay]
    ends = [t + tlay.seg_len(s, l["speed"]) for t, s, l in zip(T, segs, lay)]
    visible = {s["i"] for s in tlay.timeline_spans(c)} or set(range(len(segs)))
    lo, hi = _track_room(c)
    s_new = float(start) if start is not None else min([c["start"]] + [T[i] for i in visible])
    e_new = float(end) if end is not None else c["start"] + c["dur"]
    e_new = max(e_new, max(ends[i] for i in visible) + tlay.TAIL)
    if s_new < max(0.0, lo) - 1e-3:                       # no room on the left: slide everything right
        d = max(0.0, lo) - s_new
        T, ends, s_new, e_new = [t + d for t in T], [e + d for e in ends], s_new + d, e_new + d
    if e_new > hi + 1e-3:
        raise HTTPException(400, f"Not enough room — the next clip on this track starts at {hi:.2f} s. "
                                 "Move it, shorten the text, or let sentences overlap less.")
    origin = min([c["start"] - (c.get("in") or 0.0), s_new] + T)
    lay = [{"at": round(t - origin, 3), "speed": l["speed"]} for t, l in zip(T, lay)]
    base = ROOT / (tt.get("base") or tt["file"])
    if tlay.is_natural(segs, lay):
        f, layout = base, None
    else:
        f, layout = tlay.compose(base, segs, lay, GENERATED_NARRATION), lay
    entry = lib.register(f)
    ed().apply("tts_layout", {"id": cid, "layout": layout, "file": rel(f), "asset": entry["id"], "start": s_new,
                              "dur": e_new - s_new, "in_": s_new - origin}, label)


def _sentence_times(c, tt):
    from .tts import layout as tlay
    lay = tt.get("layout") or tlay.natural_layout(tt["segs"])
    o = c["start"] - (c.get("in") or 0.0)
    return [o + l["at"] for l in lay], [l["speed"] for l in lay]


@app.post("/api/tts/layout")
def api_tts_layout(body: dict):
    """Move / re-speed sentences of a narration clip. body: {clip, starts:[timeline s], speeds:[…]} or {clip, reset:true}."""
    with lock:
        c, tt = _narration(body["clip"])
        if body.get("reset"):
            o = c["start"] - (c.get("in") or 0.0)
            starts, speeds = [o + s["a"] for s in tt["segs"]], [1.0] * len(tt["segs"])
        else:
            cur_t, cur_s = _sentence_times(c, tt)
            starts = body.get("starts") or cur_t
            speeds = body.get("speeds") or cur_s
            if len(starts) != len(tt["segs"]) or len(speeds) != len(tt["segs"]):
                raise HTTPException(400, "sentence count changed — reload")
        _apply_layout(c["id"], starts, speeds, body.get("label") or ("Reset Sentence Timing" if body.get("reset") else "Move Sentence"))
    return push("op")


@app.post("/api/tts/context")
def api_tts_context(body: dict):
    """Shot changes + where people talk in [t0, t1] (timeline s) — for snapping, the overlay and Match to video."""
    from .tts import context as tctx
    with lock:
        proj = json.loads(json.dumps(ed().p))
    try:
        return tctx.context(proj, lib.get, float(body.get("t0", 0)), float(body.get("t1", 1e9)), scenes=body.get("scenes", True))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"couldn't analyse the video: {e}")


def _match_range(c, mode, rng):
    """Timeline range for Match to video."""
    end = c["start"] + c["dur"]
    if mode == "range" and rng:
        return float(rng[0]), float(rng[1])
    if mode == "clip":
        return c["start"], end
    tracks = {t["id"]: t for t in ed().p["tracks"]}
    vids = [k for k in ed().p["clips"] if tracks[k["track"]]["kind"] == "video" and k.get("enabled", True) and k["type"] == "media"]
    if mode == "next":
        lo, hi = _track_room(c)
        vend = max([k["start"] + clip_dur(k) for k in vids] + [end])
        return c["start"], min(hi, vend) if hi < 1e8 else vend
    # "under": the main (lowest) video track's clips that the narration overlaps → their whole span
    order = [t["id"] for t in ed().p["tracks"] if t["kind"] == "video"]
    for tid in reversed(order):                            # video tracks are listed top-first; V1 is last
        on = [k for k in vids if k["track"] == tid and k["start"] < end - 1e-3 and k["start"] + clip_dur(k) > c["start"] + 1e-3]
        if on:
            return min(k["start"] for k in on), max(k["start"] + clip_dur(k) for k in on)
    return c["start"], end


@app.post("/api/tts/match")
def api_tts_match(body: dict):
    """Match a narration to the video: {clip, mode: under|range|next|clip, range?, avoid, snap, dry_run}."""
    from .tts import context as tctx, layout as tlay, placement
    with lock:
        c, tt = _narration(body["clip"])
        r0, r1 = _match_range(c, body.get("mode", "under"), body.get("range"))
        lo, hi = _track_room(c)
        r0, r1 = max(r0, lo, 0.0), min(r1, hi)
        if r1 - r0 < 0.3:
            raise HTTPException(400, "that range is too short")
        proj = json.loads(json.dumps(ed().p))
        segs = tt["segs"]
    ctx = tctx.context(proj, lib.get, r0, r1 + 30)
    rep = placement.place(segs, r0, r1, ctx["speech"], ctx["cuts"], avoid=body.get("avoid", True), snap=body.get("snap", True),
                          wpm=tt.get("wpm"))
    natural = sum(tlay.seg_len(s) for s in segs)
    out = {**rep, "range": [round(r0, 3), round(r1, 3)], "natural": round(natural, 2), "sentences": [s["text"] for s in segs],
           "lens": [round(tlay.seg_len(s, rep["speed"]), 3) for s in segs],
           "speech": [s for s in ctx["speech"] if s[1] > r0 and s[0] < r1], "cuts": [t for t in ctx["cuts"] if r0 <= t <= r1],
           "sources": ctx["sources"]}
    if body.get("dry_run"):
        return out
    with lock:
        c, tt = _narration(body["clip"])
        end = max(r1, rep["end"] + tlay.TAIL)
        if end > hi + 1e-3:
            end = hi
            if rep["end"] > hi:
                raise HTTPException(400, f"It's {rep['over']:.1f} s too long for the space before the next clip — "
                                         f"shorten the text by about {rep['words']} words, or move that clip.")
        _apply_layout(c["id"], rep["starts"], [rep["speed"]] * len(segs), "Match Narration to Video", start=r0, end=end)
    return {**push("op"), "report": out}


def _mp3_for(wav_rel: str, label: str, fx: dict | None = None) -> dict:
    """MP3 of a generated line (exports/<project>/voice/), with the voice effects baked in when given."""
    from .tts.manager import wav_to_mp3
    slug = "".join(ch if ch.isalnum() else "_" for ch in label.strip())[:40].strip("_") or "narration"
    dst = pm.exports / "voice" / f"{slug}_{datetime.now():%H%M%S}.mp3"
    src = ROOT / wav_rel
    if voicefx_mod.active(voicefx_mod.normalize(fx)):
        sr, x = wavfile.read(src)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        st = np.stack([x, x]) if x.ndim == 1 else x.T
        tail = np.zeros((2, int(sr * 1.5)), np.float32) if fx.get("space") or (fx.get("distance") or 0) > 0 else np.zeros((2, 0), np.float32)
        y = voicefx_mod.process(np.concatenate([st, tail], axis=1), fx, 0.0)
        y /= max(1.0, float(np.abs(y).max()) / 0.98)
        tmp = Path(tempfile.gettempdir()) / f"vs_fx_{datetime.now():%H%M%S%f}.wav"
        wavfile.write(tmp, sr, (y.T * 32767).astype(np.int16))
        src = tmp
    wav_to_mp3(src, dst)
    if src != ROOT / wav_rel:
        src.unlink(missing_ok=True)
    return {"mp3": rel(dst), "url": f"/files/{rel(dst)}", "name": dst.name}


@app.post("/api/tts/mp3")
def api_tts_mp3(body: dict):
    with lock:
        c = ed().clip(body["clip"])
    f = (c.get("tts") or {}).get("file")
    if not f:
        raise HTTPException(400, "generate the voice first")
    return _mp3_for(f, c["tts"].get("text", "narration"), c.get("voice_fx"))


def _voices_changed(extra=None):
    hub.emit("voices", Voices.list())
    return {"voices": Voices.list(), **(extra or {})}


def _clips_using(voice):
    with lock:
        return [c for c in ed().p["clips"] if c["type"] == "tts" and (c.get("tts") or {}).get("voice") == voice]


@app.post("/api/voices/delete_sample")
def api_voice_delete_sample(body: dict):
    try:
        backup = Voices.delete_sample(body["file"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _voices_changed({"backup": backup})


@app.post("/api/voices/delete")
def api_voice_delete(body: dict):
    """Delete a whole voice (samples + ElevenLabs clone). The files go to cache/trash/ in case it was a mistake."""
    name = body.get("name", "")
    try:
        backup = Voices.delete(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _voices_changed({"backup": backup, "narration_using": len(_clips_using(name))})


@app.post("/api/voices/rename")
def api_voice_rename(body: dict):
    """Rename a voice (e.g. it was made under the wrong person's name); narration clips in this project follow."""
    old = body.get("name", "")
    try:
        new = Voices.rename(old, body.get("new", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    users = _clips_using(old)
    if users and new != old:
        with lock:                                    # keep their generated audio: renaming isn't a reason to regenerate
            ed().apply_batch([("update", {"ids": [c["id"]], "patch": {"tts": {"voice": new, "file": c["tts"].get("file"),
                                                                              "stale": c["tts"].get("stale", False)}}}) for c in users],
                             f"Rename voice {old} → {new}")
        push("op")
    return _voices_changed({"name": new})


@app.post("/api/voices/move_sample")
def api_voice_move_sample(body: dict):
    """Move a sample to another voice (uploaded under the wrong person) and/or retag its mood."""
    try:
        f = Voices.move_sample(body["file"], body["voice"], body.get("mood"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _voices_changed({"file": f})


@app.post("/api/voices/reset")
def api_voices_reset(body: dict):
    """Start voice training from scratch. Needs {confirm: "RESET"}. Backup in cache/trash/<time>_voices_reset/."""
    if body.get("confirm") != "RESET":
        raise HTTPException(400, "type RESET to confirm")
    r = Voices.reset_all()
    return _voices_changed(r)


@app.get("/api/tts/config")
def api_tts_config():
    return config.public_tts_config()


@app.post("/api/tts/config")
def api_tts_config_set(body: dict):
    """Engine switch (local / elevenlabs), fallback, model. API keys are managed ONLY on the API Keys page (/keys)."""
    if "api_key" in body:
        raise HTTPException(403, "API keys are managed on the API Keys page (menu bar ▸ API Keys), with your password.")
    try:
        config.set_tts_settings({k: v for k, v in body.items() if k != "api_key"})
    except ValueError as e:
        raise HTTPException(400, str(e))
    pub = config.public_tts_config()
    hub.emit("tts_config", pub)
    return pub


@app.post("/api/tts/elevenlabs/check")
def api_el_check():
    from .tts import elevenlabs as el
    key = config.get_secret("elevenlabs_api_key")
    if not key:
        raise HTTPException(400, "No ElevenLabs API key saved yet.")
    return el.capabilities(key)


@app.post("/api/tts/generate")
def api_tts_generate(body: dict):
    if config.tts_settings()["engine"] == "local" and not tts.installed():
        raise HTTPException(400, "the local voice engine isn't installed (double-click 'Install local AI voice (optional).bat', or use ElevenLabs)")
    with lock:
        clips = [c for c in ed().p["clips"] if c["type"] == "tts"]
        if body.get("ids"):
            clips = [c for c in clips if c["id"] in body["ids"]]
        else:
            clips = [c for c in clips if c["tts"].get("stale") or not c["tts"].get("file")]
    voices = {v["name"] for v in Voices.list()}
    queued, skipped = [], []
    for c in clips:                                   # don't queue lines that can only fail
        if not (c["tts"].get("text") or "").strip():
            skipped.append({"id": c["id"], "start": c["start"], "reason": "no text yet"})
        elif c["tts"].get("voice") and c["tts"]["voice"] not in voices:
            skipped.append({"id": c["id"], "start": c["start"], "reason": f"voice “{c['tts']['voice']}” no longer exists"})
        else:
            tts.submit(c)
            queued.append(c["id"])
    return {"queued": queued, "skipped": skipped}


@app.get("/api/tts/status")
def api_tts_status():
    return tts.status()


# ------------------------------------------------------------------ export / versions
def list_exports():
    """Finals (any .mp4 in exports/) first, then drafts (any .mp4 in exports/draft/: vNN + earlier finals)."""
    out = []
    folder = pm.exports
    if not folder.exists():
        return out
    finals = [p for p in sorted(folder.glob("*.mp4"))]
    drafts = sorted((folder / "draft").glob("*.mp4")) if (folder / "draft").exists() else []
    for p, kind in [(p, "final" if not p.name.startswith("v") else "version") for p in finals] + [(p, "draft") for p in drafts]:
        snap = p.with_name(f"{p.stem}.project.json")
        name = p.name if kind != "draft" else f"draft/{p.name}"
        out.append({"name": name, "kind": kind, "size": p.stat().st_size,
                    "time": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"),
                    "restorable": snap.exists(), "url": f"/files/{rel(p)}"})
    return out


@app.post("/api/export")
def api_export(body: dict):
    if export_job["running"]:
        raise HTTPException(409, "an export is already running")
    with lock:
        proj = json.loads(json.dumps(ed().p))
    if not proj["clips"]:
        raise HTTPException(400, "the timeline is empty")
    fmt = FORMATS.get(body.get("format") or proj["format"]["preset"], (proj["format"]["w"], proj["format"]["h"]))
    rng = body.get("range")
    assets = {aid: lib.get(aid) or {"path": a["path"], "kind": a["kind"], "meta": a} for aid, a in proj["assets"].items()}
    folder = pm.exports
    export_job.update(running=True, cancel=False, progress={"stage": "video", "value": 0.0}, last=None)

    def run():
        try:
            rep = compositor.export_version(
                proj, assets, folder=folder, preset=body.get("quality", "high"), fmt=fmt, t_range=tuple(rng) if rng else None,
                progress=lambda stage, v: (export_job.__setitem__("progress", {"stage": stage, "value": round(v, 3)}),
                                           hub.emit("export", {"stage": stage, "value": round(v, 3)})),
                cancel=lambda: export_job["cancel"])
            export_job["last"] = rep
            hub.emit("export_done", {**rep, "exports": list_exports()})
            hub.emit("toast", {"text": f"Exported v{rep['version']:02d}.mp4 ({rep['seconds']} s)", "kind": "ok"})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            hub.emit("export_done", {"error": str(e), "exports": list_exports()})
            hub.emit("toast", {"text": f"Export failed: {e}", "kind": "error"})
        finally:
            export_job["running"] = False

    threading.Thread(target=run, daemon=True, name="export").start()
    return {"started": True}


@app.post("/api/export/cancel")
def api_export_cancel():
    export_job["cancel"] = True
    return {"ok": True}


@app.post("/api/restore")
def api_restore(body: dict):
    name = Path(body["name"])
    sub = "draft" if name.parent.name == "draft" else ""          # only exports/ or exports/draft/ (no other paths)
    snap = pm.exports / sub / f"{name.stem}.project.json"
    if not snap.exists():
        raise HTTPException(404, "no saved timeline for that version")
    with lock:
        ed().load_snapshot(json.loads(snap.read_text(encoding="utf-8")), f"Restore {name.stem}")
    return push("restore")


# ------------------------------------------------------------------ version + update reminder
@app.get("/api/update")
def api_update(force: int = 0):
    """This version, the latest on the website, and the notes of newer versions (anonymous GET, cached a day)."""
    from . import updates
    return updates.check(bool(force))


# ------------------------------------------------------------------ API keys (own page, password, encrypted)
def _keys_guard(request: Request):
    """Only this app's own pages may call the key endpoints: same-origin (Origin / Referer = this server) and a custom
    header (a foreign web page can't add it without a CORS preflight, which this server never allows)."""
    ok_hosts = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
    for h in ("origin", "referer"):
        v = request.headers.get(h)
        if v:
            host = re.sub(r"^https?://", "", v).split("/")[0]
            if host not in ok_hosts:
                raise HTTPException(403, "Blocked: API keys can only be managed from AnKar Video Editor itself.")
    if request.headers.get("x-vlog-keys") != "1":
        raise HTTPException(403, "Blocked: missing the API Keys page header.")


@app.get("/keys")
def keys_page():
    """The API key management page (its own page: key handling stays separate from the editor's scripts)."""
    return FileResponse(WEB / "keys.html", headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                                     "Referrer-Policy": "same-origin",
                                                     "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'"})


@app.get("/api/keys")
def api_keys(request: Request):
    from . import keyauth, keystore
    _keys_guard(request)
    return {**keystore.public_list(), "auth": keyauth.status()}


def _keys_changed():
    from . import keystore
    hub.emit("keys", keystore.public_list())
    hub.emit("tts_config", config.public_tts_config())


@app.post("/api/keys/set")
def api_keys_set(request: Request, body: dict):
    """Add or change a key: {name, value, password, label?}. Needs the password."""
    from . import keyauth, keystore
    _keys_guard(request)
    try:
        keyauth.verify(body.get("password", ""))
    except keyauth.AuthError as e:
        raise HTTPException(401, str(e))
    try:
        keystore.set_key(body.get("name", ""), body.get("value", ""), body.get("label", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _keys_changed()
    return {**keystore.public_list(), "auth": keyauth.status()}


@app.post("/api/keys/remove")
def api_keys_remove(request: Request, body: dict):
    """Remove a key: {name, password}. Needs the password."""
    from . import keyauth, keystore
    _keys_guard(request)
    try:
        keyauth.verify(body.get("password", ""))
    except keyauth.AuthError as e:
        raise HTTPException(401, str(e))
    if not keystore.remove(body.get("name", "")):
        raise HTTPException(404, "There is no saved key with that name.")
    _keys_changed()
    return {**keystore.public_list(), "auth": keyauth.status()}


@app.post("/api/keys/password")
def api_keys_password(request: Request, body: dict):
    """Create the first password {new} or change it {current, new}. Stored only as a salted scrypt hash."""
    from . import keyauth, keystore
    _keys_guard(request)
    try:
        keyauth.set_password(body.get("new", ""), body.get("current"))
    except keyauth.AuthError as e:
        raise HTTPException(401, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**keystore.public_list(), "auth": keyauth.status()}


@app.post("/api/keys/test")
def api_keys_test(request: Request, body: dict):
    """Check that a saved key works (no password needed: it only uses the key, never shows it)."""
    from . import keystore
    _keys_guard(request)
    name = body.get("name")
    key = keystore.get(name)
    if not key:
        raise HTTPException(400, "No key saved.")
    if name == "anthropic_api_key":
        return api_assistant_test_key()
    if name == "elevenlabs_api_key":
        from .tts import elevenlabs as el
        c = el.capabilities(key)
        probs = c.get("problems") or []
        cred = c.get("credits") or {}
        return {"ok": not probs, "message": "; ".join(probs) if probs else
                f"The key works · {cred.get('left', '?'):,} of {cred.get('limit', '?'):,} credits left ({cred.get('tier', '')})"}
    return {"ok": True, "message": "Saved. (AnKar Video Editor doesn't know how to test this kind of key.)"}


# ------------------------------------------------------------------ AI Editor (built-in Claude chat, editing only)
_assistant = None


def assistant():
    global _assistant
    if _assistant is None:
        from .assistant.runner import Assistant
        fake = None
        if os.environ.get("VLOG_AI_FAKE") == "1" and PORT != 8765:      # UI tests on the test server only
            from .assistant.fake import make as fake
        _assistant = Assistant(hub.emit, f"http://127.0.0.1:{PORT}", client_factory=fake)
    return _assistant


@app.get("/api/assistant/config")
def api_assistant_config():
    from .assistant import settings as acfg
    return acfg.public()                                   # key status only (masked), never the key


@app.post("/api/assistant/config")
def api_assistant_config_set(body: dict):
    from .assistant import settings as acfg
    if "api_key" in body:
        raise HTTPException(403, "API keys are managed on the API Keys page (menu bar ▸ API Keys), with your password.")
    acfg.update(body)
    return acfg.public()


@app.post("/api/assistant/test_key")
def api_assistant_test_key():
    from .assistant import settings as acfg
    key = acfg.api_key()
    if not key:
        raise HTTPException(400, "No key saved yet.")
    import anthropic
    try:
        anthropic.Anthropic(api_key=key, max_retries=0, timeout=30).models.retrieve(acfg.get()["model"])
    except anthropic.AuthenticationError:
        return {"ok": False, "message": "The key was rejected."}
    except anthropic.NotFoundError:
        return {"ok": False, "message": "The key works, but this model isn't available to it — pick another model."}
    except anthropic.APIConnectionError:
        return {"ok": False, "message": "Couldn't reach the Claude API (no internet?)."}
    except anthropic.APIStatusError as e:
        return {"ok": False, "message": f"The API answered {e.status_code}."}
    return {"ok": True, "message": "The key works."}


@app.get("/api/assistant/state")
def api_assistant_state(chat: str | None = None):
    from .assistant.workflow import Workflow
    a = assistant()
    proj = pm.name
    chats = a.list_chats(proj)
    cid = chat or (a.status()["chat"] if a.status()["project"] == proj else None) or (chats[0]["id"] if chats else None)
    c = a.get_chat(proj, cid).public() if cid else None
    return {"project": proj, "chats": chats, "chat": c, "status": a.status(),
            "workflow": Workflow(PROJECTS / proj).public(), "usage": a.project_usage(proj)}


@app.post("/api/assistant/send")
def api_assistant_send(body: dict):
    text = (body.get("text") or "").strip()
    if not text and not body.get("attach"):
        raise HTTPException(400, "Type a message first.")
    try:
        return assistant().send(pm.name, body.get("chat"), text, body.get("attach"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/assistant/new")
def api_assistant_new():
    c = assistant().get_chat(pm.name, None)
    c.save()
    return {"chat": c.public(), "chats": assistant().list_chats(pm.name)}


@app.post("/api/assistant/answer")
def api_assistant_answer(body: dict):
    """{pid, action: approve|decline|change|answer, value?} — the ONLY way a waiting change gets permission."""
    try:
        p = assistant().resolve(body["pid"], body.get("action", "answer"), body.get("value"))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"status": p["status"]}


@app.post("/api/assistant/stop")
def api_assistant_stop():
    assistant().stop()
    return {"ok": True}


@app.post("/api/assistant/doc")
def api_assistant_doc(body: dict):
    """Read / save a review document of the open project (the chat's built-in .md editor). docs/ only."""
    from .assistant.workflow import DocError, Workflow
    wf = Workflow(PROJECTS / pm.name)
    try:
        p = wf.doc_path(body["path"])
        if "text" in body:                                     # the EDITOR saves: their version (never registered as AI-written)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body["text"], encoding="utf-8")
            return {"saved": True, "path": body["path"]}
        return {"path": body["path"], "text": p.read_text(encoding="utf-8") if p.exists() else ""}
    except DocError as e:
        raise HTTPException(400, str(e))


if __name__ == "__main__":
    import uvicorn
    print(f"AnKar Video Editor → http://localhost:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
