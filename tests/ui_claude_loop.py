"""Checks the Claude loop: an outside edit to projects/vlog/project.json shows up in the open UI (and is undoable)."""
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, ROOT

PORT = 9334


async def main():
    prof = OUT / "edge-profile-2"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--window-size=1680,1000", "--no-first-run", "about:blank"])
    try:
        for _ in range(50):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            await cdp.call("Runtime.enable")
            await cdp.call("Page.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url="http://localhost:8765/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && window.__vs.S.connected"):
                    break
            before = await cdp.js("window.__vs.S.project.markers.length")
            pj = ROOT / "projects" / "vlog" / "project.json"
            p = json.loads(pj.read_text(encoding="utf-8"))
            p["markers"] = [m for m in p["markers"] if not m["id"].startswith("m_claude")]
            before = len(p["markers"])
            pj.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")    # clean state first
            for _ in range(60):
                await asyncio.sleep(0.1)
                if await cdp.js("window.__vs.S.project.markers.length") == before:
                    break
            p["markers"].append({"id": f"m_claude{int(time.time())}", "t": 14.0, "label": "Scene 2 (added by Claude)", "color": "amber"})
            t0 = time.time()
            pj.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")
            seen = None
            while time.time() - t0 < 10:
                n = await cdp.js("window.__vs.S.project.markers.length")
                if n != before:
                    seen = time.time() - t0
                    break
                await asyncio.sleep(0.05)
            toasts = await cdp.js("window.__vs.S.toasts.map(t => t.text)")
            print(f"UI updated {seen:.2f}s after the file changed" if seen else "UI did NOT update", "| toasts:", toasts)
            await asyncio.sleep(0.3)
            await cdp.shot("ui_4_claude_edit.png")
            await cdp.js("window.__vs.A.undo()")
            await asyncio.sleep(0.6)
            print("after undo, markers:", await cdp.js("window.__vs.S.project.markers.map(m => m.label)"))
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
