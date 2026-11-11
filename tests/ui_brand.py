"""Watermark / logo on the TEST server (:8766): a new project starts empty, a transparent PNG dropped into its import/
lands in assets/brand/logo, the watermark is drawn identically in preview and export. python -m tests.ui_brand"""
import asyncio
import base64
import io
import json
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import websockets
from PIL import Image, ImageDraw

from tests.ui_smoke import CDP, EDGE, OUT, ROOT, TEST_URL

PORT = 9349
TEST_PROJECTS = ROOT / "cache" / "test_projects"
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


def call(path, body=None):
    req = urllib.request.Request(TEST_URL + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


async def main():
    name = "brand test"
    st = call("/api/state")
    if any(p["name"] == name for p in st["projects"]):
        call("/api/projects/open", {"name": "vlog"} if any(p["name"] == "vlog" for p in st["projects"]) else {"name": st["projects"][0]["name"]})
        call("/api/projects/delete", {"name": name})
    r = call("/api/projects/new", {"name": name})
    own = [a for a in r["assets"] if a.get("scope") == "project"]
    check("new project starts with no media of its own", not own, f"{len(own)} own, {len(r['assets'])} shared")
    check("new project format = Instagram Reels", r["project"]["format"] == {"preset": "reels", "w": 1080, "h": 1920, "fps": "30/1"}, r["project"]["format"])
    # transparent logo → the project's import/ → sorted into assets/brand/logo
    logo = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(logo)
    d.rounded_rectangle((10, 10, 590, 230), 40, fill=(255, 210, 60, 230))
    d.ellipse((40, 60, 160, 180), fill=(220, 40, 90, 255))
    imp = TEST_PROJECTS / name / "import"
    logo.save(imp / "my brand logo.png")
    aid = None
    for _ in range(40):
        time.sleep(0.5)
        aid = next((a["id"] for a in call("/api/state")["assets"] if a["name"] == "my brand logo.png" and a.get("status") == "ready"), None)
        if aid:
            break
    lp = TEST_PROJECTS / name / "assets" / "brand" / "logo" / "my brand logo.png"
    check("import/ sorted the logo into assets/brand/logo", lp.exists() and aid, str(lp.relative_to(ROOT)))
    sample = next(a for a in call("/api/state")["assets"] if a["name"] == "sample_C_theme_park.mp4")
    call("/api/op", {"op": "add_media", "args": {"asset": sample["id"], "track": "V1", "start": 0, "link_audio": False}})
    call("/api/op", {"op": "set_brand", "args": {"asset": aid, "position": "tr", "size": 0.3, "opacity": 0.85}})
    prof = OUT / "edge-profile-brand"
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
            for dname in ("Runtime", "Page"):
                await cdp.call(f"{dname}.enable")
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
            await asyncio.sleep(1.5)
            await J("window.__vs.player.seek(2.0)")
            for _ in range(60):
                await asyncio.sleep(0.15)
                if await J("window.__vs.player.settled()"):
                    break
            await asyncio.sleep(0.5)
            url = await J("document.querySelector('canvas.screen').toDataURL('image/png')")
            prev = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            exp = Image.open(ROOT / call("/api/snapshot", {"t": 2.0})["path"]).convert("RGB").resize(prev.size, Image.BOX)
            a, b = np.asarray(prev, np.float32), np.asarray(exp, np.float32)
            W, H = prev.size
            corner = (slice(0, int(H * 0.2)), slice(int(W * 0.6), W))           # the logo's area (top right)
            Image.fromarray(np.hstack([a, b]).astype(np.uint8)).save(OUT / "brand_cmp.png")
            check("watermark preview = export", np.abs(a - b).mean() < 3 and np.abs(a[corner] - b[corner]).mean() < 6,
                  f"frame {np.abs(a - b).mean():.2f}/255, logo corner {np.abs(a[corner] - b[corner]).mean():.2f}/255")
            yellow = (b[corner][..., 0] > 200) & (b[corner][..., 1] > 150) & (b[corner][..., 2] < 140)
            check("logo visible top-right, transparent around it", yellow.mean() > 0.02 and np.abs(b[-50:, :50] - a[-50:, :50]).mean() < 6,
                  f"{yellow.mean():.0%} of the corner is logo yellow")
            errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            check("no JS exceptions", not errs)
    finally:
        proc.terminate()
        call("/api/projects/open", {"name": [p for p in call("/api/projects")["projects"] if p["name"] != name][0]["name"]})
        call("/api/projects/delete", {"name": name})
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
