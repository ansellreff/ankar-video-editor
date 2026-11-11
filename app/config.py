"""Local app settings + secrets.

Secrets (API keys) live ONLY in the encrypted key store (app/keystore.py: config/keys.enc + config/master.key, both
git-ignored) or the ELEVENLABS_API_KEY / ANTHROPIC_API_KEY environment variables. They are changed only on the
password-protected API Keys page (/keys).
They are never written to project files, exports, logs or the browser (the UI only ever sees a masked value).
"""
from __future__ import annotations

import json
import os

from .paths import ROOT

CONFIG = ROOT / "config"
SECRETS = CONFIG / "secrets.json"
SETTINGS = CONFIG / "settings.json"
TTS_DEFAULTS = {"engine": "local", "fallback": True, "el_model": "eleven_multilingual_v2",
                "el_clone_denoise": False,           # ElevenLabs remove_background_noise when making a clone
                # TTS output: Opus 48 kHz / 192 kbps — higher fidelity than mp3_44100_128 at the same credits, allowed on
                # Starter (voice-match test 2026-11-06: equal-or-better similarity)
                "el_format": "opus_48000_192",
                # ElevenLabs voice settings. auto = derived from the narration tone; otherwise these values are sent as is.
                "el_voice": {"auto": True, "stability": 0.55, "similarity": 0.85, "style": 0.0, "speaker_boost": True}}


def clean_el_voice(v: dict) -> dict:
    d = {**TTS_DEFAULTS["el_voice"], **(v or {})}
    f = lambda x: round(min(1.0, max(0.0, float(x))), 2)  # noqa: E731
    return {"auto": bool(d["auto"]), "stability": f(d["stability"]), "similarity": f(d["similarity"]),
            "style": f(d["style"]), "speaker_boost": bool(d["speaker_boost"])}


def _read(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(p, data):
    CONFIG.mkdir(exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def get_secret(name: str) -> str | None:
    """An API key: environment variable first, else the encrypted key store (app/keystore.py)."""
    from . import keystore
    return keystore.get(name)


def set_secret(name: str, value: str | None):
    """Internal only (tests / migration). The UI changes keys through the password-protected API Keys page."""
    from . import keystore
    if value:
        keystore.set_key(name, value)
    else:
        keystore.remove(name)


def masked(v: str | None) -> str | None:
    if not v:
        return None
    return f"{v[:3]}…{v[-4:]}" if len(v) > 10 else "••••"


def tts_settings() -> dict:
    s = {**TTS_DEFAULTS, **_read(SETTINGS).get("tts", {})}
    s["el_voice"] = clean_el_voice(s.get("el_voice"))
    return s


def set_tts_settings(patch: dict):
    data = _read(SETTINGS)
    allowed = {k: v for k, v in patch.items() if k in TTS_DEFAULTS}
    if "engine" in allowed and allowed["engine"] not in ("local", "elevenlabs"):
        raise ValueError("engine must be local or elevenlabs")
    if "el_voice" in allowed:
        allowed["el_voice"] = clean_el_voice({**data.get("tts", {}).get("el_voice", {}), **allowed["el_voice"]})
    data["tts"] = {**TTS_DEFAULTS, **data.get("tts", {}), **allowed}
    _write(SETTINGS, data)
    return data["tts"]


def public_tts_config() -> dict:
    """What the UI may see: settings + whether a key exists (masked), never the key itself."""
    key = get_secret("elevenlabs_api_key")
    return {**tts_settings(), "key_set": bool(key), "key_masked": masked(key),
            "key_source": "environment" if os.environ.get("ELEVENLABS_API_KEY") else ("encrypted key store" if key else None)}
