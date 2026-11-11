"""UI test of the AI Editor tab on the TEST server with the scripted fake model (no network, no cost):
open the tab → send a message → an Approve card appears and NOTHING changes yet → Approve → the marker is added
(one Undo step) → a second run is Declined → nothing changes. Also reports any JS errors.

Start the test server with the fake model first:
  $env:VLOG_AI_FAKE = "1"; .\\tests\\test_server.ps1; Remove-Item Env:VLOG_AI_FAKE
python -m tests.ui_assistant"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9337


def api(path, body=None):
    req = urllib.request.Request(TEST_URL + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def markers():
    return [m for m in api("/api/state")["project"].get("markers", []) if m.get("label") == "AI test"]


async def wait_js(cdp, expr, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if await cdp.js(expr):
            return True
        await asyncio.sleep(0.3)
    return False


async def main():
    prof = OUT / "edge-profile-ai"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1680,1000", "about:blank"])
    ok = True
    try:
        for _ in range(50):
            try:
                page = next(t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            for d in ("Runtime", "Log", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            await asyncio.sleep(6)
            api("/api/assistant/new", {})                       # a fresh chat for this test
            await cdp.js("[...document.querySelectorAll('.rtab')].find(b => b.textContent.includes('AI Editor')).click()")
            panel = await wait_js(cdp, "!!document.querySelector('.ai-panel') && !!document.querySelector('.ai-steps')")
            print("AI Editor tab + stepper shown:", panel)
            ok &= panel
            for decision in ("Approve", "Decline"):
                before = len(markers())
                cur = (api("/api/assistant/state").get("chat") or {}).get("id")
                api("/api/assistant/send", {"text": f"test ({decision})", "chat": cur})
                card = await wait_js(cdp, "!!document.querySelector('.ai-card.prop.pending')")
                await asyncio.sleep(0.5)
                untouched = len(markers()) == before
                print(f"[{decision}] approval card shown: {card} · nothing changed before answering: {untouched}")
                await cdp.shot(f"ui_ai_{decision.lower()}_card.png")
                await cdp.js(f"[...document.querySelectorAll('.ai-card.prop.pending button')].find(b => b.textContent.trim() === '{decision}').click()")
                done = await wait_js(cdp, "[...document.querySelectorAll('.ai-bub')].some(b => b.textContent.includes('Done.'))"
                                          f" && document.querySelectorAll('.ai-bub').length >= {2 if decision == 'Approve' else 4}")
                await asyncio.sleep(1.0)
                after = len(markers())
                expect = before + 1 if decision == "Approve" else before
                print(f"[{decision}] turn finished: {done} · markers {before} → {after} (expected {expect})")
                ok &= card and untouched and done and after == expect
            await cdp.shot("ui_ai_done.png")
            errs = []
            for e in cdp.events:
                m, p = e.get("method"), e.get("params", {})
                if m == "Runtime.exceptionThrown":
                    errs.append(p["exceptionDetails"].get("exception", {}).get("description", "exception"))
                elif m == "Runtime.consoleAPICalled" and p["type"] == "error":
                    errs.append(" ".join(str(a.get("value", a.get("description", ""))) for a in p["args"])[:300])
            print("JS errors:", errs or "none")
            ok &= not errs
    finally:
        proc.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
