"""v3 parity on the TEST server (:8766): LUTs, new effects and transitions — browser preview vs export renderer
(/api/snapshot) on real footage. python -m tests.ui_v3 [filter-substring]"""
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import numpy as np
import websockets
from PIL import Image

from tests.ui_smoke import CDP, EDGE, OUT, ROOT, TEST_URL

PORT = 9345
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def call(path, body=None):
    req = urllib.request.Request(TEST_URL + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:300]}")


def op(name, **args):
    return call("/api/op", {"op": name, "args": args})["result"]


def cases(state):
    """[(label, t, setup)] — each setup builds one segment on a fresh 4 s slot."""
    pres = state["presets"]
    out = []
    lut_files = {l["name"]: l["file"] for l in state["luts"]}
    for name, amount in (("Teal & Orange", 1.0), ("Bleach Bypass", 0.6), ("Night Neon", 1.0)):
        out.append((f"LUT {name} {int(amount * 100)}%", "filter", {"type": "lut", "file": lut_files[name], "amount": amount}))
    for f in pres["filters"]:
        if f.get("v3"):
            out.append((f"Effect {f['name']}", "filter", {"type": f["id"], **{k: v["default"] for k, v in f["params"].items()}}))
    for t in pres["transitions"]:
        if t.get("v3"):
            out.append((f"Transition {t['name']}", "transition", t))
    return out


async def main(only=None):
    state = call("/api/state")
    assets = state["assets"]
    vids = [a for a in assets if a["kind"] == "video" and a["name"].startswith("sample_") and (a.get("meta") or {}).get("dur")]
    va, vb = vids[0], vids[1 % len(vids)]
    call("/api/projects/new", {"name": "v3 parity", "format": "9:16"})
    plan, slot = [], 0.0
    for label, kind, spec in cases(state):
        if only and only.lower() not in label.lower():
            continue
        if kind == "filter":
            (cid,) = op("add_media", asset=va["id"], track="V1", start=slot, in_=0.5, out=4.5, link_audio=False)
            op("update", ids=[cid], patch={"filters": [spec]})
            plan.append((label, round(slot + 1.7, 3)))
        else:
            (a,) = op("add_media", asset=va["id"], track="V1", start=slot, in_=0.5, out=3.0, link_audio=False)
            (b,) = op("add_media", asset=vb["id"], track="V1", start=slot + 2.5, in_=0.5, out=3.0, link_audio=False)
            op("add_transition", type=spec["id"], a=a, b=b, dur=1.0)
            plan.append((label, round(slot + 2.5 - 0.5 + 0.37, 3)))    # ~37% into the transition
        slot += 5.0
    prof = OUT / "edge-profile-v3"
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
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=120_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            for d in ("Runtime", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && !!document.querySelector('.clip')"):
                    break
            await cdp.call("Page.bringToFront")
            await cdp.call("Emulation.setFocusEmulationEnabled", enabled=True)
            J = cdp.js
            await J("window.__vs.set({monZoom: 0.5})")
            await asyncio.sleep(2.0)
            for label, tt in plan:
                await J(f"window.__vs.set({{sel: {{clips: [], transition: null, asset: null}}}}); window.__vs.player.seek({tt})")
                settled = False
                for _ in range(80):
                    await asyncio.sleep(0.15)
                    if await J("window.__vs.player.settled()"):
                        settled = True
                        break
                await asyncio.sleep(0.4)
                url = await J("document.querySelector('canvas.screen').toDataURL('image/png')")
                prev = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
                snap = call("/api/snapshot", {"t": tt})["path"]
                exp = Image.open(ROOT / snap).convert("RGB").resize(prev.size, Image.BOX)
                a, b = np.asarray(prev, np.float32), np.asarray(exp, np.float32)
                d = np.abs(a - b).mean()
                Image.fromarray(np.hstack([a, b]).astype(np.uint8)).save(OUT / f"v3_{label.replace(' ', '_').replace('&', 'and').replace('%', '')}.png")
                check(f"{label:34s}", d < 3 and settled, f"preview vs export {d:5.2f}/255{'' if settled else ' (preview NOT settled)'}")
            errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            cons = [e for e in cdp.events if e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] == "error"]
            check("no JS exceptions / shader errors", not errs and not cons,
                  "; ".join(str(a.get("value", a.get("description", "")))[:300] for e in cons[:3] for a in e["params"]["args"]))
    finally:
        proc.terminate()
        try:
            call("/api/projects/open", {"name": "vlog"})
            call("/api/projects/delete", {"name": "v3 parity"})
        except Exception as e:
            print("cleanup:", e)
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
