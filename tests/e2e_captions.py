"""Auto Captions end-to-end on the TEST server (:8766): build a clip (3 English lines, 1 Mandarin line, a mumbled
stretch) → upload → place on the timeline → /api/captions/auto → check text, ( ) translation, word timing, review flags
→ restyle → edit text → rechunk. Speech made with Windows' built-in voices (cache/work_test/cap/*.wav)."""
import json
import os
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
BASE = os.environ.get("VLOG_TEST_URL", "http://localhost:8766")
W = ROOT / "cache/work_test/cap"
ok = True


def call(path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": ctype}, method="GET" if data is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=900).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


# ---- build the clip: l0, l1, zh, mumble (reversed speech), l2 with pauses
parts, t, truth = [np.zeros(24000, np.float32)], 0.5, {}
for name in ("l0", "l1", "zh", "mumble", "l2"):
    if name == "mumble":
        sr, x = wavfile.read(W / "l1.wav")
        y = to_mono48(x, sr)[::-1].copy() * 0.6                    # speech-like sound, no words
    else:
        sr, x = wavfile.read(W / f"{name}.wav")
        y = to_mono48(x, sr)
    truth[name] = (t, t + len(y) / 48000)
    parts += [y, np.zeros(int(0.8 * 48000), np.float32)]
    t += len(y) / 48000 + 0.8
speech = np.concatenate(parts)
n = len(speech)
mix = np.stack([speech * 0.9] * 2).astype(np.float32)
mp4 = W / "_test_captions.mp4"
out = av.open(str(mp4), "w")
vs = out.add_stream("libx264", rate=Fraction(30), options=x264_options(crf="32", preset="ultrafast"))
vs.width, vs.height, vs.pix_fmt = 360, 640, "yuv420p"
as_ = out.add_stream("aac", rate=48000, layout="stereo")
for i in range(int(n / 48000 * 30)):
    img = np.full((640, 360, 3), 70, np.uint8)
    img[:, :, 2] = 120
    f = rgb_to_yuv709(img); f.pts = i
    for p in vs.encode(f):
        out.mux(p)
for p in vs.encode():
    out.mux(p)
for k in range(0, n, 1024):
    fr = av.AudioFrame.from_ndarray(np.ascontiguousarray(mix[:, k:k + 1024]), format="fltp", layout="stereo")
    fr.sample_rate, fr.pts = 48000, k
    for p in as_.encode(fr):
        out.mux(p)
for p in as_.encode():
    out.mux(p)
out.close()
print(f"test clip {n / 48000:.1f}s, truth {json.dumps({k: [round(a, 2), round(b, 2)] for k, (a, b) in truth.items()})}")

up = call("/api/upload?name=_test_captions.mp4", raw=mp4.read_bytes(), ctype="application/octet-stream")
aid = up["asset"]
for _ in range(60):
    a = next((a for a in call("/api/state")["assets"] if a["id"] == aid), None)
    if a and (a.get("meta") or {}).get("dur"):
        break
    time.sleep(0.5)
try:
    call("/api/projects/new", {"name": "captions test", "format": "9:16"})
    r = call("/api/op", {"op": "add_media", "args": {"asset": aid, "track": "V1", "start": 1.0}})
    vid = r["result"][0]
    t0 = time.time()
    res = call("/api/captions/auto", {"scope": "clip", "ids": [vid], "template": "karaoke_line", "replace": True})
    print(f"auto captions: {res['captions']} captions, {res['review']} to review, {time.time() - t0:.1f}s")
    p = res["project"]
    caps = sorted([c for c in p["clips"] if c["type"] == "text" and c["text"].get("caption")], key=lambda c: c["start"])
    for c in caps:
        ws = c["text"]["caption"]["words"]
        print(f"  {c['start']:6.2f}-{c['start'] + c['dur']:5.2f} [{c['meta'].get('lang')}] {c['text']['content']!r}"
              f"{'  REVIEW: ' + '; '.join(c['meta']['review']) if c['meta'].get('review') else ''}"
              f"  conf={[round(w.get('conf', 1), 2) for w in ws]}")
    text = " ".join(c["text"]["content"] for c in caps).lower()
    check("English transcribed", all(k in text for k in ("theme park", "kaohsiung", "roller coaster", "night market")), "")
    zh = [c for c in caps if c["meta"].get("lang") == "zh"]
    check("Mandarin translated in ( )", bool(zh) and zh[0]["text"]["content"].startswith("(") and caps and any(c["text"]["content"].endswith(")") for c in zh),
          zh[0]["text"]["content"] if zh else "none")
    check("Mandarin original kept", bool(zh) and bool(zh[0]["meta"].get("original")), zh[0]["meta"].get("original") if zh else "")
    check("lines are short (≤5 words)", all(len(c["text"]["caption"]["words"]) <= 5 for c in caps))
    # word timing: 'roller' should start near the start of line l1 (clip starts at 1.0 on the timeline)
    rc = next((c for c in caps if "roller" in c["text"]["content"].lower()), None)
    if rc:
        w = next(w for w in rc["text"]["caption"]["words"] if "roller" in w["w"].lower())
        at = rc["start"] + w["t0"]
        exp = 1.0 + truth["l1"][0] + 0.25                              # "The" comes first (~0.25 s)
        check("word timing within 0.4 s", abs(at - exp) < 0.4, f"'roller' at {at:.2f}s, expected ~{exp:.2f}s")
    mum = (1.0 + truth["mumble"][0], 1.0 + truth["mumble"][1])
    unclear_markers = [m for m in p["markers"] if m.get("kind") == "unclear"]
    in_mumble = [c for c in caps if c["start"] < mum[1] and c["start"] + c["dur"] > mum[0]]
    flagged = unclear_markers or any(c["meta"].get("review") for c in in_mumble)
    check("mumbled speech flagged for review", flagged,
          f"markers={[(round(m['t'], 2)) for m in unclear_markers]}, captions in mumble={[c['text']['content'] for c in in_mumble]}")
    check("no overlaps", all(a["start"] + a["dur"] <= b["start"] + 1e-6 for a, b in zip(caps, caps[1:])))
    # restyle, edit, rechunk
    r = call("/api/op", {"op": "restyle_captions", "args": {"ids": "all", "template": "word_pop"}})
    check("restyle all → Word Pop", all(c["text"]["caption"]["style"]["mode"] == "pop" for c in r["project"]["clips"] if c["type"] == "text"))
    first = caps[0]
    r = call("/api/op", {"op": "update", "args": {"ids": [first["id"]], "patch": {"text": {"content": "Hello *Taiwan* friends"}}}})
    c1 = next(c for c in r["project"]["clips"] if c["id"] == first["id"])
    check("edit text keeps timing span", c1["text"]["caption"]["words"][0]["t0"] == first["text"]["caption"]["words"][0]["t0"]
          and c1["text"]["caption"]["words"][1].get("emph"), c1["text"]["content"])
    r = call("/api/op", {"op": "rechunk_captions", "args": {"ids": "all", "max_words": 2, "max_chars": 20}})
    caps2 = [c for c in r["project"]["clips"] if c["type"] == "text"]
    check("rechunk to 2 words per line", all(len(c["text"]["caption"]["words"]) <= 2 for c in caps2) and len(caps2) > len(caps), f"{len(caps)} → {len(caps2)}")
    r = call("/api/captions/auto", {"scope": "clip", "ids": [vid], "template": "karaoke_line", "replace": True})
    caps3 = [c for c in r["project"]["clips"] if c["type"] == "text"]
    check("re-run replaces (no duplicates)", len(caps3) == res["captions"], f"{len(caps3)} vs {res['captions']}")
finally:
    call("/api/projects/open", {"name": "vlog"}) if any(x["name"] == "vlog" for x in call("/api/projects")["projects"]) else None
    try:
        call("/api/projects/delete", {"name": "captions test"})
    except Exception as e:
        print("cleanup:", e)
    for f in (ROOT / "cache" / "test_projects").rglob("_test_captions*.mp4"):
        for _ in range(20):
            try:
                f.unlink()
                break
            except PermissionError:
                time.sleep(0.5)
print("ALL PASS" if ok else "SOME FAILED")
