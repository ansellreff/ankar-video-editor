"""AI narration end-to-end through the running server (localhost:8765). Cleans up after itself."""
import json
import shutil
import time
import urllib.request
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
BASE = __import__("os").environ.get("VLOG_TEST_URL", "http://localhost:8766")


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=600).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")


sample_src = ROOT / "cache" / "work" / "tts_spike" / "default.wav"
sample = ROOT / "assets" / "audio" / "voiceover" / "e2e_voice_sample.wav"
shutil.copy(sample_src, sample)
voice_dir = ROOT / "assets" / "voices" / "E2E Voice"
added = []
try:
    print("create voice:", call("/api/voices/create", {"name": "E2E Voice", "consent": True})["name"])
    aid = None
    for _ in range(40):                                     # wait for the library to pick up the sample file
        st = call("/api/state")
        aid = next((a["id"] for a in st["assets"] if a["name"] == "e2e_voice_sample.wav" and (a.get("meta") or {}).get("dur")), None)
        if aid:
            break
        time.sleep(0.5)
    r = call("/api/voices/sample", {"asset": aid, "voice": "E2E Voice", "mood": "cheerful", "t0": 0, "t1": 4.8, "clean": True})
    print("sample:", r["file"])
    st = call("/api/op", {"op": "add_tts", "args": {"start": 2.0, "dur": 3.4, "voice": "E2E Voice", "tone": "cheerful",
                                                    "text": "Welcome to E-DA Theme Park, the happiest place in Kaohsiung!"}})
    cid = st["result"][0]
    added.append(cid)
    track = next(c for c in st["project"]["clips"] if c["id"] == cid)["track"]
    print("narration clip:", cid, "on", track)
    t0 = time.time()
    print("queued:", call("/api/tts/generate", {"ids": [cid]})["queued"])
    job = None
    while time.time() - t0 < 600:
        job = call("/api/tts/status")["jobs"].get(cid)
        if job and job["state"] in ("done", "error"):
            break
        time.sleep(2)
    print(f"job: {job}  ({time.time() - t0:.0f}s)")
    st = call("/api/state")
    c = next(c for c in st["project"]["clips"] if c["id"] == cid)
    f = ROOT / c["tts"]["file"]
    sr, x = wavfile.read(f)
    rms = float(np.sqrt(np.mean((x.astype(np.float32) / 32768) ** 2)))
    print(f"generated {f.name}: {len(x) / sr:.3f}s (clip {c['dur']:.3f}s, fitted={c['tts'].get('fitted')}), rms={rms:.3f}, stale={c['tts']['stale']}, asset={c.get('asset')}")
    assert c["tts"]["stale"] is False and c.get("asset") and rms > 0.01
    assert abs(len(x) / sr - c["dur"]) < 0.05, "fit-to-duration failed"
    # change the tone → stale again
    st = call("/api/op", {"op": "update", "args": {"ids": [cid], "patch": {"tts": {"tone": "serious"}}}})
    assert next(k for k in st["project"]["clips"] if k["id"] == cid)["tts"]["stale"] is True
    print("tone change marks the clip stale: OK")
    print("ALL OK")
finally:
    for cid in added:
        try:
            call("/api/op", {"op": "delete", "args": {"ids": [cid]}, "label": "Remove test narration"})
        except Exception as e:  # noqa: BLE001
            print("cleanup:", e)
    shutil.rmtree(voice_dir, ignore_errors=True)
    sample.unlink(missing_ok=True)
