"""Tiny client for the AnKar Video Editor server itself: the AI Editor's tools use the same HTTP API the editor UI uses, so
every change goes through the ops (undo history, live update in the browser)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class Http:
    def __init__(self, base: str | None = None):
        self.base = base or f"http://127.0.0.1:{os.environ.get('VLOG_PORT', '8765')}"

    def call(self, method: str, path: str, body=None, timeout=900):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            try:
                msg = json.loads(msg).get("error") or json.loads(msg).get("detail") or msg
            except ValueError:
                pass
            raise RuntimeError(str(msg)[:400]) from None

    def get(self, path, **kw):
        return self.call("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body or {}, **kw)

    def state(self):
        return self.get("/api/state")

    def batch(self, ops: list, label: str):
        return self.post("/api/op", {"batch": [{"op": o["op"], "args": o.get("args", {})} for o in ops], "label": label})
