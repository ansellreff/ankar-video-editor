"""The user's own API keys (Claude / Anthropic, ElevenLabs, any other) — encrypted at rest, never sent to the browser.

Storage (all git-ignored):
  config/keys.enc    AES-256-GCM encrypted JSON {name: {value, label, updated}}
  config/master.key  the 32-byte encryption key; on Windows it is itself wrapped with DPAPI (only this Windows user
                     on this PC can unwrap it), so a copied config/ folder alone doesn't reveal the keys.
Environment variables ELEVENLABS_API_KEY / ANTHROPIC_API_KEY still win (e.g. on a server).
A plain config/secrets.json from older versions is imported once, then deleted.
Adding / changing / removing a key needs the password (app/keyauth.py) — enforced in the server endpoints."""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time

from .paths import ROOT

CONFIG = ROOT / "config"
STORE = CONFIG / "keys.enc"
MASTER = CONFIG / "master.key"
LEGACY = CONFIG / "secrets.json"
ENV = {"elevenlabs_api_key": "ELEVENLABS_API_KEY", "anthropic_api_key": "ANTHROPIC_API_KEY"}
SERVICES = [
    {"name": "anthropic_api_key", "label": "Claude (Anthropic)", "used_for": "AI Editor",
     "hint": "console.anthropic.com ▸ API keys · starts with sk-ant-", "prefix": "sk-ant-"},
    {"name": "elevenlabs_api_key", "label": "ElevenLabs", "used_for": "AI Voice (narration, voice cloning, sound effects)",
     "hint": "elevenlabs.io ▸ Developers ▸ API keys", "prefix": ""},
]
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
# key-looking strings (used to hide keys in anything shown or logged, and by scripts/check_secrets.py)
KEY_PATTERNS = [re.compile(p) for p in (
    r"sk-ant-[A-Za-z0-9_\-]{20,}",             # Anthropic
    r"\bsk_[A-Za-z0-9]{32,}\b",                # ElevenLabs (new style)
    r"\bsk-[A-Za-z0-9_\-]{32,}\b",             # other providers using sk-…
    r"\bAIza[0-9A-Za-z_\-]{35}\b",             # Google
    r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",         # GitHub tokens
)]
_lock = threading.RLock()
_cache: dict | None = None


# ---------------------------------------------------------------- master key (DPAPI-wrapped on Windows)
def _dpapi(data: bytes, protect: bool) -> bytes | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = BLOB()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))   # 0x1 = no UI
        if not ok:
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:  # noqa: BLE001 — DPAPI is an extra layer; without it the file key is used as is
        return None


def _master() -> bytes:
    if MASTER.exists():
        raw = MASTER.read_bytes()
        if raw.startswith(b"DPAPI:"):
            k = _dpapi(base64.b64decode(raw[6:]), protect=False)
            if not k:
                raise RuntimeError("The key store belongs to another Windows user or PC (DPAPI). Re-enter the API keys.")
            return k
        return base64.b64decode(raw[5:]) if raw.startswith(b"PLAIN:") else raw
    CONFIG.mkdir(exist_ok=True)
    k = secrets.token_bytes(32)
    wrapped = _dpapi(k, protect=True)
    MASTER.write_bytes(b"DPAPI:" + base64.b64encode(wrapped) if wrapped else b"PLAIN:" + base64.b64encode(k))
    return k


# ---------------------------------------------------------------- encrypted store
def _load() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        data = {}
        if STORE.exists():
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            j = json.loads(STORE.read_text(encoding="utf-8"))
            plain = AESGCM(_master()).decrypt(base64.b64decode(j["nonce"]), base64.b64decode(j["data"]), b"vlog-keys-v1")
            data = json.loads(plain.decode("utf-8"))
        if LEGACY.exists():                                   # one-time import of the old plain-text file
            try:
                old = json.loads(LEGACY.read_text(encoding="utf-8"))
                for k, v in old.items():
                    if isinstance(v, str) and v.strip() and k not in data:
                        data[k] = {"value": v.strip(), "label": "", "updated": time.strftime("%Y-%m-%d %H:%M")}
                _cache = data
                _save(data)
                LEGACY.unlink()
            except (OSError, ValueError):
                pass
        _cache = data
        return data


