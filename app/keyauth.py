"""Password for adding / changing / removing API keys.

There is NO built-in password: on a new install the API Keys page first asks the user to create one. Only a salted
scrypt hash is stored, in config/auth.json (git-ignored, stays on this PC). Wrong passwords are limited: 5 tries,
then the key page is locked for 5 minutes. Later: "forgot password" by email / OTP."""
from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from .paths import ROOT

AUTH = ROOT / "config" / "auth.json"
MAX_TRIES, LOCK_S = 5, 300
MIN_LEN, MAX_LEN = 10, 200
N = 2**15
_lock = threading.Lock()
_state = {"fails": 0, "locked_until": 0.0}
# the most common passwords (and their obvious variants are caught by the "all one character" / sequence checks)
COMMON = {"password", "password1", "password12", "password123", "1234567890", "0123456789", "qwertyuiop", "1q2w3e4r5t",
          "iloveyou12", "qwerty1234", "1qaz2wsx3edc", "abcdefghij", "passw0rd12", "letmein123", "welcome123",
          "admin12345", "football12", "baseball12", "monkey1234", "dragon1234", "sunshine12", "princess12",
          "qwertyuiop1", "asdfghjkl1", "zxcvbnm123", "1234567891", "9876543210", "11223344556", "abc1234567"}


def _record() -> dict | None:
    try:
        d = json.loads(AUTH.read_text(encoding="utf-8"))
        if d.get("salt") and d.get("hash"):
            return d
    except (OSError, ValueError):
        pass
    return None


def _hash(password: str, salt_hex: str, n: int = N) -> str:
    h = hashlib.scrypt(password.encode("utf-8"), salt=binascii.unhexlify(salt_hex), n=n, r=8, p=1,
                       maxmem=64 * 1024 * 1024, dklen=32)
    return binascii.hexlify(h).decode()


def status() -> dict:
    left = max(0, int(_state["locked_until"] - time.time()))
    return {"password": "set" if _record() else "unset", "locked_s": left,
            "tries_left": MAX_TRIES - _state["fails"] if not left else 0, "min_len": MIN_LEN}


class AuthError(Exception):
    pass


def check_strength(pw: str):
    """Raises ValueError with a plain-language reason."""
    if not isinstance(pw, str) or len(pw) < MIN_LEN:
        raise ValueError(f"Use at least {MIN_LEN} characters.")
    if len(pw) > MAX_LEN:
        raise ValueError(f"Use at most {MAX_LEN} characters.")
    low = pw.lower()
    if low in COMMON or len(set(low)) <= 2:
        raise ValueError("That password is too common or too simple. Try a short sentence or a few random words.")
    digits = "01234567890123456789"
    if low.isdigit() and (low in digits or low in digits[::-1]):
        raise ValueError("A run of numbers is too easy to guess.")


def verify(password: str):
    """Raises AuthError (wrong / locked / none yet). Constant-time comparison; a failure costs a scrypt run."""
    with _lock:
        now = time.time()
        if _state["locked_until"] > now:
            raise AuthError(f"Too many wrong passwords. Try again in {int(_state['locked_until'] - now) + 1} s.")
        rec = _record()
        if not rec:
            raise AuthError("Create your password first (top of the API Keys page).")
        ok = isinstance(password, str) and 0 < len(password) <= MAX_LEN and hmac.compare_digest(
            _hash(password, rec["salt"], int(rec.get("n", N))), rec["hash"])
        if ok:
            _state["fails"] = 0
            return
        _state["fails"] += 1
        if _state["fails"] >= MAX_TRIES:
            _state["fails"] = 0
            _state["locked_until"] = now + LOCK_S
            raise AuthError(f"Wrong password. The key page is locked for {LOCK_S // 60} minutes.")
        raise AuthError(f"Wrong password ({MAX_TRIES - _state['fails']} tries left).")


def set_password(new: str, current: str | None = None):
    """First password (none saved yet) or a change (needs the current one). Raises AuthError / ValueError."""
    if _record():
        verify(current or "")
    check_strength(new)
    salt = secrets.token_hex(16)
    AUTH.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUTH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"salt": salt, "hash": _hash(new, salt), "n": N, "alg": "scrypt",
                               "updated": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    os.replace(tmp, AUTH)
    with _lock:
        _state.update(fails=0, locked_until=0.0)
