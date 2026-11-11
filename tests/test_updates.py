"""Version + update reminder: compares versions, reads a fake website, stays quiet when offline or given bad data.
python -m pytest tests/test_updates.py"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import releasenotes, updates, version


def test_versions():
    assert version.parse("v1.2.3") == (1, 2, 3)
    assert version.newer("1.10.0", "1.9.9") and not version.newer("1.0.0", "1.0.0")
    for bad in ("1.2", "1.2.3.4", "x.1.2", "", "1.2.3-beta"):
        with pytest.raises(ValueError):
            version.parse(bad)


def test_changelog_has_this_version():
    rels = releasenotes.load()
    assert rels and rels[0]["version"] == version.VERSION, "CHANGELOG.md must start with the current version"
    assert rels[0]["notes"] and rels[0]["date"]


def test_changelog_parse():
    rels = releasenotes.parse("# C\n\n## 1.1.0 — 2026-12-01\n- A\n  wrapped\n- B\n\n## 1.0.0 - 2026-11-12\n* C\n")
    assert rels == [{"version": "1.1.0", "date": "2026-12-01", "notes": ["A wrapped", "B"]},
                    {"version": "1.0.0", "date": "2026-11-12", "notes": ["C"]}]


class Site:
    def __init__(self, body):
        self.body = body
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append((self.path, dict(self.headers)))
                data = outer.body if isinstance(outer.body, bytes) else json.dumps(outer.body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.hits = []
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "CACHE_FILE", tmp_path / "update_check.json")
    monkeypatch.setattr(updates, "VERSION", "1.0.0")
    monkeypatch.delenv("ANKAR_UPDATE_CHECK", raising=False)
    return monkeypatch


def latest(v, page=None):
    return {"version": v, "date": "2026-12-01", "download_page": page,
            "releases": [{"version": v, "date": "2026-12-01", "notes": ["New thing"]},
                         {"version": "1.0.0", "date": "2026-11-12", "notes": ["First"]}]}


def test_newer_version_is_reported_with_notes(env):
    s = Site(latest("1.1.0"))
    env.setenv("ANKAR_SITE", s.url)
    try:
        r = updates.check(force=True)
        assert r["newer"] and r["latest"] == "1.1.0"
        assert [n["version"] for n in r["notes"]] == ["1.1.0"]         # only versions newer than mine
        assert r["download_page"] == s.url + "/account"                 # missing link → the site's own account page
        path, headers = s.hits[0]
        assert path == "/api/latest" and "Cookie" not in headers        # anonymous: nothing about the user is sent
        updates.check()
        assert len(s.hits) == 1                                         # cached: at most once a day
    finally:
        s.close()


def test_same_version_and_foreign_links(env):
    s = Site(latest("1.0.0", page="https://evil.example/download"))
    env.setenv("ANKAR_SITE", s.url)
    try:
        r = updates.check(force=True)
        assert not r["newer"] and r["notes"] == []
        assert r["download_page"].startswith(s.url)                    # never a link to another website
    finally:
        s.close()


def test_offline_and_bad_answers_mean_no_reminder(env):
    env.setenv("ANKAR_SITE", "http://127.0.0.1:9")                     # nothing listens there
    r = updates.check(force=True)
    assert r["newer"] is False and r["latest"] is None and r["error"]
    for body in (b"<html>not json</html>", {"version": "<script>"}, {"nothing": 1}):
        s = Site(body)
        env.setenv("ANKAR_SITE", s.url)
        try:
            r = updates.check(force=True)
            assert r["newer"] is False and r["latest"] is None
        finally:
            s.close()


def test_turned_off(env):
    env.setenv("ANKAR_UPDATE_CHECK", "0")
    assert updates.check()["disabled"]
