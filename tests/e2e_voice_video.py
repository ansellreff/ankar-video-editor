"""Voice from Video end-to-end: make an MP4 (2 speakers + background music) → upload → extract voices (music removed)
→ learn Person 2 → narrate → MP3 → place on the timeline. Uses the running server; cleans up after itself."""
import json
import shutil
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from scipy.io import wavfile

from app.colors import rgb_to_yuv709, x264_options
from app.tts.manager import to_mono48

ROOT = Path(__file__).resolve().parent.parent
TEST_PROJECTS = __import__("pathlib").Path(__import__("os").environ.get("VLOG_PROJECTS_DIR") or ROOT / "cache" / "test_projects")  # the TEST server (:8766) keeps its projects (and their exports/) here
BASE = __import__("os").environ.get("VLOG_TEST_URL", "http://localhost:8766")
W = ROOT / "cache/work/vtest"


def call(path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": ctype}, method="GET" if data is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")


# ---- build the test video: speech turns + music bed (-12 dB under the voices) + a simple picture
parts, t, truth = [np.zeros(24000, np.float32)], 0.5, []
for i in range(6):
    sr, x = wavfile.read(W / f"p{i}.wav")
    y = to_mono48(x, sr)
    truth.append((t, t + len(y) / 48000, "male" if i % 2 == 0 else "female"))
    parts += [y, np.zeros(int(0.5 * 48000), np.float32)]
    t += len(y) / 48000 + 0.5
speech = np.concatenate(parts)
n = len(speech)
tt = np.arange(n) / 48000
music = np.zeros(n, np.float32)
for k, f0 in enumerate([220, 277.2, 329.6, 246.9]):                      # chord progression + soft beat
    seg = (tt // 2 % 4) == k
    for h in (1, 1.5, 2):
        music += seg * 0.06 * np.sin(2 * np.pi * f0 * h * tt) / h
beat = (np.sin(2 * np.pi * 2 * tt) > 0.97) * np.random.default_rng(1).standard_normal(n) * 0.08
mix = np.stack([speech * 0.8 + music + beat] * 2).astype(np.float32)
mp4 = W / "night_market_test.mp4"
out = av.open(str(mp4), "w")
vs = out.add_stream("libx264", rate=Fraction(30), options=x264_options(crf="30", preset="ultrafast"))
vs.width, vs.height, vs.pix_fmt = 360, 640, "yuv420p"
as_ = out.add_stream("aac", rate=48000, layout="stereo")
for i in range(int(n / 48000 * 30)):
    img = np.zeros((640, 360, 3), np.uint8)
    img[:, :, 0] = 40 + (i * 3) % 120
    img[:, :, 2] = 90
    f = rgb_to_yuv709(img); f.pts = i
    for p in vs.encode(f):
        out.mux(p)
for p in vs.encode():
    out.mux(p)
for s in range(0, n, 1024):
    af = av.AudioFrame.from_ndarray(np.ascontiguousarray(mix[:, s:s + 1024]), format="fltp", layout="stereo")
    af.sample_rate, af.pts = 48000, s
    for p in as_.encode(af):
        out.mux(p)
for p in as_.encode():
    out.mux(p)
out.close()
print(f"test video: {n / 48000:.1f}s, 2 speakers + music, {mp4.stat().st_size // 1024} KB")

uploaded, voice_dir, placed = None, None, []
try:
    # 1. upload
    r = call("/api/upload?name=night_market_test.mp4", raw=mp4.read_bytes(), ctype="video/mp4")
    uploaded = ROOT / r["path"]
    print("1 upload →", r["path"])
    # 2. extract voices (music removed)
    t0 = time.time()
    job = call("/api/voices/speakers", {"asset": r["asset"], "n": 2, "isolate": True})
    print(f"2 extract: {len(job['speakers'])} people in {time.time() - t0:.0f}s (music removed: {job['isolated']})")
    ok_turns = 0
    for s, e, who in truth:
        ov = {}
        for ts, te, k in job["turns"]:
            ov[k] = ov.get(k, 0) + max(0.0, min(e, te) - max(s, ts))
        best = max(ov, key=ov.get) if ov else None
        print(f"   {s:5.1f}-{e:5.1f} {who:6s} → {best}")
        ok_turns += best == ("S1" if who == truth[0][2] else "S2") or best == ("S2" if who == truth[0][2] else "S1")
    labels = {}
    for s, e, who in truth:
        best = max({k: sum(max(0, min(e, te) - max(s, ts)) for ts, te, kk in job["turns"] if kk == k) for k in {t[2] for t in job["turns"]}}.items(), key=lambda kv: kv[1])[0]
        labels.setdefault(who, set()).add(best)
    sep = all(len(v) == 1 for v in labels.values()) and labels["male"] != labels["female"]
    print("   people separated correctly:", sep, {k: sorted(v) for k, v in labels.items()})
    female = next(iter(labels["female"]))
    # 3. learn
    r3 = call("/api/voices/from_speaker", {"job": job["id"], "speaker": female, "voice": "E2E Video Voice", "consent": True, "clean": False})
    voice_dir = ROOT / "library/voices/E2E Video Voice"
    sr, smp = wavfile.read(ROOT / r3["file"])
    print(f"3 learned from {female}: {len(smp) / sr:.1f}s of clean speech → {r3['file']}")
    # 4. narrate → MP3 → timeline
    q = call("/api/tts/quick", {"text": "Welcome to Taiwan! This is my cloned voice narrating the vlog.", "voice": "E2E Video Voice", "tone": "cheerful"})
    t0, j = time.time(), None
    while time.time() - t0 < 600:
        j = call("/api/tts/status")["jobs"].get(q["id"])
        if j and j["state"] in ("done", "error"):
            break
        time.sleep(2)
    print(f"4 narrate: {j['state']} in {time.time() - t0:.0f}s, {j.get('dur')}s, engine {j.get('engine')}")
    time.sleep(1.5)
    mp3 = sorted((TEST_PROJECTS).rglob("voice_test_*.mp3"), key=lambda p: p.stat().st_mtime)[-1]
    print("   MP3:", mp3.relative_to(ROOT), f"{mp3.stat().st_size // 1024} KB")
    st = call("/api/tts/place", {"file": j["file"], "start": 2.0, "text": "Welcome to Taiwan!"})
    placed = [c["id"] for c in st["project"]["clips"] if (c.get("label") or "").startswith("🗣 Welcome")]
    tr = next(c["track"] for c in st["project"]["clips"] if c["id"] == placed[0])
    print("   placed on the timeline:", placed, "track", tr)
    print("ALL OK" if sep else "SEPARATION NEEDS WORK")
finally:
    if placed:
        call("/api/op", {"op": "delete", "args": {"ids": placed}, "label": "Remove test narration"})
    if voice_dir:
        shutil.rmtree(voice_dir, ignore_errors=True)
    if uploaded:
        uploaded.unlink(missing_ok=True)
    for f in list((TEST_PROJECTS).rglob("voice_test_*.mp3")) + list((ROOT / "library/generated/narration").glob("tts_*.wav")):
        f.unlink()
