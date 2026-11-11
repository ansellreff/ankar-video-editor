"""Feedback & Change Log helper (POST /api/changelog). Python API used by the edit scripts; CLI for quick entries:
python -m scripts.changelog set <project> <id> [--status done] [--change "..."]"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

URL = os.environ.get("VLOG_URL", "http://localhost:8765")


def send(project, **body):
    body["project"] = project
    req = urllib.request.Request(URL + "/api/changelog", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def new_round(project, title, checkpoint_before=None):
    return send(project, action="round", title=title, checkpoint_before=checkpoint_before)


def add(project, video, item, decision="change", reason="", id=None, status="todo"):
    return send(project, action="add", video=video, item=item, decision=decision, reason=reason, id=id, status=status)


def note(project, id, change=None, status=None, decision=None, reason=None):
    b = {"action": "set", "id": id}
    for k, v in (("change", change), ("status", status), ("decision", decision), ("reason", reason)):
        if v is not None:
            b[k] = v
    try:
        return send(project, **b)
    except Exception as e:  # noqa: BLE001  (logging must never break the edit)
        print("[changelog]", e)


def round_done(project, checkpoint_after):
    return send(project, action="round_done", checkpoint_after=checkpoint_after)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("project")
    ap.add_argument("id")
    ap.add_argument("--status")
    ap.add_argument("--change")
    a = ap.parse_args()
    if a.cmd == "set":
        note(a.project, a.id, a.change, a.status)
