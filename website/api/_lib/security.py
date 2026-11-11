"""Passwords (scrypt), tokens, encryption of the optional email / admin authenticator secret, and TOTP (RFC 6238).

Secrets come only from Vercel's environment settings, never from the repo:
  DATA_KEY  32 random bytes as 64 hex characters — encrypts emails and the admin's authenticator secret."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
import time

N, R, P = 2**15, 8, 1
MIN_PW, MAX_PW = 10, 200
USERNAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,22})[a-z0-9]$")
RESERVED = {"admin", "administrator", "root", "ankar", "support", "help", "system", "security", "moderator", "owner",
            "staff", "api", "null", "undefined", "me", "you"}
COMMON = {"password", "password1", "password12", "password123", "1234567890", "0123456789", "qwertyuiop", "1q2w3e4r5t",
          "iloveyou12", "qwerty1234", "1qaz2wsx3edc", "abcdefghij", "passw0rd12", "letmein123", "welcome123",
          "admin12345", "football12", "baseball12", "monkey1234", "dragon1234", "sunshine12", "princess12",
          "qwertyuiop1", "asdfghjkl1", "zxcvbnm123", "1234567891", "9876543210", "abc1234567", "ankarvideo",
          "ankar12345", "videoeditor", "password!!"}


# ---------------------------------------------------------------- passwords
def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${N}${R}${P}${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


_DUMMY = None


def burn_time(pw: str):
    """Same cost as a real check when the username doesn't exist (no timing hint about which usernames exist)."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_pw("not-a-real-password-just-timing")
    check_pw(pw, _DUMMY)


def pw_problem(pw, username: str = "") -> str | None:
    if not isinstance(pw, str) or len(pw) < MIN_PW:
        return f"Use at least {MIN_PW} characters."
    if len(pw) > MAX_PW:
        return f"Use at most {MAX_PW} characters."
    low = pw.lower()
    if low in COMMON or len(set(low)) <= 2 or (username and username.lower() in low):
        return "That password is too easy to guess. Try a short sentence or a few random words."
    digits = "01234567890123456789"
    if low.isdigit() and (low in digits or low in digits[::-1]):
        return "A run of numbers is too easy to guess."
    return None


def username_problem(u) -> str | None:
    if not isinstance(u, str) or not USERNAME.match(u.lower()):
        return "Usernames are 3–24 letters, numbers, dots, dashes or underscores (start and end with a letter or number)."
    if u.lower() in RESERVED:
        return "That username is reserved. Please pick another."
    return None


# ---------------------------------------------------------------- tokens
def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


# ---------------------------------------------------------------- encryption (AES-256-GCM)
def _key() -> bytes | None:
    k = os.environ.get("DATA_KEY", "").strip()
    try:
        b = bytes.fromhex(k)
        return b if len(b) == 32 else None
    except ValueError:
        return None


def can_encrypt() -> bool:
    return _key() is not None


def encrypt(text: str, purpose: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    k = _key()
    if not k:
        raise RuntimeError("DATA_KEY is not set")
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(k).encrypt(nonce, text.encode(), purpose.encode())).decode()


def decrypt(blob: str, purpose: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(blob)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], purpose.encode()).decode()


def code_hash(code: str, user_id: int) -> str:
    """One-time codes: keyed hash (DATA_KEY) so a database copy alone can't be used to test codes offline."""
    return hmac.new(_key() or b"no-key", f"{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- email address
EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


def email_problem(e) -> str | None:
    if not isinstance(e, str) or len(e) > 254 or not EMAIL.match(e.strip()):
        return "That doesn't look like an email address."
    return None


def mask_email(e: str) -> str:
    name, _, dom = e.partition("@")
    return (name[0] + "•" * max(1, len(name) - 1)) + "@" + dom


# ---------------------------------------------------------------- TOTP (authenticator app), admin only
def totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def totp_check(secret: str, code: str, last_step: int, now: float | None = None) -> int | None:
    """The time step the code belongs to (±1 step = ±30 s), or None. Steps ≤ last_step are refused (no replay)."""
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        return None
    step = int((now or time.time()) // 30)
    for s in (step - 1, step, step + 1):
        if s > last_step and hmac.compare_digest(_hotp(secret, s), code):
            return s
    return None


def totp_uri(secret: str, label: str) -> str:
    from urllib.parse import quote
    return f"otpauth://totp/{quote('AnKar Video Editor:' + label)}?secret={secret}&issuer={quote('AnKar Video Editor')}&digits=6&period=30"
