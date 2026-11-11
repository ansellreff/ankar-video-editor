"""Claude's editing progress, shown in the editor's "Claude" pop-up (web/js/claudeProgress.js).

Whenever Claude edits for the user it reports a JOB with STEPS here (via POST /api/claude/progress, or the helper
`python -m scripts.claude_progress ...`). The pop-up shows the overall %, the time left, what Claude is doing right now,
and lists of done / current / upcoming steps. Finished jobs are kept as history. Saved in cache/claude_progress.json so a
server restart doesn't lose it.

Step: {id, title, status: pending|active|done|skipped|error, est (s), started, ended, detail, log:[{t, text}], frac}
Percentage = estimate-weighted share of finished steps + the active step's own fraction (if Claude reports one).
Time left = remaining estimates × how fast Claude has been vs its estimates so far (clamped 0.5×–3×).
"""
from __future__ import annotations

import json
import threading
import time

from .paths import CACHE

FILE = CACHE / "claude_progress.json"
_lock = threading.Lock()
MAX_HISTORY = 30
MAX_LOG = 40


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"job": None, "history": []}


def _save(d: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE)


def _step(s: dict) -> dict:
    return {"id": str(s.get("id") or s["title"]), "title": s["title"], "status": s.get("status", "pending"),
            "est": float(s.get("est") or 60), "started": s.get("started"), "ended": s.get("ended"),
            "detail": s.get("detail", ""), "log": s.get("log", []), "frac": s.get("frac")}


def summary(job: dict | None) -> dict | None:
    """Job + computed pct / eta / current step (what the UI shows)."""
    if not job:
        return None
    now = time.time()
    steps = job["steps"]
    tot = sum(s["est"] for s in steps if s["status"] != "skipped") or 1.0
    done = sum(s["est"] for s in steps if s["status"] == "done")
    act = next((s for s in steps if s["status"] == "active"), None)
    frac = 0.0
    if act:
        if act.get("frac") is not None:
            frac = max(0.0, min(0.98, float(act["frac"])))
        elif act.get("started"):                              # no reported fraction: ease toward the estimate
            el = now - act["started"]
            frac = min(0.9, el / max(act["est"], 1.0) * 0.9)
    pct = (done + (act["est"] * frac if act else 0.0)) / tot
    if job.get("ended"):
        pct = 1.0
    # pace: actual vs estimated on finished steps
    fin = [s for s in steps if s["status"] == "done" and s.get("started") and s.get("ended")
           and s["ended"] - s["started"] >= 5]                # steps ticked off after the fact don't tell the pace
    ratio = 1.0
    if fin:
        ratio = sum(s["ended"] - s["started"] for s in fin) / max(sum(s["est"] for s in fin), 1.0)
        ratio = max(0.5, min(3.0, ratio))
    remaining = sum(s["est"] for s in steps if s["status"] == "pending") * ratio
    if act:
        remaining += max(0.0, act["est"] * ratio * (1 - frac))
    return {**job, "pct": round(pct, 4), "eta": None if job.get("ended") else round(remaining),
            "elapsed": round((job.get("ended") or now) - job["started"]),
            "current": act["title"] if act else None, "current_detail": act.get("detail", "") if act else ""}


def get() -> dict:
    with _lock:
        d = _load()
    return {"job": summary(d.get("job")), "history": d.get("history", [])}


def update(body: dict) -> dict:
    """Actions:
    {action: "start", title, steps:[{id,title,est}], detail?}  → new job (the previous one goes to history)
    {action: "step", id, status?, detail?, frac?, log?}         → change a step (status active/done/skipped/error)
    {action: "add", steps:[...], after?}                        → add upcoming steps
    {action: "log", text}                                       → a line under the active step
    {action: "finish", note?}  /  {action: "clear"}
    """
    a = body.get("action")
    now = time.time()
    with _lock:
        d = _load()
        job = d.get("job")
        if a == "start":
            if job:
                d["history"] = ([_archive(job, now)] + d.get("history", []))[:MAX_HISTORY]
            job = {"id": f"job_{int(now)}", "title": body.get("title") or "Editing", "detail": body.get("detail", ""),
                   "started": now, "ended": None, "steps": [_step(s) for s in body.get("steps", [])]}
        elif job is None:
            raise ValueError("no job running — start one first")
        elif a == "step":
            s = next((x for x in job["steps"] if x["id"] == str(body["id"])), None)
            if s is None:
                raise ValueError(f"unknown step {body['id']}")
            st = body.get("status")
            if st == "active":
                for o in job["steps"]:                       # one active step at a time
                    if o is not s and o["status"] == "active":
                        o.update(status="done", ended=now)
                s.update(status="active", started=s.get("started") or now, ended=None)
            elif st in ("done", "skipped", "error"):
                s.update(status=st, ended=now, started=s.get("started") or now, frac=None)
            elif st == "pending":
                s.update(status="pending", started=None, ended=None, frac=None)
            if "detail" in body:
                s["detail"] = body["detail"]
            if body.get("frac") is not None:
                s["frac"] = float(body["frac"])
            if body.get("est"):
                s["est"] = float(body["est"])
            if body.get("log"):
                s["log"] = (s.get("log", []) + [{"t": now, "text": body["log"]}])[-MAX_LOG:]
        elif a == "add":
            new = [_step(x) for x in body.get("steps", [])]
            after = body.get("after")
            idx = next((i + 1 for i, x in enumerate(job["steps"]) if x["id"] == after), len(job["steps"])) if after else len(job["steps"])
            job["steps"][idx:idx] = new
        elif a == "log":
            s = next((x for x in job["steps"] if x["status"] == "active"), None) or (job["steps"][-1] if job["steps"] else None)
            if s is not None:
                s["log"] = (s.get("log", []) + [{"t": now, "text": body.get("text", "")}])[-MAX_LOG:]
        elif a == "finish":
            for s in job["steps"]:
                if s["status"] == "active":
                    s.update(status="done", ended=now)
            job.update(ended=now, note=body.get("note", ""))
        elif a == "clear":
            d["history"] = ([_archive(job, now)] + d.get("history", []))[:MAX_HISTORY]
            job = None
        else:
            raise ValueError(f"unknown action {a}")
        d["job"] = job
        _save(d)
    return get()


def _archive(job: dict, now: float) -> dict:
    s = summary(job)
    return {"id": job["id"], "title": job["title"], "started": job["started"], "ended": job.get("ended") or now,
            "done": sum(1 for x in job["steps"] if x["status"] == "done"), "total": len(job["steps"]),
            "pct": s["pct"], "note": job.get("note", ""),
            "steps": [{"title": x["title"], "status": x["status"]} for x in job["steps"]]}
