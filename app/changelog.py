"""Feedback & Change Log (per project): every review note the user gives, Claude's decision on it, what was changed, when,
and the checkpoints before/after — so any change can be checked and undone (File ▸ Revert to Checkpoint).

Stored in projects/<name>/docs/changelog.json (+ a readable changelog.md next to it).
Entry: {id, created, updated, round, video, item (the user's words), decision: change|correct|partly, reason,
        status: todo|doing|done|verified, changes:[{time, text}], checkpoint_before, checkpoint_after}
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from .paths import PROJECTS

_lock = threading.Lock()


def _file(project: str):
    return PROJECTS / project / "docs" / "changelog.json"


def load(project: str) -> dict:
    f = _file(project)
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"rounds": [], "entries": []}


def _save(project: str, d: dict):
    f = _file(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)
    (f.with_suffix(".md")).write_text(markdown(project, d), encoding="utf-8")


def _ts(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def markdown(project: str, d: dict) -> str:
    out = [f"# Feedback & Change Log: {project}", ""]
    for r in sorted(d.get("rounds", []), key=lambda r: r["created"], reverse=True):
        out += [f"## {r['title']} ({_ts(r['created'])})", ""]
        if r.get("checkpoint_before"):
            out.append(f"Checkpoint before: `{r['checkpoint_before']}`" + (f" · after: `{r['checkpoint_after']}`" if r.get("checkpoint_after") else ""))
            out.append("")
        for e in [e for e in d.get("entries", []) if e.get("round") == r["id"]]:
            out.append(f"### {e['id']} · {e.get('video', '')} · {e['status'].upper()}")
            out.append(f"- **Your note:** {e['item']}")
            out.append(f"- **Decision:** {e['decision']}" + (f" ({e['reason']})" if e.get("reason") else ""))
            for c in e.get("changes", []):
                out.append(f"- {_ts(c['time'])} · {c['text']}")
            out.append("")
    return "\n".join(out)


def update(project: str, body: dict) -> dict:
    """{action: round, title, checkpoint_before?} → new round
       {action: add, round?, video, item, decision, reason?, status?}
       {action: set, id, status?, decision?, reason?, change? (text appended with time)}
       {action: round_done, round?, checkpoint_after}"""
    a = body.get("action")
    now = time.time()
    with _lock:
        d = load(project)
        rounds = d.setdefault("rounds", [])
        ents = d.setdefault("entries", [])
        cur = rounds[-1]["id"] if rounds else None
        if a == "round":
            rid = f"R{len(rounds) + 1}"
            rounds.append({"id": rid, "title": body.get("title") or f"Feedback round {len(rounds) + 1}", "created": now,
                           "checkpoint_before": body.get("checkpoint_before"), "checkpoint_after": None})
        elif a == "add":
            rid = body.get("round") or cur
            n = sum(1 for e in ents if e.get("round") == rid) + 1
            ents.append({"id": body.get("id") or f"{rid}.{n}", "round": rid, "created": now, "updated": now,
                         "video": body.get("video", ""), "item": body["item"], "decision": body.get("decision", "change"),
                         "reason": body.get("reason", ""), "status": body.get("status", "todo"), "changes": []})
        elif a == "set":
            e = next((x for x in ents if x["id"] == body["id"]), None)
            if e is None:
                raise ValueError(f"no entry {body['id']}")
            for k in ("status", "decision", "reason", "video"):
                if k in body:
                    e[k] = body[k]
            if body.get("change"):
                e["changes"].append({"time": now, "text": body["change"]})
            e["updated"] = now
        elif a == "round_done":
            r = next((x for x in rounds if x["id"] == (body.get("round") or cur)), None)
            if r:
                r["checkpoint_after"] = body.get("checkpoint_after")
                r["done"] = now
        else:
            raise ValueError(f"unknown action {a}")
        _save(project, d)
        return d
