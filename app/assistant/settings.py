"""AI Editor settings (config/settings.json → "assistant") and API prices.

The Anthropic API key lives ONLY in the encrypted key store (app/keystore.py, "anthropic_api_key") or the
ANTHROPIC_API_KEY environment variable — never in projects, chats, logs, exports or the browser (the UI only sees a
masked value). It is added / changed / removed only on the password-protected API Keys page (/keys)."""
from __future__ import annotations

import os

from .. import config

# $ per million tokens (Claude API, 2026-10; cache write = 1.25 × input for the 5-minute cache)
MODELS = {
    "claude-opus-5-5": {"name": "Claude Opus 5.5", "in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"name": "Claude Sonnet 5.5", "in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULTS = {"model": "claude-opus-5-5", "effort": "medium", "budget_usd": None, "max_tokens": 64000}


def get() -> dict:
    s = {**DEFAULTS, **(config._read(config.SETTINGS).get("assistant") or {})}
    if s["model"] not in MODELS:
        s["model"] = DEFAULTS["model"]
    if s["effort"] not in EFFORTS:
        s["effort"] = DEFAULTS["effort"]
    return s


def update(patch: dict) -> dict:
    data = config._read(config.SETTINGS)
    cur = {**DEFAULTS, **(data.get("assistant") or {})}
    for k, v in patch.items():
        if k == "model" and v in MODELS:
            cur["model"] = v
        elif k == "effort" and v in EFFORTS:
            cur["effort"] = v
        elif k == "budget_usd":
            cur["budget_usd"] = None if v in (None, "", 0) else max(0.0, float(v))
    data["assistant"] = cur
    config._write(config.SETTINGS, data)
    return get()


def api_key() -> str | None:
    return config.get_secret("anthropic_api_key")


def set_api_key(value: str | None):
    config.set_secret("anthropic_api_key", (value or "").strip() or None)


def public() -> dict:
    """What the browser may see: settings + key status (masked), never the key."""
    k = api_key()
    return {**get(), "models": {m: v["name"] for m, v in MODELS.items()}, "efforts": list(EFFORTS),
            "key_set": bool(k), "key_masked": config.masked(k),
            "key_source": "environment" if os.environ.get("ANTHROPIC_API_KEY") else ("encrypted key store" if k else None)}


def cost(usage: dict, model: str) -> float:
    """$ for one response's usage {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}."""
    p = MODELS.get(model) or MODELS[DEFAULTS["model"]]
    return round((usage.get("input_tokens", 0) * p["in"] + usage.get("output_tokens", 0) * p["out"]
                  + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
                  + usage.get("cache_read_input_tokens", 0) * p["cache_read"]) / 1e6, 6)
