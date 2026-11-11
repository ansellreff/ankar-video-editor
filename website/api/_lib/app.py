"""AnKar Video Editor website API (Vercel Python function; locally: python -m website.dev).

Accounts store only what the update reminder needs: username, password hash, optional email (encrypted, only for
"forgot password"), latest downloaded version + date. No IP addresses, no tracking, no analytics.
Every request that changes something must come from this site itself (Origin check + JSON body)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import db, mail
from . import security as sec

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
RELEASES = Path(__file__).with_name("releases.json")
SESSION_S = 30 * 24 * 3600
ADMIN_S = 30 * 60                      # an authenticator code unlocks the admin page for 30 minutes
MAX_FAILS, LOCK_S = 5, 15 * 60
COOKIE = "ankar_s"


# ---------------------------------------------------------------- helpers
def now() -> int:
    return int(time.time())


def releases() -> dict:
    d = json.loads(RELEASES.read_text(encoding="utf-8"))
    d["repo"] = os.environ.get("GITHUB_REPO") or d.get("repo", "")
    return d


def vkey(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def site_url(request: Request) -> str:
    return os.environ.get("SITE_URL", "").rstrip("/") or f"{request.url.scheme}://{request.headers.get('host', '')}"


def secure_cookies(request: Request) -> bool:
    return request.url.scheme == "https" or bool(os.environ.get("VERCEL"))


def same_origin(request: Request):
    """CSRF protection: state-changing requests must be JSON sent by this site's own pages."""
    origin = request.headers.get("origin")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not origin or urlsplit(origin).netloc != host:
        raise HTTPException(403, "Blocked: this request didn't come from the AnKar website.")
    if not (request.headers.get("content-type") or "").startswith("application/json"):
        raise HTTPException(415, "Send JSON.")


async def body(request: Request) -> dict:
    same_origin(request)
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, "Too much data.")
    try:
        d = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Bad request.")
    if not isinstance(d, dict):
        raise HTTPException(400, "Bad request.")
    return d


def limit(key: str, max_n: int, window_s: int):
    """Simple fixed-window counter in the database (keys are usernames or 'global', never IP addresses)."""
    t = now()
    row = db.q("SELECT start, n FROM limits WHERE k = ?", (key,), one=True)
    if not row or t - row["start"] >= window_s:
        db.q("INSERT INTO limits (k, start, n) VALUES (?, ?, 1) ON CONFLICT (k) DO UPDATE SET start = excluded.start, n = 1", (key, t))
        return
    if row["n"] >= max_n:
        wait = window_s - (t - row["start"])
        raise HTTPException(429, f"Too many tries. Please wait {max(1, wait // 60)} minute(s).")
    db.q("UPDATE limits SET n = n + 1 WHERE k = ?", (key,))


def user_by_name(username: str):
    return db.q("SELECT * FROM users WHERE username_lc = ?", (str(username or "").strip().lower(),), one=True)


def current(request: Request, need: bool = True):
    """(user, session) for the signed-in browser, or (None, None)."""
    tok = request.cookies.get(COOKIE)
    if tok and len(tok) < 100:
        s = db.q("SELECT * FROM sessions WHERE token_hash = ?", (sec.token_hash(tok),), one=True)
        if s and s["expires_at"] > now():
            u = db.q("SELECT * FROM users WHERE id = ?", (s["user_id"],), one=True)
            if u and not u["disabled"]:
                return u, s
    if need:
        raise HTTPException(401, "Please sign in.")
    return None, None


def is_admin(u) -> bool:
    a = os.environ.get("ADMIN_USERNAME", "").strip().lower()
    return bool(u and a and u["username_lc"] == a)


def start_session(request: Request, user_id: int, payload: dict) -> JSONResponse:
    tok = sec.new_token()
    t = now()
    db.q("DELETE FROM sessions WHERE expires_at < ?", (t,))
    db.q("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
         (sec.token_hash(tok), user_id, t, t + SESSION_S))
    r = JSONResponse(payload)
    r.set_cookie(COOKIE, tok, max_age=SESSION_S, httponly=True, secure=secure_cookies(request), samesite="lax", path="/")
    return r


