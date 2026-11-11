"""Steady pacing end-to-end on the TEST server (:8766) with the local engine (built-in voice):
the same 3-sentence line at Slow and Fast (the second re-uses the cached sentences), plus long pauses."""
import json
import os
import time
import urllib.request

BASE = os.environ.get("VLOG_TEST_URL", "http://localhost:8766")
TEXT = ("After a long and busy week, we finally made it to Kaohsiung. "
        "Tomorrow we ride our bikes to E-DA Theme Park. [pause 0.8] It is going to be so much fun!")


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    return json.loads(urllib.request.urlopen(req, timeout=900).read())


def quick(**kw):
    t = time.time()
    qid = call("/api/tts/quick", {"text": TEXT, "voice": None, "tone": "neutral", **kw})["id"]
    while True:
        j = call("/api/tts/status")["jobs"].get(qid)
        if j and j["state"] in ("done", "error"):
            return j, round(time.time() - t, 1)
        time.sleep(1.5)


ok = True
res = {}
for label, kw in (("auto", {"rate": None}), ("slow", {"rate": "slow"}), ("fast", {"rate": "fast"}),
                  ("fast, long pauses", {"rate": "fast", "pause": 2.0})):
    j, secs = quick(**kw)
    res[label] = j
    print(f"{label:18s} state={j['state']} dur={j.get('dur')} s  wpm={j.get('wpm')}  pieces={j.get('pieces')}  took {secs}s  {j.get('error', '')}")
    ok &= j["state"] == "done"
if ok:
    ok &= res["slow"]["dur"] > res["fast"]["dur"] and res["slow"]["wpm"] < res["fast"]["wpm"]
    ok &= res["fast, long pauses"]["dur"] > res["fast"]["dur"]
    ok &= abs(res["slow"]["wpm"] - 140) < 15 and abs(res["fast"]["wpm"] - 220) < 20
print("ALL PASS" if ok else "SOME FAILED")
