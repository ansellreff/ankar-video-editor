"""Key safety (API Keys page flow) + ElevenLabs fallback-to-local, on the TEST server, with a FAKE key.

It never touches a real key: the safety part uses a custom key name; the fallback part runs only when no real
ElevenLabs key is saved (keys can't be read back, so a real one couldn't be restored)."""
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("VLOG_TEST_URL", "http://localhost:8766")
PASSWORD = os.environ.get("VLOG_KEYS_PASSWORD", "")          # the key-page password (default one for tests)
FAKE = "sk_fake_" + "0123456789abcdef" * 3
HDR = {"Content-Type": "application/json", "X-Vlog-Keys": "1"}


def call(path, body=None, ok=True, headers=HDR):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=600).read())
    except urllib.error.HTTPError as e:
        if ok:
            raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")
        return {"_status": e.code, "_body": e.read().decode()}


assert PASSWORD, "set VLOG_KEYS_PASSWORD to the key-page password"
# --- safety: password, write-only, encrypted, not in /api/state, not in project files
assert call("/api/keys/set", {"name": "test_fake_key", "value": FAKE, "password": "wrong"}, ok=False)["_status"] == 401
pub = call("/api/keys/set", {"name": "test_fake_key", "value": FAKE, "password": PASSWORD})
assert FAKE not in json.dumps(pub) and any(k["name"] == "test_fake_key" for k in pub["custom"])
assert FAKE not in json.dumps(call("/api/state"))
assert not (ROOT / "config" / "keys.enc").read_text().count(FAKE), "key stored in plain text!"
assert not any(FAKE in p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "projects").rglob("*.json"))
blocked = call("/api/keys/set", {"name": "x_key", "value": FAKE, "password": PASSWORD}, ok=False,
               headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
assert blocked["_status"] == 403, blocked
call("/api/keys/remove", {"name": "test_fake_key", "password": PASSWORD})
print("password needed, write-only, encrypted, other websites blocked: OK")

# --- fallback: only without a real ElevenLabs key
if any(s["name"] == "elevenlabs_api_key" and s["set"] for s in call("/api/keys")["services"]):
    print("a real ElevenLabs key is saved → fallback test skipped (it would have to replace your key)")
    raise SystemExit(0)
cid = None
before = call("/api/tts/config")
try:
    call("/api/keys/set", {"name": "elevenlabs_api_key", "value": FAKE, "password": PASSWORD})
    call("/api/tts/config", {"engine": "elevenlabs"})
    r = call("/api/op", {"op": "add_tts", "args": {"start": 1.0, "dur": 3.0, "tone": "calm", "text": "Testing the fallback to the local voice."}})
    cid = r["result"][0]
    call("/api/tts/generate", {"ids": [cid]})
    t0, job = time.time(), None
    while time.time() - t0 < 600:
        job = call("/api/tts/status")["jobs"].get(cid)
        if job and job["state"] in ("done", "error"):
            break
        time.sleep(2)
    assert job["state"] == "done" and job["engine"] == "local", "fallback to local did not happen"
    print("ElevenLabs rejected → fell back to the local engine: OK")
finally:
    if cid:
        call("/api/op", {"op": "delete", "args": {"ids": [cid]}, "label": "Remove test narration"})
    call("/api/keys/remove", {"name": "elevenlabs_api_key", "password": PASSWORD}, ok=False)
    call("/api/tts/config", {"engine": before["engine"], "fallback": before["fallback"]})
print("ALL OK")