def me_payload(u) -> dict:
    rel = releases()
    latest = rel["releases"][0] if rel["releases"] else None
    have = u["last_version"]
    newer = [r for r in rel["releases"] if have and vkey(r["version"]) > vkey(have)]
    email = None
    if u["email_enc"]:
        try:
            email = sec.mask_email(sec.decrypt(u["email_enc"], f"email:{u['id']}"))
        except Exception:  # noqa: BLE001
            email = "(saved)"
    return {"username": u["username"], "joined": time.strftime("%Y-%m-%d", time.gmtime(u["created_at"])),
            "last_version": have,
            "last_download": time.strftime("%Y-%m-%d", time.gmtime(u["last_download_at"])) if u["last_download_at"] else None,
            "latest": latest, "update_available": bool(have and latest and vkey(latest["version"]) > vkey(have)),
            "notes_since": newer, "email": email, "email_possible": sec.can_encrypt(), "admin": is_admin(u)}


def check_password_or_lock(u, pw: str):
    """Wrong password → count; 5 in a row → locked 15 minutes. Same message whether or not the username exists."""
    if not u:
        sec.burn_time(pw if isinstance(pw, str) else "")
        raise HTTPException(401, "Wrong username or password.")
    t = now()
    if u["locked_until"] > t:
        raise HTTPException(429, f"Too many wrong passwords. Try again in {(u['locked_until'] - t) // 60 + 1} minute(s).")
    if isinstance(pw, str) and len(pw) <= sec.MAX_PW and sec.check_pw(pw, u["pw_hash"]):
        if u["failed"]:
            db.q("UPDATE users SET failed = 0 WHERE id = ?", (u["id"],))
        return
    fails = u["failed"] + 1
    if fails >= MAX_FAILS:
        db.q("UPDATE users SET failed = 0, locked_until = ? WHERE id = ?", (t + LOCK_S, u["id"]))
        raise HTTPException(429, "Too many wrong passwords. This account is locked for 15 minutes.")
    db.q("UPDATE users SET failed = ? WHERE id = ?", (fails, u["id"]))
    raise HTTPException(401, "Wrong username or password.")


@app.middleware("http")
async def no_store(request: Request, call_next):
    r = await call_next(request)
    if request.url.path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-store"
        r.headers["X-Content-Type-Options"] = "nosniff"
    return r


# ---------------------------------------------------------------- public
@app.get("/api/latest")
def api_latest(request: Request):
    """Used by the app's update reminder. Anonymous: needs no account, records nothing."""
    rel = releases()
    latest = rel["releases"][0]
    r = JSONResponse({"version": latest["version"], "date": latest["date"], "releases": rel["releases"],
                      "download_page": site_url(request) + "/account"})
    r.headers["Cache-Control"] = "public, max-age=600"
    return r


@app.get("/api/config")
def api_config():
    return {"email_reset": mail.configured() and sec.can_encrypt(), "email_possible": sec.can_encrypt(),
            "min_password": sec.MIN_PW, "repo": releases()["repo"]}


# ---------------------------------------------------------------- accounts
@app.post("/api/signup")
async def api_signup(request: Request):
    d = await body(request)
    username, pw, email = str(d.get("username", "")).strip(), d.get("password"), (d.get("email") or "").strip()
    for problem in (sec.username_problem(username), sec.pw_problem(pw, username),
                    sec.email_problem(email) if email else None):
        if problem:
            raise HTTPException(400, problem)
    if email and not sec.can_encrypt():
        raise HTTPException(400, "Saving an email isn't available on this site yet — leave it empty for now.")
    limit("signup:global", 300, 3600)                         # slows down bots without tracking anyone
    if user_by_name(username):
        raise HTTPException(409, "That username is taken. Please pick another.")
    row = db.q("INSERT INTO users (username, username_lc, pw_hash, created_at) VALUES (?, ?, ?, ?) RETURNING id",
               (username, username.lower(), sec.hash_pw(pw), now()), one=True)
    if email:
        db.q("UPDATE users SET email_enc = ? WHERE id = ?", (sec.encrypt(email, f"email:{row['id']}"), row["id"]))
    u = db.q("SELECT * FROM users WHERE id = ?", (row["id"],), one=True)
    return start_session(request, u["id"], me_payload(u))


