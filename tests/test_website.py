"""Website accounts API (website/api/_lib) on a temporary SQLite database — sign-up/in, lockout, CSRF, download
records the version, update badge, email reset codes, my data, delete, admin TOTP gate, no secrets in responses.
python -m pytest tests/test_website.py"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "website" / "api"))
sys.path.insert(0, str(ROOT / "cache" / "website-test-libs"))          # segno (QR codes), installed only for tests

from starlette.testclient import TestClient  # noqa: E402

from _lib import app as site  # noqa: E402
from _lib import db, mail, security as sec  # noqa: E402

PW = "purple tiger sings loud"
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKAR_MAIL_TEST", "1")
    monkeypatch.setenv("DATA_KEY", "ab" * 32)
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("GITHUB_REPO", "someone/ankar-video-editor")
    db.reset_for_tests(tmp_path / "t.db")
    mail.sent_for_tests.clear()
    rel = tmp_path / "releases.json"
    rel.write_text(json.dumps({"repo": "", "releases": [
        {"version": "1.1.0", "date": "2026-12-01", "notes": ["New thing"]},
        {"version": "1.0.0", "date": "2026-11-12", "notes": ["First"]}]}))
    monkeypatch.setattr(site, "RELEASES", rel)
    return TestClient(site.app)


def post(c, path, body, headers=ORIGIN):
    return c.post(path, json=body, headers=headers)


def signup(c, name="alice", email=None):
    r = post(c, "/api/signup", {"username": name, "password": PW, "email": email})
    assert r.status_code == 200, r.text
    return r


def test_signup_signin_and_stored_fields(c):
    r = signup(c, "Alice", email="alice@example.com")
    assert r.json()["username"] == "Alice" and r.json()["email"].startswith("a•") and "ankar_s" in r.cookies
    row = db.q("SELECT * FROM users", one=True)
    assert PW not in json.dumps(row) and row["pw_hash"].startswith("scrypt$")
    assert "alice@example.com" not in json.dumps(row)                        # email only encrypted
    assert post(c, "/api/signup", {"username": "alice", "password": PW}).status_code == 409   # case-insensitive
    c.cookies.clear()
    assert c.get("/api/me").json() == {"signed_in": False}
    assert post(c, "/api/signin", {"username": "ALICE", "password": PW}).status_code == 200
    assert c.get("/api/me").json()["username"] == "Alice"


def test_password_and_username_rules(c):
    for u, p in (("ab", PW), ("admin", PW), ("bad name", PW), ("okname", "short"), ("okname", "password123"),
                 ("okname", "okname is my password")):
        assert post(c, "/api/signup", {"username": u, "password": p}).status_code == 400, (u, p)


def test_csrf_other_sites_and_non_json_are_blocked(c):
    assert post(c, "/api/signup", {"username": "x1x", "password": PW}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert post(c, "/api/signup", {"username": "x1x", "password": PW}, headers={}).status_code == 403
    r = c.post("/api/signup", content="username=x1x", headers={**ORIGIN, "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_lockout_after_5_wrong_passwords(c):
    signup(c)
    c.cookies.clear()
    codes = [post(c, "/api/signin", {"username": "alice", "password": "wrong password!!"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 429]
    assert post(c, "/api/signin", {"username": "alice", "password": PW}).status_code == 429     # even the right one
    assert post(c, "/api/signin", {"username": "nobody", "password": PW}).json()["detail"] == "Wrong username or password."


def test_download_records_version_and_update_badge(c):
    signup(c)
    assert c.get("/api/me").json()["update_available"] is False                # never downloaded → no badge
    r = c.get("/api/download", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == \
        "https://github.com/someone/ankar-video-editor/releases/download/v1.1.0/AnKar-Video-Editor-1.1.0.zip"
    me = c.get("/api/me").json()
    assert me["last_version"] == "1.1.0" and not me["update_available"]
    db.q("UPDATE users SET last_version = '1.0.0'")
    me = c.get("/api/me").json()
    assert me["update_available"] and [n["version"] for n in me["notes_since"]] == ["1.1.0"]
    c.cookies.clear()
    assert c.get("/api/download", follow_redirects=False).headers["location"].startswith("/signin")


def test_latest_is_public_and_anonymous(c):
    r = c.get("/api/latest")
    assert r.status_code == 200 and r.json()["version"] == "1.1.0" and r.json()["download_page"].endswith("/account")
    assert "set-cookie" not in r.headers


def test_forgot_password_code_single_use_and_same_answer(c):
    signup(c, email="alice@example.com")
    signup(c, "bob")                                                             # no email
    c.cookies.clear()
    a = post(c, "/api/forgot", {"username": "alice"}).json()
    b = post(c, "/api/forgot", {"username": "bob"}).json()
    n = post(c, "/api/forgot", {"username": "nobody"}).json()
    assert a == b == n                                                           # no account probing
    assert len(mail.sent_for_tests) == 1 and mail.sent_for_tests[0]["to"] == "alice@example.com"
    code = mail.sent_for_tests[0]["code"]
    assert post(c, "/api/reset", {"username": "alice", "code": "000000" if code != "000000" else "111111", "new": "brand new password"}).status_code == 400
    assert post(c, "/api/reset", {"username": "alice", "code": code, "new": "brand new password"}).status_code == 200
    assert post(c, "/api/reset", {"username": "alice", "code": code, "new": "another new password"}).status_code == 400   # used
    c.cookies.clear()
    assert post(c, "/api/signin", {"username": "alice", "password": "brand new password"}).status_code == 200


def test_reset_code_expires(c):
    signup(c, email="alice@example.com")
    post(c, "/api/forgot", {"username": "alice"})
    db.q("UPDATE resets SET expires_at = ?", (int(time.time()) - 1,))
    code = mail.sent_for_tests[0]["code"]
    assert post(c, "/api/reset", {"username": "alice", "code": code, "new": "brand new password"}).status_code == 400


def test_change_password_email_mydata_delete(c):
    signup(c)
    assert post(c, "/api/password", {"current": "nope nope nope", "new": "brand new password"}).status_code == 401
    assert post(c, "/api/password", {"current": PW, "new": "brand new password"}).status_code == 200
    r = post(c, "/api/email", {"email": "a@b.example", "password": "brand new password"})
    assert r.status_code == 200 and r.json()["email"] == "a@b.example".replace("a@", "a•@")
    d = c.get("/api/mydata").json()
    assert d["email"] == "a@b.example" and "hash" in d["password"] and "scrypt$" not in json.dumps(d)
    assert post(c, "/api/delete", {"password": PW}).status_code == 401
    assert post(c, "/api/delete", {"password": "brand new password"}).status_code == 200
    assert db.q("SELECT COUNT(*) AS n FROM users", one=True)["n"] == 0
    assert db.q("SELECT COUNT(*) AS n FROM sessions", one=True)["n"] == 0


def test_admin_needs_owner_and_authenticator(c):
    signup(c, "alice")
    assert c.get("/api/admin/stats").status_code == 403                         # not the owner
    c.cookies.clear()
    signup(c, "boss")
    assert c.get("/api/admin/stats").status_code == 403                         # owner, but no TOTP yet
    r = post(c, "/api/admin/totp/setup", {"password": PW})
    assert r.status_code == 200 and r.json()["qr"].startswith("data:image/svg+xml")
    secret = r.json()["secret"]
    assert post(c, "/api/admin/totp/verify", {"code": "123456"}).status_code == 401
    good = sec._hotp(secret, int(time.time() // 30))
    assert post(c, "/api/admin/totp/verify", {"code": good}).status_code == 200
    assert post(c, "/api/admin/totp/verify", {"code": good}).status_code == 401  # no replay
    s = c.get("/api/admin/stats").json()
    assert s["users"] == 2 and [u["user"] for u in s["list"]] == [1, 2]
    blob = json.dumps(s)
    assert "alice" not in blob and "scrypt" not in blob and "@" not in blob     # anonymous
    assert post(c, "/api/admin/user", {"user": 1, "action": "disable"}).status_code == 200
    c2 = TestClient(site.app)
    assert post(c2, "/api/signin", {"username": "alice", "password": PW}).status_code == 401


def test_no_secret_in_any_response(c):
    r = signup(c, email="alice@example.com")
    tok = r.cookies["ankar_s"]
    for path in ("/api/me", "/api/mydata", "/api/latest", "/api/config"):
        body = c.get(path).text
        assert tok not in body and "scrypt$" not in body and sec.token_hash(tok) not in body


def test_totp_rfc6238_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"                                # RFC 6238 test key "12345678901234567890"
    assert sec._hotp(secret, 59 // 30) == "287082"
    assert sec.totp_check(secret, "287082", 0, now=59) == 1 and sec.totp_check(secret, "287082", 1, now=59) is None
