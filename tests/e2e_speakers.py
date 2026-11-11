"""Speaker detection → voice from one speaker → quick line → MP3, via the running server (uses the 2-voice test file)."""
import json
import shutil
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_PROJECTS = __import__("pathlib").Path(__import__("os").environ.get("VLOG_PROJECTS_DIR") or ROOT / "cache" / "test_projects")  # the TEST server (:8766) keeps its projects (and their exports/) here
BASE = __import__("os").environ.get("VLOG_TEST_URL", "http://localhost:8766")


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=600).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")


truth = json.loads((ROOT / "cache/work/twospk/truth.json").read_text())
aid = None
for _ in range(40):
    aid = next((a["id"] for a in call("/api/state")["assets"] if a["name"] == "_test_two_speakers.wav" and (a.get("meta") or {}).get("dur")), None)
    if aid:
        break
    time.sleep(0.5)
try:
    for n in (None, 2):
        t = time.time()
        job = call("/api/voices/speakers", {"asset": aid, "n": n})
        print(f"\nn={n or 'auto'}: {len(job['speakers'])} speakers in {time.time() - t:.1f}s")
        for sp in job["speakers"]:
            print(f"  {sp['id']}: {sp['seconds']} s, {len(sp['turns'])} turns {sp['turns']}")
        # accuracy: label each truth turn by majority overlap
        mapping, correct, total = {}, 0.0, 0.0
        for s, e, who in truth:
            ov = {}
            for ts, te, k in job["turns"]:
                o = max(0.0, min(e, te) - max(s, ts))
                ov[k] = ov.get(k, 0) + o
            best = max(ov, key=ov.get) if ov else None
            mapping.setdefault(who, set()).add(best)
            correct += ov.get(best, 0)
            total += e - s
        print("  truth → detected:", {k: sorted(v) for k, v in mapping.items()}, f"| covered {correct / total:.0%} of speech")
    clean = all(len(v) == 1 for v in mapping.values()) and mapping["David"] != mapping["Zira"]
    print("two speakers separated correctly:", clean)
    zira = next(iter(mapping["Zira"]))
    r = call("/api/voices/from_speaker", {"job": job["id"], "speaker": zira, "voice": "E2E Speaker", "consent": True, "mood": "cheerful"})
    print("voice made from", zira, "→", r["file"])
    q = call("/api/tts/quick", {"text": "This voice was cloned from the second speaker only.", "voice": "E2E Speaker", "tone": "cheerful"})
    t0, job2 = time.time(), None
    while time.time() - t0 < 600:
        job2 = call("/api/tts/status")["jobs"].get(q["id"])
        if job2 and job2["state"] in ("done", "error"):
            break
        time.sleep(2)
    print("quick line:", {k: job2.get(k) for k in ("state", "engine", "dur", "error")})
    time.sleep(2)
    mp3s = sorted((TEST_PROJECTS).rglob("voice_test_*.mp3"), key=lambda p: p.stat().st_mtime)
    print("MP3:", mp3s[-1].relative_to(ROOT) if mp3s else "none", f"{mp3s[-1].stat().st_size // 1024} KB" if mp3s else "")
    import av
    with av.open(str(mp3s[-1])) as c:
        print("MP3 check:", c.streams.audio[0].codec_context.name, c.streams.audio[0].sample_rate, "Hz,", round(c.duration / 1e6, 2), "s")
finally:
    shutil.rmtree(ROOT / "library/voices/E2E Speaker", ignore_errors=True)
    for f in TEST_PROJECTS.rglob("_test_two_speakers.wav"):
        f.unlink(missing_ok=True)
    for f in (TEST_PROJECTS).rglob("voice_test_*.mp3"):
        f.unlink()
    for f in (ROOT / "library/generated/narration").glob("tts_*.wav"):
        f.unlink()