@app.post("/api/signin")
async def api_signin(request: Request):
    d = await body(request)
    username, pw = str(d.get("username", "")).strip(), d.get("password")
    limit(f"signin:{username.lower()[:40]}", 20, 3600)
    u = user_by_name(username)
    if u and u["disabled"]:
        sec.burn_time(pw if isinstance(pw, str) else "")
        raise HTTPException(401, "Wrong username or password.")
    check_password_or_lock(u, pw)
    return start_session(request, u["id"], me_payload(u))


@app.post("/api/signout")
async def api_signout(request: Request):
    same_origin(request)
    tok = request.cookies.get(COOKIE)
    if tok:
        db.q("DELETE FROM sessions WHERE token_hash = ?", (sec.token_hash(tok),))
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r


@app.get("/api/me")
def api_me(request: Request):
    u, _ = current(request, need=False)
    return me_payload(u) if u else {"signed_in": False}


@app.get("/api/mydata")
def api_mydata(request: Request):
    """Everything stored about you, exactly."""
    u, _ = current(request)
    email = None
    if u["email_enc"]:
        try:
            email = sec.decrypt(u["email_enc"], f"email:{u['id']}")
        except Exception:  # noqa: BLE001
            email = "(encrypted, can't be read with the current key)"
    n = db.q("SELECT COUNT(*) AS n FROM sessions WHERE user_id = ? AND expires_at > ?", (u["id"], now()), one=True)["n"]
    return {"user_number": u["id"], "username": u["username"], "password": "only a one-way scrypt hash (nobody can read your password)",
            "email": email, "joined": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(u["created_at"])),
            "latest_downloaded_version": u["last_version"],
            "latest_download_date": time.strftime("%Y-%m-%d", time.gmtime(u["last_download_at"])) if u["last_download_at"] else None,
            "signed_in_browsers": n, "anything_else": "nothing — no IP addresses, no tracking, no projects, no API keys"}