def _save(data: dict):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    with _lock:
        CONFIG.mkdir(exist_ok=True)
        nonce = secrets.token_bytes(12)
        ct = AESGCM(_master()).encrypt(nonce, json.dumps(data).encode("utf-8"), b"vlog-keys-v1")
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"v": 1, "alg": "AES-256-GCM", "nonce": base64.b64encode(nonce).decode(),
                                   "data": base64.b64encode(ct).decode()}), encoding="utf-8")
        os.replace(tmp, STORE)


def get(name: str) -> str | None:
    env = ENV.get(name)
    if env and os.environ.get(env, "").strip():
        return os.environ[env].strip()
    e = _load().get(name)
    return e["value"] if e else None


def set_key(name: str, value: str, label: str = ""):
    """Internal: callers must have checked the password (server endpoints do)."""
    if not NAME_RE.match(name or ""):
        raise ValueError("key names: lowercase letters, digits and _ (3–48 characters)")
    value = (value or "").strip()
    if len(value) < 8 or any(c.isspace() for c in value):
        raise ValueError("that doesn't look like an API key")
    svc = next((s for s in SERVICES if s["name"] == name), None)
    if svc and svc["prefix"] and not value.startswith(svc["prefix"]):
        raise ValueError(f"a {svc['label']} key starts with {svc['prefix']}")
    with _lock:
        data = dict(_load())
        data[name] = {"value": value, "label": label.strip()[:60], "updated": time.strftime("%Y-%m-%d %H:%M")}
        _save(data)
        globals()["_cache"] = data


def remove(name: str) -> bool:
    with _lock:
        data = dict(_load())
        if name not in data:
            return False
        data.pop(name)
        _save(data)
        globals()["_cache"] = data
        return True


def masked(v: str | None) -> str | None:
    if not v:
        return None
    return f"••••{v[-4:]}" if len(v) > 12 else "••••"


def public_list() -> dict:
    """What the browser may see: names, labels, masked endings, where it comes from — never a value."""
    data = _load()
    out = []
    for s in SERVICES:
        env = ENV.get(s["name"])
        src = "environment" if env and os.environ.get(env, "").strip() else ("saved" if s["name"] in data else None)
        out.append({**{k: s[k] for k in ("name", "label", "used_for", "hint")}, "set": bool(src), "source": src,
                    "masked": masked(get(s["name"])), "updated": (data.get(s["name"]) or {}).get("updated")})
    custom = [{"name": k, "label": v.get("label") or k, "used_for": "your own key", "set": True, "source": "saved",
               "masked": masked(v["value"]), "updated": v.get("updated")}
              for k, v in data.items() if k not in {s["name"] for s in SERVICES}]
    return {"services": out, "custom": custom, "encryption": "AES-256-GCM" + (" + Windows DPAPI" if MASTER.exists() and MASTER.read_bytes().startswith(b"DPAPI:") else "")}


def redact(text: str) -> str:
    """Hide any stored key (and anything that looks like a key) in text shown to the user, sent to Claude or logged."""
    if not text or not isinstance(text, str):
        return text
    try:
        vals = [e["value"] for e in _load().values() if len(e.get("value", "")) >= 8]
    except Exception:  # noqa: BLE001
        vals = []
    vals += [os.environ[e] for e in ENV.values() if len(os.environ.get(e, "")) >= 8]
    for v in vals:
        if v in text:
            text = text.replace(v, "[hidden key]")
    for p in KEY_PATTERNS:
        text = p.sub("[hidden key]", text)
    return text


def reset_cache():
    global _cache
    with _lock:
        _cache = None
