"""Screenshot the running app (whole window + timeline) for a visual review: python -m tests.ui_shot [name] [t]"""
import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9341


async def main(name="ui_review", t=None):
    prof = OUT / "edge-profile-shot"
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
            await cdp.call("Page.enable"); await cdp.call("Runtime.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && !!document.querySelector('.tl-toolbar')"):
                    break
            await asyncio.sleep(1.5)
            await cdp.js("window.__vs.A.zoomFit()")
            if t is not None:
                await cdp.js(f"window.__vs.player.seek({t})")
            if len(sys.argv) > 3:                            # optional JS to run first (e.g. open a tab)
                await cdp.js(sys.argv[3])
            await asyncio.sleep(2.5)
            print(await cdp.shot(f"{name}.png"))
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "ui_review", float(sys.argv[2]) if len(sys.argv) > 2 else None))