@app.post("/api/password")
async def api_password(request: Request):
    d = await body(request)
    u, s = current(request)
    check_password_or_lock(u, d.get("current"))
    p = sec.pw_problem(d.get("new"), u["username"])
    if p:
        raise HTTPException(400, p)
    db.q("UPDATE users SET pw_hash = ? WHERE id = ?", (sec.hash_pw(d["new"]), u["id"]))
    db.q("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (u["id"], s["token_hash"]))   # sign out elsewhere
    return {"ok": True}


@app.post("/api/email")
async def api_email(request: Request):
    """Add / change / remove the optional email (only used for "forgot password"). Needs the password."""
    d = await body(request)
    u, _ = current(request)
    check_password_or_lock(u, d.get("password"))
    email = (d.get("email") or "").strip()
    if not email:
        db.q("UPDATE users SET email_enc = NULL WHERE id = ?", (u["id"],))
    else:
        p = sec.email_problem(email)
        if p:
            raise HTTPException(400, p)
        if not sec.can_encrypt():
            raise HTTPException(400, "Saving an email isn't available on this site yet.")
        db.q("UPDATE users SET email_enc = ? WHERE id = ?", (sec.encrypt(email, f"email:{u['id']}"), u["id"]))
    return me_payload(db.q("SELECT * FROM users WHERE id = ?", (u["id"],), one=True))


@app.post("/api/delete")
async def api_delete(request: Request):
    d = await body(request)
    u, _ = current(request)
    check_password_or_lock(u, d.get("password"))
    for t in ("sessions", "resets"):
        db.q(f"DELETE FROM {t} WHERE user_id = ?", (u["id"],))
    db.q("DELETE FROM users WHERE id = ?", (u["id"],))
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r


# ---------------------------------------------------------------- forgot password (email code)
GENERIC = "If that account has an email address saved, a 6-digit code is on its way. It works for 15 minutes."


@app.post("/api/forgot")
async def api_forgot(request: Request):
    d = await body(request)
    if not (mail.configured() and sec.can_encrypt()):
        raise HTTPException(503, "Email reset isn't available on this site yet.")
    username = str(d.get("username", "")).strip().lower()[:40]
    limit(f"forgot:{username}", 5, 3600)
    u = user_by_name(username)
    if u and u["email_enc"] and not u["disabled"]:
        prev = db.q("SELECT sent_at FROM resets WHERE user_id = ?", (u["id"],), one=True)
        if not prev or now() - prev["sent_at"] >= 60:
            code = sec.new_code()
            db.q("DELETE FROM resets WHERE user_id = ?", (u["id"],))
            db.q("INSERT INTO resets (user_id, code_hash, expires_at, tries, sent_at) VALUES (?, ?, ?, 0, ?)",
                 (u["id"], sec.code_hash(code, u["id"]), now() + 15 * 60, now()))
            try:
                mail.send_reset_code(sec.decrypt(u["email_enc"], f"email:{u['id']}"), u["username"], code, site_url(request))
            except Exception:  # noqa: BLE001
                raise HTTPException(502, "The email couldn't be sent right now. Please try again later.")
    return {"message": GENERIC}                               # same answer for every username (no account probing)


@app.post("/api/reset")
async def api_reset(request: Request):
    d = await body(request)
    u = user_by_name(d.get("username", ""))
    r = db.q("SELECT * FROM resets WHERE user_id = ?", (u["id"],), one=True) if u else None
    bad = HTTPException(400, "That code is wrong or has expired. Ask for a new one.")
    if not r or r["expires_at"] < now() or r["tries"] >= 5:
        raise bad
    if sec.code_hash(str(d.get("code", "")).strip(), u["id"]) != r["code_hash"]:
        db.q("UPDATE resets SET tries = tries + 1 WHERE user_id = ?", (u["id"],))
        raise bad
    p = sec.pw_problem(d.get("new"), u["username"])
    if p:
        raise HTTPException(400, p)
    db.q("DELETE FROM resets WHERE user_id = ?", (u["id"],))     # single use
    db.q("UPDATE users SET pw_hash = ?, failed = 0, locked_until = 0 WHERE id = ?", (sec.hash_pw(d["new"]), u["id"]))
    db.q("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
    return start_session(request, u["id"], me_payload(db.q("SELECT * FROM users WHERE id = ?", (u["id"],), one=True)))


# ---------------------------------------------------------------- download (records the version for the reminder)
@app.get("/api/download")
def api_download(request: Request):
    u, _ = current(request, need=False)
    if not u:
        return RedirectResponse("/signin?next=download", status_code=303)
    rel = releases()
    v = rel["releases"][0]["version"]
    if not rel["repo"]:
        raise HTTPException(503, "The download isn't published yet.")
    db.q("UPDATE users SET last_version = ?, last_download_at = ? WHERE id = ?", (v, now(), u["id"]))
    db.q("INSERT INTO version_downloads (version, n) VALUES (?, 1) ON CONFLICT (version) DO UPDATE SET n = version_downloads.n + 1", (v,))
    return RedirectResponse(f"https://github.com/{rel['repo']}/releases/download/v{v}/AnKar-Video-Editor-{v}.zip", status_code=303)


# ---------------------------------------------------------------- admin (you only: ADMIN_USERNAME + authenticator code)
def admin_user(request: Request, unlocked: bool = True):
    u, s = current(request)
    if not is_admin(u):
        raise HTTPException(403, "Not allowed.")
    if unlocked and s["admin_until"] < now():
        raise HTTPException(403, "Enter your authenticator code first.")
    return u, s


@app.get("/api/admin/status")
def api_admin_status(request: Request):
    u, s = admin_user(request, unlocked=False)
    return {"totp": bool(u["totp_enc"]), "unlocked": s["admin_until"] > now(), "can_encrypt": sec.can_encrypt()}


@app.post("/api/admin/totp/setup")
async def api_admin_totp_setup(request: Request):
    """First time only: make the authenticator secret (shown once, as a QR code + key)."""
    d = await body(request)
    u, _ = admin_user(request, unlocked=False)
    if u["totp_enc"]:
        raise HTTPException(409, "The authenticator is already set up.")
    check_password_or_lock(u, d.get("password"))
    if not sec.can_encrypt():
        raise HTTPException(503, "Set DATA_KEY in Vercel first.")
    secret = sec.totp_secret()
    db.q("UPDATE users SET totp_pending_enc = ? WHERE id = ?", (sec.encrypt(secret, f"totp:{u['id']}"), u["id"]))
    uri = sec.totp_uri(secret, u["username"])
    qr = None
    try:
        import segno
        qr = segno.make(uri, error="m").svg_data_uri(scale=6, dark="#111111", light="#ffffff")
    except ImportError:
        pass
    return {"secret": secret, "uri": uri, "qr": qr}


@app.post("/api/admin/totp/verify")
async def api_admin_totp_verify(request: Request):
    d = await body(request)
    u, s = admin_user(request, unlocked=False)
    limit(f"totp:{u['id']}", 10, 900)
    pending = not u["totp_enc"]
    blob = u["totp_pending_enc"] if pending else u["totp_enc"]
    if not blob:
        raise HTTPException(400, "Set up the authenticator first.")
    step = sec.totp_check(sec.decrypt(blob, f"totp:{u['id']}"), d.get("code"), u["totp_last_step"])
    if step is None:
        raise HTTPException(401, "That code is wrong. Use the current 6-digit code from your authenticator app.")
    if pending:
        db.q("UPDATE users SET totp_enc = totp_pending_enc, totp_pending_enc = NULL WHERE id = ?", (u["id"],))
    db.q("UPDATE users SET totp_last_step = ? WHERE id = ?", (step, u["id"]))
    db.q("UPDATE sessions SET admin_until = ? WHERE token_hash = ?", (now() + ADMIN_S, s["token_hash"]))
    return {"ok": True}


@app.get("/api/admin/stats")
def api_admin_stats(request: Request):
    """Counts + an anonymous list. Never usernames' passwords (only hashes exist), never emails."""
    admin_user(request)
    t = now()
    count = lambda sql, a=(): db.q(sql, a, one=True)["n"]  # noqa: E731
    users = db.q("SELECT id, created_at, last_version, last_download_at, disabled FROM users ORDER BY id")
    latest = releases()["releases"][0]["version"]
    by_latest = {}
    for x in users:
        k = x["last_version"] or "never downloaded"
        by_latest[k] = by_latest.get(k, 0) + 1
    return {
        "users": len(users),
        "new_7d": sum(1 for x in users if t - x["created_at"] < 7 * 86400),
        "new_30d": sum(1 for x in users if t - x["created_at"] < 30 * 86400),
        "with_email": count("SELECT COUNT(*) AS n FROM users WHERE email_enc IS NOT NULL"),
        "active_sessions": count("SELECT COUNT(*) AS n FROM sessions WHERE expires_at > ?", (t,)),
        "latest_version": latest,
        "up_to_date": by_latest.get(latest, 0),
        "users_by_latest_download": dict(sorted(by_latest.items(), key=lambda kv: vkey(kv[0]), reverse=True)),
        "downloads_by_version": {r["version"]: r["n"] for r in sorted(db.q("SELECT version, n FROM version_downloads"),
                                                                     key=lambda r: vkey(r["version"]), reverse=True)},
        "list": [{"user": x["id"], "joined": time.strftime("%Y-%m", time.gmtime(x["created_at"])),
                  "last_download": f"{x['last_version']} · {time.strftime('%Y-%m-%d', time.gmtime(x['last_download_at']))}"
                  if x["last_version"] else "—", "disabled": bool(x["disabled"])} for x in users],
    }


@app.post("/api/admin/user")
async def api_admin_user(request: Request):
    d = await body(request)
    me, _ = admin_user(request)
    try:
        uid = int(d.get("user"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Give a user number.")
    if uid == me["id"]:
        raise HTTPException(400, "That's your own account.")
    act = d.get("action")
    if act in ("disable", "enable"):
        db.q("UPDATE users SET disabled = ? WHERE id = ?", (1 if act == "disable" else 0, uid))
        if act == "disable":
            db.q("DELETE FROM sessions WHERE user_id = ?", (uid,))
    elif act == "delete":
        for t in ("sessions", "resets"):
            db.q(f"DELETE FROM {t} WHERE user_id = ?", (uid,))
        db.q("DELETE FROM users WHERE id = ?", (uid,))
    else:
        raise HTTPException(400, "Unknown action.")
    return {"ok": True}
