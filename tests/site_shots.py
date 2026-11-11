"""Screenshots with headless Edge.
  python -m tests.site_shots editor   → website/public/img/*.webp from the TEST server's Demo project (port 8766)
  python -m tests.site_shots site [base_url]  → cache/work/site_*.png of every website page (desktop + phone)"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets
from PIL import Image

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "website" / "public" / "img"
PORT = 9347


async def session(fn):
    prof = OUT / "edge-profile-site"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--window-size=1680,1000", "--no-first-run", "--mute-audio", "--hide-scrollbars", "about:blank"])
    try:
        for _ in range(60):
            try:
                page = next(p for p in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if p["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=120_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await fn(cdp)
    finally:
        proc.terminate()


async def grab(cdp, full=False) -> Image.Image:
    p = {"format": "png"}
    if full:
        m = await cdp.call("Page.getLayoutMetrics")
        cs = m["cssContentSize"]
        p.update(captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": cs["width"], "height": cs["height"], "scale": 1})
    r = await cdp.call("Page.captureScreenshot", **p)
    return Image.open(io.BytesIO(base64.b64decode(r["data"])))


async def size(cdp, w, h, mobile=False, scale=1):
    await cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale, mobile=mobile)


async def editor(cdp):
    await size(cdp, 1680, 1000)
    await cdp.call("Page.navigate", url=TEST_URL + "/")
    for _ in range(150):
        await asyncio.sleep(0.2)
        if await cdp.js("!!window.__vs && !!document.querySelector('.tl-toolbar')"):
            break
    name = await cdp.js("window.__vs.S.projectName")
    assert name == "Demo", f"open the Demo project on the test server first (open: {name})"
    await asyncio.sleep(2)
    await cdp.js("window.__vs.A.zoomFit()")
    IMG.mkdir(parents=True, exist_ok=True)
    for fname, t, tab in (("editor", 21.0, "layouts"), ("captions", 46.6, "captions"), ("looks", 42.0, "luts"),
                          ("ai-editor", 21.0, "assistant")):
        await cdp.js(f"window.__vs.set({{fxTab: '{tab}', sel: {{clips: [], tr: null}}}}); window.__vs.player.seek({t})")
        await asyncio.sleep(1.0)
        await cdp.js("window.__vs.player.settled ? window.__vs.player.settled() : true")
        await asyncio.sleep(1.5)
        img = (await grab(cdp)).convert("RGB")
        img.save(IMG / f"{fname}.webp", "WEBP", quality=82, method=6)
        print("saved", fname, img.size)


async def site(cdp, base):
    out_pages = ["", "start", "whatsnew", "signup", "signin", "forgot", "privacy", "terms", "nope"]
    for w, h, mob, tag in ((1440, 900, False, "desk"), (390, 844, True, "phone")):
        await size(cdp, w, h, mob, 1)
        pages = out_pages + ["account", "admin"]
        if tag == "phone":
            pages = ["", "start", "signup", "account"]
        for p in pages:
            if p == "account":                                  # sign up a throw-away demo user (dev server only)
                await cdp.js("fetch('/api/signup', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
                             "body: JSON.stringify({username: 'demo_user', password: 'a long demo password', email: 'demo@example.com'})})"
                             ".then(r => r.status)")
                import sqlite3
                con = sqlite3.connect(str(ROOT / "cache" / "site_dev.db"))
                con.execute("UPDATE users SET last_version = '0.9.0', last_download_at = 1793000000")
                con.commit()
                con.close()
            await cdp.call("Page.navigate", url=f"{base}/{p}")
            await asyncio.sleep(1.2)
            over = await cdp.js("document.documentElement.scrollWidth > window.innerWidth + 1")
            img = await grab(cdp, full=True)
            out = OUT / f"site_{tag}_{p or 'home'}.png"
            img.save(out)
            print(f"{out.name} {img.size}{'  ⚠ horizontal scroll' if over else ''}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "editor"
    if what == "editor":
        asyncio.run(session(editor))
    else:
        base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:3000"
        asyncio.run(session(lambda c: site(c, base)))
