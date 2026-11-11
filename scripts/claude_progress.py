"""Report Claude's editing progress to the editor's pop-up (POST /api/claude/progress). Server: env VLOG_URL or :8765.

python -m scripts.claude_progress start "Title" steps.json [--detail "..."]   (steps.json: [{id, title, est}] or inline JSON)
python -m scripts.claude_progress step <id> active|done|skipped|error|pending [--detail ".."] [--frac 0.4] [--log ".."] [--est 120]
python -m scripts.claude_progress add steps.json [--after <id>]
python -m scripts.claude_progress log "text"
python -m scripts.claude_progress finish ["note"]
python -m scripts.claude_progress show
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

URL = os.environ.get("VLOG_URL", "http://localhost:8765")


def send(body=None):
    req = urllib.request.Request(URL + "/api/claude/progress", data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _steps(arg):
    if os.path.exists(arg):
        with open(arg, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(arg)


# python API (used by the build scripts)
def start(title, steps, detail=""):
    return send({"action": "start", "title": title, "steps": steps, "detail": detail})


def step(id, status=None, detail=None, frac=None, log=None, est=None):
    b = {"action": "step", "id": id}
    for k, v in (("status", status), ("detail", detail), ("frac", frac), ("log", log), ("est", est)):
        if v is not None:
            b[k] = v
    try:
        return send(b)
    except Exception as e:  # noqa: BLE001  (progress reporting must never break the actual work)
        print(f"[progress] {e}", file=sys.stderr)


def log(text):
    try:
        return send({"action": "log", "text": text})
    except Exception as e:  # noqa: BLE001
        print(f"[progress] {e}", file=sys.stderr)


def finish(note=""):
    return send({"action": "finish", "note": note})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--detail")
    ap.add_argument("--frac", type=float)
    ap.add_argument("--log")
    ap.add_argument("--est", type=float)
    ap.add_argument("--after")
    a = ap.parse_args()
    if a.cmd == "start":
        r = start(a.args[0], _steps(a.args[1]), a.detail or "")
    elif a.cmd == "step":
        r = step(a.args[0], a.args[1] if len(a.args) > 1 else None, a.detail, a.frac, a.log, a.est)
    elif a.cmd == "add":
        r = send({"action": "add", "steps": _steps(a.args[0]), "after": a.after})
    elif a.cmd == "log":
        r = log(" ".join(a.args))
    elif a.cmd == "finish":
        r = finish(" ".join(a.args))
    elif a.cmd == "show":
        r = send()
    else:
        sys.exit(f"unknown command {a.cmd}")
    j = (r or {}).get("job")
    if j:
        print(f"{round(j['pct'] * 100)}% · now: {j.get('current')} · eta {j.get('eta')} s")


if __name__ == "__main__":
    main()
