"""Small client for the running AnKar Video Editor server (default: the user's editor on :8765 — every op shows up live in the UI).
Used by the "Having Fun in Taiwan" build scripts. Env VLOG_URL overrides the server address."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

URL = os.environ.get("VLOG_URL", "http://localhost:8765")


def call(method: str, path: str, body=None, timeout=600):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(URL + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} → {e.code}: {msg[:400]}") from None


def get(path, **kw):
    return call("GET", path, **kw)


def post(path, body=None, **kw):
    return call("POST", path, body or {}, **kw)


def state():
    return get("/api/state")


def op(_op, _label=None, **args):
    return post("/api/op", {"op": _op, "args": args, "label": _label or _op})


def batch(ops, label):
    """ops: [(name, args), ...] → one undo step. Returns the server's reply (includes created ids per op)."""
    return post("/api/op", {"batch": [{"op": n, "args": a} for n, a in ops], "label": label})


def assets_by_name():
    """{file name (lower): asset entry} for the open project."""
    out = {}
    for a in state()["assets"]:
        out[os.path.basename(a["path"]).lower()] = a
    return out


class Events:
    """Listen to the server's SSE stream in a thread; wait_for(kind, pred) returns the first matching event's data."""

    def __init__(self):
        self.items, self.cv = [], threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()
        time.sleep(0.5)

    def _run(self):
        while True:
            try:
                with urllib.request.urlopen(URL + "/api/events", timeout=3600) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if not line.startswith("data:"):
                            continue
                        try:
                            msg = json.loads(line[5:].strip())                 # server sends {"type": kind, "data": ...}
                        except ValueError:
                            continue
                        with self.cv:
                            self.items.append((msg.get("type"), msg.get("data")))
                            self.cv.notify_all()
            except Exception:  # noqa: BLE001
                time.sleep(1)

    def wait_for(self, kind, pred=lambda d: True, timeout=900):
        end = time.time() + timeout
        with self.cv:
            seen = 0
            while time.time() < end:
                for k, d in self.items[seen:]:
                    if k == kind and pred(d if d is not None else {}):
                        return d
                seen = len(self.items)
                self.cv.wait(timeout=1.0)
        raise TimeoutError(f"no '{kind}' event within {timeout} s")
