"""Open the app in headless Edge and print any JS errors (module load failures, exceptions, console errors)."""
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9336


async def main():
    prof = OUT / "edge-profile-err"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1680,1000", "about:blank"])
    try:
        for _ in range(50):
            try:
                page = next(t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            for d in ("Runtime", "Log", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            await asyncio.sleep(6)
            print("app loaded:", await cdp.js("!!window.__vs"))
            for e in cdp.events:
                m, p = e.get("method"), e.get("params", {})
                if m == "Runtime.exceptionThrown":
                    d = p["exceptionDetails"]
                    print("EXC", d.get("exception", {}).get("description", d.get("text")), d.get("url", ""), d.get("lineNumber"))
                elif m == "Runtime.consoleAPICalled" and p["type"] in ("error", "warning"):
                    print("CON", p["type"], " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"])[:500])
                elif m == "Log.entryAdded" and p["entry"]["level"] in ("error", "warning"):
                    print("LOG", p["entry"]["text"][:500], p["entry"].get("url", ""), p["entry"].get("lineNumber", ""))
            await cdp.shot("ui_err.png")
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
