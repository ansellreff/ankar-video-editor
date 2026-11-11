"""Caption templates: browser preview (captionlayer.js) vs export renderer (caption.py) for every template mid-word,
plus screenshots of the Captions tab / Inspector. TEST server (:8766) only. python -m tests.ui_captions"""
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import websockets
from PIL import Image

from tests.ui_smoke import CDP, EDGE, OUT, ROOT, TEST_URL

PORT = 9343
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def call(path, body=None):
    req = urllib.request.Request(TEST_URL + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


WORDS = [("We", 0.0, 0.3), ("went", 0.3, 0.6), ("to", 0.6, 0.75), ("Kaohsiung", 0.75, 1.3), ("today!", 1.3, 1.9)]


async def main():
    tpls = call("/api/captions/templates")["templates"]
    tpls = [t for t in tpls if not t.get("user")]
    call("/api/projects/new", {"name": "caption parity", "format": "9:16"})
    caps = [{"start": 2.0 * i + 0.5, "end": 2.0 * i + 2.4, "words": [{"w": w, "t0": a, "t1": b} for w, a, b in WORDS]} for i in range(len(tpls))]
    for i, t in enumerate(tpls):
        call("/api/op", {"op": "add_captions", "args": {"captions_": [caps[i]], "template": t["id"]}})
    prof = OUT / "edge-profile-cap"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1680,1000",
                             "--no-first-run", "--mute-audio", "about:blank"])
    try:
        for _ in range(50):
            try:
                page = next(p for p in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=80_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            for d in ("Runtime", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && !!document.querySelector('.tl-toolbar')"):
                    break
            await cdp.call("Page.bringToFront")
            await cdp.call("Emulation.setFocusEmulationEnabled", enabled=True)
            await asyncio.sleep(2.0)
            J = cdp.js
            await J("window.__vs.set({monZoom: 1})")                    # 100%: compare at the real frame size
            await asyncio.sleep(1.0)
            print("preview canvas:", await J("[document.querySelector('canvas.screen').width, document.querySelector('canvas.screen').height]"))
            worst = []
            for i, t in enumerate(tpls):
                tt = round(caps[i]["start"] + 0.95, 4)                 # 'Kaohsiung' active, 0.2 s into it
                await J(f"window.__vs.set({{sel: {{clips: [], transition: null, asset: null}}}}); window.__vs.player.seek({tt})")
                for _ in range(40):
                    await asyncio.sleep(0.15)
                    if await J("window.__vs.player.settled()"):
                        break
                await asyncio.sleep(0.3)
                url = await J("document.querySelector('canvas.screen').toDataURL('image/png')")
                prev = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
                snap = call("/api/snapshot", {"t": tt})["path"]
                exp = Image.open(ROOT / snap if not os.path.isabs(snap) else snap).convert("RGB").resize(prev.size, Image.BOX)   # area-average: bilinear aliases thin text on a 4× shrink
                a, b = np.asarray(prev, np.float32), np.asarray(exp, np.float32)
                d = np.abs(a - b)
                region = (a.max(axis=2) > 12) | (b.max(axis=2) > 12)
                full = d.mean()
                txt = d[region].mean() if region.any() else 0.0
                worst.append((txt, t["name"]))
                Image.fromarray(np.hstack([a, b]).astype(np.uint8)).save(OUT / f"cap_cmp_{t['id']}.png")
                # text region = edge-heavy: FreeType vs browser anti-aliasing alone gives ~25-45; a 1-px shift gives 75+
                check(f"{t['name']:18s} preview = export", full < 3 and txt < 50, f"frame diff {full:4.2f}/255, text region {txt:5.1f}/255 ({region.mean():.1%} of frame)")
            print("largest text-region differences:", sorted(worst, reverse=True)[:3])
            # screenshots for the visual review
            await J("window.__vs.set({fxTab: 'captions'})")
            first = await J("window.__vs.S.project.clips.find(c => c.text?.caption).id")
            await J(f"window.__vs.set({{sel: {{clips: ['{first}'], transition: null, asset: null}}}}); window.__vs.player.seek(1.45)")
            await asyncio.sleep(2.5)
            print(await cdp.shot("ui_captions_panel.png"))
            await J("window.__vs.A.autoCaptions()")
            await asyncio.sleep(2.0)
            print(await cdp.shot("ui_captions_dialog.png"))
            errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            check("no JS exceptions", not errs, "; ".join(e["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:300] for e in errs[:3]))
    finally:
        proc.terminate()
        try:
            call("/api/projects/open", {"name": "vlog"})
        except Exception:
            pass
        try:
            call("/api/projects/delete", {"name": "caption parity"})
        except Exception as e:
            print("cleanup:", e)
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
