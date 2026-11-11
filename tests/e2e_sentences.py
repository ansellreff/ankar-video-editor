"""Narration sentence timing end-to-end on the TEST server (:8766) — no voice engine and no credits needed:
a synthetic 2-shot video with two bursts of "talking", and a 3-sentence narration assembled from fake speech.
Checks: placed narration is sentence-editable, Match to video finds the shot change and the talking and places the
sentences around it, moving a sentence re-composes the audio (and undo restores it).
python -m tests.e2e_sentences"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import av
import numpy as np
from scipy.io import wavfile

from app.paths import GENERATED_NARRATION, ROOT
from app.tts import pacing
from tests.test_pacing import fake_speech

BASE = os.environ.get("VLOG_TEST_URL", "http://localhost:8766")
PROJECTS = ROOT / "cache" / "test_projects"
NAME = "E2E Sentences"
TALK = [(1.0, 2.0), (4.0, 4.8)]           # where "people talk" in the test video
CUT = 3.0


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}") from None


def make_video(f: Path):
    sr, n = 48000, 6 * 48000
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.003, n).astype(np.float32)
    t = np.arange(n) / sr
    for s0, s1 in TALK:                                       # syllable-like bursts
        m = (t >= s0) & (t < s1)
        a[m] += 0.3 * np.sin(2 * np.pi * 180 * t[m]) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t[m]))
    with av.open(str(f), "w") as out:
        v = out.add_stream("libx264", rate=25)
        v.width, v.height, v.pix_fmt = 288, 512, "yuv420p"
        au = out.add_stream("aac", rate=sr)
        au.layout = "mono"
        for i in range(150):
            img = np.zeros((512, 288, 3), np.uint8)
            img[:] = (190, 60, 40) if i / 25 < CUT else (30, 70, 200)
            img[200:260, (i * 4) % 288:(i * 4) % 288 + 20] = 255
            for p in v.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(p)
        for p in v.encode():
            out.mux(p)
        for k in range(0, n, 1024):
            fr = av.AudioFrame.from_ndarray(a[None, k:k + 1024], format="flt", layout="mono")
            fr.sample_rate = sr
            for p in au.encode(fr):
                out.mux(p)
        for p in au.encode():
            out.mux(p)


def make_narration() -> tuple[str, str]:
    text = "Here we are at the park today. Look at that giant ride over there. We are going to try it now!"
    ps = pacing.split_text(text)
    y, info = pacing.assemble(ps, [fake_speech(3 + i, 6.0) for i in range(len(ps))])
    f = GENERATED_NARRATION / "tts_e2e_sentences.wav"
    wavfile.write(f, 48000, (np.clip(y, -1, 1) * 32767).astype(np.int16))
    f.with_suffix(".json").write_text(json.dumps(info), encoding="utf-8")
    return f"library/generated/narration/{f.name}", text


def main():
    ok = True
    names = [p["name"] for p in call("/api/projects")["projects"]]
    if NAME in names:
        call("/api/projects/delete", {"name": NAME})
    call("/api/projects/new", {"name": NAME})
    vdir = PROJECTS / NAME / "assets" / "video"
    vdir.mkdir(parents=True, exist_ok=True)
    make_video(vdir / "two_shots.mp4")
    call("/api/rescan", {})
    aid = None
    for _ in range(60):
        st = call("/api/state")
        a = next((x for x in st["assets"] if x["name"] == "two_shots.mp4"), None)
        if a and a.get("status") == "ready":
            aid = a["id"]
            break
        time.sleep(0.5)
    print("video asset ready:", bool(aid))
    call("/api/op", {"op": "add_media", "args": {"asset": aid, "track": "V1", "start": 0.0}, "label": "Add"})
    nfile, text = make_narration()
    r = call("/api/tts/place", {"file": nfile, "start": 0.0, "text": text, "voice": None})
    c = next(k for k in r["project"]["clips"] if k["type"] == "tts")
    segs = c["tts"]["segs"]
    print(f"placed as narration clip with {len(segs or [])} sentences, asset={bool(c.get('asset'))}")
    ok &= bool(segs) and len(segs) == 3 and c["tts"]["text"] == text

    ctx = call("/api/tts/context", {"t0": 0, "t1": 7})
    print("context cuts:", ctx["cuts"], " speech:", ctx["speech"], " sources:", ctx["sources"])
    ok &= any(abs(k - CUT) < 0.25 for k in ctx["cuts"])
    for s0, s1 in TALK:
        ok &= any(a <= s0 + 0.2 and b >= s1 - 0.2 for a, b in ctx["speech"])

    rep = call("/api/tts/match", {"clip": c["id"], "mode": "under", "avoid": True, "snap": True, "dry_run": True})
    print("match plan:", {k: rep[k] for k in ("starts", "speed", "end", "fits", "over", "collisions", "range")})
    ok &= rep["range"][0] == 0.0 and abs(rep["range"][1] - 6.0) < 0.05 and rep["collisions"] == 0
    res = call("/api/tts/match", {"clip": c["id"], "mode": "under", "avoid": True, "snap": True})
    c = next(k for k in res["project"]["clips"] if k["id"] == c["id"])
    ok &= bool(c["tts"]["layout"]) and c["tts"]["file"].split("/")[-1].startswith("lay_")
    # the composed file really has sound where the sentences are and silence under the talking
    sr, z = wavfile.read(ROOT / c["tts"]["file"])
    z = np.abs(z.astype(np.float32) / 32768)
    o = c["start"] - c["in"]
    lev = lambda t0, t1: float(z[max(0, int((t0 - o) * sr)):max(0, int((t1 - o) * sr))].max(initial=0))   # noqa: E731
    talk_quiet = all(lev(a + 0.05, b - 0.05) < 1e-3 for a, b in TALK if b > c["start"])
    sent_loud = all(lev(s + 0.2, s + 0.5) > 0.05 for s in rep["starts"])
    print(f"applied: clip {c['start']:.2f}→{c['start'] + c['dur']:.2f} s; silent under the talking: {talk_quiet}; sentences audible: {sent_loud}")
    ok &= talk_quiet and sent_loud

    o = c["start"] - c["in"]
    times = [o + l["at"] for l in c["tts"]["layout"]]
    times2 = times[:]
    times2[2] += 0.4
    r2 = call("/api/tts/layout", {"clip": c["id"], "starts": times2, "speeds": [1.0, 1.0, 1.1]})
    c2 = next(k for k in r2["project"]["clips"] if k["id"] == c["id"])
    o2 = c2["start"] - c2["in"]
    moved = abs((o2 + c2["tts"]["layout"][2]["at"]) - times2[2]) < 0.01 and c2["tts"]["layout"][2]["speed"] == 1.1
    print("moved sentence 3 by +0.4 s at 1.1×:", moved, "file changed:", c2["tts"]["file"] != c["tts"]["file"])
    ok &= moved and c2["tts"]["file"] != c["tts"]["file"]
    u = call("/api/undo", {"client": "e2e"})
    cu = next(k for k in u["project"]["clips"] if k["id"] == c["id"])
    ok &= cu["tts"]["layout"] == c["tts"]["layout"] and cu["tts"]["file"] == c["tts"]["file"]
    print("undo restores the previous timing:", cu["tts"]["layout"] == c["tts"]["layout"])
    rr = call("/api/tts/layout", {"clip": c["id"], "reset": True})
    cr = next(k for k in rr["project"]["clips"] if k["id"] == c["id"])
    ok &= cr["tts"]["layout"] is None and cr["tts"]["file"] == nfile
    print("reset → original file:", cr["tts"]["file"] == nfile)
    tight = call("/api/tts/match", {"clip": c["id"], "mode": "range", "range": [0.0, 1.5], "dry_run": True})
    print("too-short range:", {k: tight[k] for k in ("fits", "over", "words")})
    ok &= not tight["fits"] and tight["words"] > 0
    print("ALL PASS" if ok else "SOME FAILED")       # tests.ui_sentences continues with this project, then cleans up


if __name__ == "__main__":
    main()
