"""End-to-end backend check (not a pytest unit test): library → editor ops → export. Run: python -m tests.e2e_backend"""
import json
import time
from pathlib import Path

import av
import numpy as np

from app import generators
from app.library import Library
from app.paths import CACHE, ROOT
from app.project import Editor
from app.render import compositor

events = []
lib = Library(notify=lambda k, d: events.append(k))
lib.scan()
t0 = time.time()
while any(a.get("status") in ("queued", "processing") for a in lib.list()) and time.time() - t0 < 300:
    time.sleep(0.5)
assets = {a["name"]: a for a in lib.list()}
for n in ("sample_A_street_night.mp4", "sample_B_bikes_morning.mp4"):
    a = assets[n]
    d = lib.cache_dir(a["id"])
    print(f"{n}: status={a['status']} dur={a['meta']['dur']} {a['meta']['w']}x{a['meta']['h']} "
          f"proxy={(d / 'proxy.mp4').exists()} strip={a['derived'].get('strip', {}).get('count')} wave={(d / 'wave.json').exists()}")
print(f"library: {len(assets)} assets, processed in {time.time() - t0:.1f}s")

tmp = CACHE / "work" / "e2e_project.json"
tmp.unlink(missing_ok=True)
ed = Editor(tmp, asset_info=lib.get)
A, B = assets["sample_A_street_night.mp4"]["id"], assets["sample_B_bikes_morning.mp4"]["id"]
r = generators.typed_intro()
wav = lib.register(ROOT / r["wav"])
ed.apply_batch([("add_text", t) for t in r["texts"]] + [("add_media", {"asset": wav["id"], "track": "A3", "start": 0})], "intro")
a_ids = ed.apply("add_media", {"asset": A, "track": "V1", "start": 8.0})
b_ids = ed.apply("add_media", {"asset": B, "track": "V1", "start": ed.end(ed.clip(a_ids[0]))})
ed.apply("add_transition", {"type": "cross_dissolve", "b": a_ids[0], "dur": 0.4})
ed.apply("add_transition", {"type": "inward_wipe", "a": a_ids[0], "b": b_ids[0], "dur": 0.8})
ed.apply("add_transition", {"type": "dip_black", "a": b_ids[0], "dur": 1.0})
ed.apply("update", {"ids": [b_ids[0]], "patch": {"filters": [{"type": "warm_sun", "amount": 0.8}, {"type": "vignette", "amount": 0.5, "size": 0.75}]}})
ed.apply("add_text", {"track": "T1", "start": 14.2, "dur": 3, "content": "The next morning...", "y": 0.16,
                      "style": {"weight": 600, "size": 60, "outline": 4}, "anim": {"in": "fade", "in_dur": 0.4}})
print("timeline:", [(c["id"], c["track"], c["start"], round(ed.end(c), 3)) for c in ed.p["clips"]])
print("transitions:", [(x["type"], x["a"], x["b"], x["dur"]) for x in ed.p["transitions"]])

out = CACHE / "work" / "e2e_export.mp4"
stages = {}
rep = compositor.render(ed.p, {aid: lib.get(aid) for aid in ed.p["assets"]}, out, preset="draft",
                        progress=lambda s, v: stages.__setitem__(s, v))
print("export:", json.dumps(rep))

# sample frames for a visual check
want = [2.0, 5.5, 8.2, 11.0, 14.03, 15.0, 19.7]
frames = []
with av.open(str(out)) as c:
    for f in c.decode(video=0):
        t = float(f.time)
        if want and t >= want[0]:
            frames.append((want.pop(0), f.to_image().resize((216, 384))))
from PIL import Image, ImageDraw
sheet = Image.new("RGB", (len(frames) * 226, 410), (40, 40, 40))
for i, (t, im) in enumerate(frames):
    sheet.paste(im, (i * 226, 0))
    ImageDraw.Draw(sheet).text((i * 226 + 4, 390), f"t={t}", fill="white")
sheet.save(CACHE / "work" / "e2e_sheet.png")
print("sheet:", CACHE / "work" / "e2e_sheet.png")
