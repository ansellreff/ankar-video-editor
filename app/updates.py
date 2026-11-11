"""Update reminder: is a newer AnKar Video Editor on the website?

Privacy: one anonymous GET of <SITE>/api/latest (at start, then at most once a day). Nothing about the user, their
projects or their keys is sent; no account is needed. Offline / site down → simply no reminder.
Turn it off with env ANKAR_UPDATE_CHECK=0. Tests point it elsewhere with ANKAR_SITE."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request

from . import releasenotes
from .paths import CACHE
from .version import NAME, VERSION, newer, parse
from . import version as _v

CACHE_FILE = CACHE / "update_check.json"
EVERY_S = 24 * 3600
_lock = threading.Lock()


def _site() -> str:
    return os.environ.get("ANKAR_SITE", _v.SITE).rstrip("/")


def _safe_url(u, site: str) -> str | None:
    """Only links to the AnKar website itself are ever opened from an update notice."""
    if isinstance(u, str) and (u == site or u.startswith(site + "/")) and not re.search(r"[\s<>\"']", u):
        return u
    return None


def _clean(data: dict, site: str) -> dict:
    """Keep only well-formed fields from the site's answer (it is data, never code)."""
    latest = data.get("version")
    parse(latest)
    rels = []
    for r in (data.get("releases") or [])[:50]:
        try:
            parse(r.get("version"))
        except (ValueError, AttributeError):
            continue
        notes = [str(n)[:400] for n in (r.get("notes") or [])[:40] if isinstance(n, str)]
        rels.append({"version": r["version"], "date": str(r.get("date", ""))[:10], "notes": notes})
    return {"version": latest, "date": str(data.get("date", ""))[:10], "releases": rels,
            "download_page": _safe_url(data.get("download_page"), site) or site + "/account"}


def _fetch(site: str) -> dict:
    req = urllib.request.Request(site + "/api/latest", headers={"User-Agent": f"{NAME}/{VERSION}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=6) as r:
        if r.status != 200:
            raise OSError(f"HTTP {r.status}")
        return _clean(json.loads(r.read(200_000).decode("utf-8")), site)


def check(force: bool = False) -> dict:
    """{current, latest, newer, notes: [releases newer than this one], download_page, checked, error?}"""
    site = _site()
    base = {"current": VERSION, "site": site, "local_notes": releasenotes.load()}
    if os.environ.get("ANKAR_UPDATE_CHECK", "1") == "0":
        return {**base, "latest": None, "newer": False, "notes": [], "disabled": True}
    with _lock:
        cached = {}
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        fresh = cached.get("site") == site and time.time() - cached.get("checked", 0) < EVERY_S and cached.get("data")
        err = None
        if force or not fresh:
            try:
                cached = {"site": site, "checked": time.time(), "data": _fetch(site)}
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(json.dumps(cached), encoding="utf-8")
            except Exception as e:  # noqa: BLE001 — offline / site down / bad answer: no reminder
                err = type(e).__name__
                if cached.get("site") != site:
                    cached = {}
    d = cached.get("data")
    if not d:
        return {**base, "latest": None, "newer": False, "notes": [], "error": err or "no data"}
    is_newer = newer(d["version"], VERSION)
    notes = [r for r in d["releases"] if newer(r["version"], VERSION)]
    return {**base, "latest": d["version"], "date": d["date"], "newer": is_newer, "notes": notes,
            "download_page": d["download_page"], "checked": cached.get("checked"), **({"error": err} if err else {})}
