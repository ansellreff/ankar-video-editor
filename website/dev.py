"""Run the website on this PC for testing (SQLite instead of Neon, codes printed instead of emailed):

    .venv\\Scripts\\python -m website.dev          → http://localhost:3000

Serves public/ like Vercel does (clean URLs, the security headers from vercel.json) and the API at /api/*."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "api"))
os.environ.setdefault("ANKAR_MAIL_TEST", "1")
os.environ.setdefault("DATA_KEY", "00" * 32)                 # local testing only — Vercel gets a real random one

from fastapi.responses import FileResponse, Response  # noqa: E402

from _lib.app import app  # noqa: E402

PUBLIC = HERE / "public"
HEADERS = {h["key"]: h["value"] for h in json.loads((HERE / "vercel.json").read_text())["headers"][0]["headers"]}
HEADERS.pop("Strict-Transport-Security", None)               # not over http://localhost
HEADERS["Content-Security-Policy"] = HEADERS["Content-Security-Policy"].replace("; upgrade-insecure-requests", "")


@app.middleware("http")
async def vercel_like(request, call_next):
    r = await call_next(request)
    for k, v in HEADERS.items():
        r.headers.setdefault(k, v)
    return r


@app.get("/{path:path}")
def static(path: str):
    p = (PUBLIC / path).resolve()
    if PUBLIC not in p.parents and p != PUBLIC:
        return Response(status_code=404)
    for c in (p / "index.html", p.with_suffix(".html") if p.suffix == "" else p, p):
        if c.is_file():
            return FileResponse(c)
    return FileResponse(PUBLIC / "404.html", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "3000")))
