"""Real pointer/keyboard interaction test on the timeline (run after tests.ui_smoke has built the demo edit)."""
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9335


async def mouse(cdp, kind, x, y, buttons=1):
    await cdp.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left" if kind != "mouseMoved" or buttons else "none",
                   buttons=buttons, clickCount=1)


async def drag(cdp, x0, y0, x1, y1, steps=8):
    await mouse(cdp, "mouseMoved", x0, y0, 0)
    await mouse(cdp, "mousePressed", x0, y0)
    for i in range(1, steps + 1):
        await mouse(cdp, "mouseMoved", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        await asyncio.sleep(0.02)
    await mouse(cdp, "mouseReleased", x1, y1)
    await asyncio.sleep(0.6)


async def key(cdp, k, code, mods=0, vk=0):
    for t in ("keyDown", "keyUp"):
        await cdp.call("Input.dispatchKeyEvent", type=t, key=k, code=code, modifiers=mods, windowsVirtualKeyCode=vk)
    await asyncio.sleep(0.5)


async def main():
    prof = OUT / "edge-profile-3"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--window-size=1680,1000", "--no-first-run", "about:blank"])
    ok = True
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
            for d in ("Runtime", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!document.querySelector('.clip')"):
                    break
            await asyncio.sleep(1.0)
            await cdp.js("window.__vs.set({pps: 40})")
            await asyncio.sleep(0.5)

            def check(name, cond, detail=""):
                nonlocal ok
                ok &= bool(cond)
                print(("PASS " if cond else "FAIL ") + name, detail)

            rect = """(name) => { const el = [...document.querySelectorAll('.lane.video .clip')].find(e => e.title.startsWith(name));
                       const r = el.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }"""
            clip = "(name) => window.__vs.S.project.clips.find(c => c.track.startsWith('V') && (window.__vs.S.assets[c.asset]||{}).name === name)"
            c_name = "sample_C_theme_park.mp4"
            r = await cdp.js(f"({rect})('{c_name}')")
            before = await cdp.js(f"({clip})('{c_name}').start")
            # 1. move clip C right by 80 px (2 s at 40 px/s)
            await drag(cdp, r["x"] + r["w"] / 2, r["y"] + r["h"] / 2, r["x"] + r["w"] / 2 + 80, r["y"] + r["h"] / 2)
            after = await cdp.js(f"({clip})('{c_name}').start")
            check("drag-move clip", abs((after - before) - 2.0) < 0.15, f"start {before:.2f} → {after:.2f}")
            linked = await cdp.js(f"(() => {{ const v = ({clip})('{c_name}'); return window.__vs.S.project.clips.find(c => c.link === v.link && c.id !== v.id).start; }})()")
            check("linked audio moved too", abs(linked - after) < 1e-3, f"audio start {linked:.2f}")
            # 2. trim C's right edge left by 40 px (1 s)
            r = await cdp.js(f"({rect})('{c_name}')")
            dur0 = await cdp.js(f"(() => {{ const c = ({clip})('{c_name}'); return (c.out - c.in) / c.speed; }})()")
            await drag(cdp, r["x"] + r["w"] - 3, r["y"] + 10, r["x"] + r["w"] - 43, r["y"] + 10)   # upper part: above the transition band
            dur1 = await cdp.js(f"(() => {{ const c = ({clip})('{c_name}'); return (c.out - c.in) / c.speed; }})()")
            check("trim right edge", abs((dur0 - dur1) - 1.0) < 0.15, f"duration {dur0:.2f} → {dur1:.2f}")
            # 3. razor: press C, click in the middle of clip C → split
            n0 = await cdp.js("window.__vs.S.project.clips.length")
            await key(cdp, "c", "KeyC", vk=67)
            r = await cdp.js(f"({rect})('{c_name}')")
            await mouse(cdp, "mouseMoved", r["x"] + r["w"] / 2, r["y"] + 20, 0)
            await mouse(cdp, "mousePressed", r["x"] + r["w"] / 2, r["y"] + 20)
            await mouse(cdp, "mouseReleased", r["x"] + r["w"] / 2, r["y"] + 20)
            await asyncio.sleep(0.6)
            n1 = await cdp.js("window.__vs.S.project.clips.length")
            check("razor split (video + linked audio)", n1 == n0 + 2, f"clips {n0} → {n1}")
            await key(cdp, "v", "KeyV", vk=86)
            # 4. ruler scrub
            rr = await cdp.js("(() => { const r = document.querySelector('.ruler').getBoundingClientRect(); return {x: r.left, y: r.top}; })()")
            sl = await cdp.js("document.querySelector('.tl-scroll').scrollLeft")
            await mouse(cdp, "mousePressed", rr["x"] + 200, rr["y"] + 14)
            await mouse(cdp, "mouseReleased", rr["x"] + 200, rr["y"] + 14)
            await asyncio.sleep(0.3)
            t = await cdp.js("window.__vs.S.t")
            check("ruler click seeks", abs(t - (200 + sl) / 40) < 0.1, f"t={t:.2f}")
            # 5. Ctrl+Z three times → C back where it was
            for _ in range(3):
                await key(cdp, "z", "KeyZ", mods=2, vk=90)
            back = await cdp.js(f"({clip})('{c_name}').start")
            n2 = await cdp.js("window.__vs.S.project.clips.length")
            check("Ctrl+Z ×3 restores", abs(back - before) < 1e-3 and n2 == n0, f"start {back:.2f}, clips {n2}")
            # 6. select clip + Delete key, then undo
            r = await cdp.js(f"({rect})('{c_name}')")
            await mouse(cdp, "mousePressed", r["x"] + 10, r["y"] + 20)
            await mouse(cdp, "mouseReleased", r["x"] + 10, r["y"] + 20)
            await asyncio.sleep(0.3)
            await key(cdp, "Delete", "Delete", vk=46)
            n3 = await cdp.js("window.__vs.S.project.clips.length")
            await key(cdp, "z", "KeyZ", mods=2, vk=90)
            n4 = await cdp.js("window.__vs.S.project.clips.length")
            check("Delete key removes clip + linked audio, undo restores", n3 == n0 - 2 and n4 == n0, f"{n0} → {n3} → {n4}")
            await cdp.shot("ui_5_interact.png")
    finally:
        proc.terminate()
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
