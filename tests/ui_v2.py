"""v2 feature test in headless Edge (run after tests.ui_smoke built the demo edit; server on :8765)."""
import asyncio
import base64
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_interact import drag, key, mouse
from tests.ui_smoke import CDP, EDGE, OUT, ROOT, compare, TEST_URL
TEST_PROJECTS = __import__("pathlib").Path(__import__("os").environ.get("VLOG_PROJECTS_DIR") or ROOT / "cache" / "test_projects")  # the TEST server (:8766) keeps its projects (and their exports/) here

PORT = 9337
FPS = 30000 / 1001
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, detail)


async def main():
    prof = OUT / "edge-profile-v2"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1680,1000",
                             "--no-first-run", "--mute-audio", "about:blank"])
    try:
        for _ in range(50):
            try:
                page = next(t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=80_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            for d in ("Runtime", "Page", "Log"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && !!document.querySelector('.clip')"):
                    break
            await asyncio.sleep(1.5)
            J = cdp.js
            clipB = "window.__vs.S.project.clips.find(c => c.track === 'V1' && (window.__vs.S.assets[c.asset]||{}).name === 'sample_B_bikes_morning.mp4')"
            # ---- 1. click in the monitor selects the visible clip
            await J("window.__vs.player.seek(16.0)")
            await asyncio.sleep(1.0)
            svg = await J("(() => { const r = document.querySelector('.mon-overlay').getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; })()")
            W, H = await J("[window.__vs.S.project.format.w, window.__vs.S.project.format.h]")
            print(f"frame {W}x{H}")
            fx = lambda x: svg["x"] + x / W * svg["w"]   # noqa: E731
            fy = lambda y: svg["y"] + y / H * svg["h"]   # noqa: E731
            px, py = W / 2, H * 0.73                      # a point inside the centered clip
            await mouse(cdp, "mousePressed", fx(px), fy(py)); await mouse(cdp, "mouseReleased", fx(px), fy(py))
            await asyncio.sleep(0.4)
            selB = await J(f"window.__vs.S.sel.clips.includes({clipB}.id)")
            check("click in monitor selects clip B", selB)
            # ---- 2. gizmo move (drag inside the box)
            m0 = await J(f"{clipB}.motion")
            await drag(cdp, fx(px), fy(py), fx(px + 100), fy(py - 100))
            m = await J(f"{clipB}.motion")
            tol = max(3, 1.5 * W / svg["w"])                # mouse events are whole screen pixels (≈4 frame px at Fit)
            check("gizmo move", abs(m["x"] - m0["x"] - 100) <= tol and abs(m["y"] - m0["y"] + 100) <= tol, f"x={m['x']} y={m['y']} (±{tol:.1f})")
            # ---- 3. gizmo scale (bottom-right corner) and rotate (knob)
            pts = await J("[...document.querySelectorAll('.gizmo circle.gz-h')].map(c => [+c.getAttribute('cx'), +c.getAttribute('cy')])")
            knob, corners = pts[0], pts[1:5]
            br = max(corners, key=lambda p: p[0] + p[1])
            cx, cy = W / 2 + m["x"], H / 2 + m["y"]
            await drag(cdp, fx(br[0]), fy(br[1]), fx(cx + (br[0] - cx) * 0.7), fy(cy + (br[1] - cy) * 0.7))
            s = await J(f"{clipB}.motion.scale")
            check("gizmo scale", 0.6 < s < 0.8, f"scale={s:.3f}")
            pts = await J("[...document.querySelectorAll('.gizmo circle.gz-h')].map(c => [+c.getAttribute('cx'), +c.getAttribute('cy')])")
            knob = pts[0]
            await drag(cdp, fx(knob[0]), fy(knob[1]), fx(cx + 400), fy(cy - 400))
            r = await J(f"{clipB}.motion.rot")
            check("gizmo rotate", 30 < r < 60, f"rot={r:.1f}")
            await key(cdp, "z", "KeyZ", mods=2, vk=90)          # undo rotate for a cleaner export check
            # ---- 4. text: drag the caption
            await J("window.__vs.player.seek(15.0)")
            await asyncio.sleep(0.8)
            cap = "window.__vs.S.project.clips.find(c => c.type === 'text' && c.text.content.startsWith('The next'))"
            y0 = await J(f"{cap}.text.y")
            await mouse(cdp, "mousePressed", fx(W / 2), fy(y0 * H)); await mouse(cdp, "mouseReleased", fx(W / 2), fy(y0 * H))
            await asyncio.sleep(0.3)
            picked = await J("(() => { const c = window.__vs.S.project.clips.find(k => k.id === window.__vs.S.sel.clips[0]); return c ? c.type + ':' + c.track : 'none'; })()")
            print("   clicked on the caption, selected:", picked)
            await drag(cdp, fx(W / 2), fy(y0 * H), fx(W / 2), fy(y0 * H + H * 0.1))
            y1 = await J(f"{cap}.text.y")
            check("drag text in monitor", abs((y1 - y0) - 0.1) < 0.01, f"y {y0:.3f} → {y1:.3f}")
            await J(f"window.__vs.A.selectClips?.([{cap}.id]); window.__vs.set({{sel: {{clips: [{cap}.id], transition: null, asset: null}}}})")
            await J(f"fetch('/api/op', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{op:'update', args:{{ids:[{cap}.id], patch:{{motion:{{rot: -8, scale: 1.3}}}}}}}})}})")
            # ---- 5. keyframes: Ken Burns on clip C
            clipC = "window.__vs.S.project.clips.find(c => c.track === 'V1' && (window.__vs.S.assets[c.asset]||{}).name === 'sample_C_theme_park.mp4')"
            await J(f"window.__vs.A.animPreset('ken_burns_in', [{clipC}.id])")
            await asyncio.sleep(0.6)
            nk = await J("document.querySelectorAll('.clip .keys i').length")
            check("keyframe diamonds on timeline", nk >= 2, f"{nk} diamonds")
            # ---- 6. freeze frame via Shift+F at 9.5 s on clip A
            n0 = await J("window.__vs.S.project.clips.length")
            await J("window.__vs.set({sel: {clips: [], transition: null, asset: null}}); window.__vs.player.seek(9.5)")
            await asyncio.sleep(0.4)
            await key(cdp, "F", "KeyF", mods=8, vk=70)
            fz = await J("window.__vs.S.project.clips.filter(c => c.hold != null).map(c => [c.start, c.dur, c.hold])")
            check("Shift+F inserts a 2 s freeze frame", len(fz) == 1 and abs(fz[0][1] - 2) < 0.05, f"{fz}")
            # ---- 7. speed dialog 50% on clip C (Ctrl+R)
            await J(f"window.__vs.set({{sel: {{clips: [{clipC}.id], transition: null, asset: null}}}})")
            await key(cdp, "r", "KeyR", mods=2, vk=82)
            await asyncio.sleep(0.4)
            await J("(() => { const b = [...document.querySelectorAll('.dialog .seg button')].find(b => b.textContent === '0.5×'); b.click(); })()")
            await asyncio.sleep(0.2)
            await J("[...document.querySelectorAll('.dialog .btn.primary')].find(b => b.textContent.includes('Apply')).click()")
            await asyncio.sleep(0.8)
            sp = await J(f"{clipC}.speed")
            check("Speed dialog 50%", abs(sp - 0.5) < 1e-6, f"speed={sp}")
            # ---- 8. rate stretch tool on clip A's end edge: shrink 1 s → faster
            await key(cdp, "r", "KeyR", vk=82)
            await J("window.__vs.set({pps: 40})")
            await asyncio.sleep(0.4)
            clipA = "window.__vs.S.project.clips.find(c => c.track === 'V1' && (window.__vs.S.assets[c.asset]||{}).name === 'sample_A_street_night.mp4' && c.hold == null && c.start < 9)"
            rr = await J(f"(() => {{ const el = [...document.querySelectorAll('.lane.video .clip')].find(e => e.title.startsWith('sample_A')); const r = el.getBoundingClientRect(); return {{x: r.left, y: r.top, w: r.width}}; }})()")
            spA0 = await J(f"{clipA}.speed")
            await drag(cdp, rr["x"] + rr["w"] - 3, rr["y"] + 10, rr["x"] + rr["w"] - 3 - 20, rr["y"] + 10)
            spA1 = await J(f"{clipA}.speed")
            check("rate stretch tool speeds the clip up", spA1 > spA0 * 1.1, f"speed {spA0:.3f} → {spA1:.3f}")
            await key(cdp, "v", "KeyV", vk=86)
            # ---- 9. split-screen layout with a clip on V2
            await J("(async () => { const a = Object.values(window.__vs.S.assets).find(x => x.name === 'sample_B_bikes_morning.mp4'); "
                    "await window.__vs.A.addAsset(a.id, 0.5, 'V2'); })()")
            await asyncio.sleep(0.6)
            await J("(async () => { const p = window.__vs.S.project; const v2 = p.clips.find(c => c.track === 'V2'); "
                    "const v1 = p.clips.find(c => c.track === 'V1' && c.start <= 1 && c.start + (c.out - c.in) > 1) || p.clips.find(c => c.track === 'V1'); "
                    "await window.__vs.A.layout('split_lr', [v1.id, v2.id]); })()")
            await asyncio.sleep(0.6)
            v2m = await J("(() => { const c = window.__vs.S.project.clips.find(c => c.track === 'V2'); return [c.motion.x, c.crop.l, c.crop.r]; })()")
            check("split layout: V2 on the right half", v2m[0] == W / 4, f"{v2m}")
            # ---- 10. parity export of all of the above
            FR = [round(round(x * FPS) / FPS, 4) for x in (1.5, 10.2, 15.0, 17.0, 21.0, 25.0)]
            frames = {}
            await cdp.call("Page.bringToFront")              # headless pages can turn "hidden", which stops frames
            await cdp.call("Emulation.setFocusEmulationEnabled", enabled=True)
            await asyncio.sleep(1.5)                         # let the last edits reach the preview
            for t in FR:
                await J(f"window.__vs.set({{sel: {{clips: [], transition: null, asset: null}}}}); window.__vs.player.seek({t})")
                await asyncio.sleep(0.3)
                settled = False
                for _ in range(60):                          # wait until every visible layer has its frame
                    if await J("window.__vs.player.settled()"):
                        settled = True
                        break
                    await asyncio.sleep(0.15)
                if not settled:
                    print(f"   preview not settled at {t}:", await J("JSON.stringify({dirty: window.__vs.player.dirty, keys: window.__vs.player.visibleKeys})"),
                          await J("new Promise(r => { let ok = false; requestAnimationFrame(() => { ok = true; r('rAF alive'); }); setTimeout(() => ok || r('rAF STALLED (browser not producing frames)'), 2500); })"),
                          await J("document.visibilityState"))
                    for e in cdp.events:
                        if e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] == "error":
                            print("   CONSOLE ERROR:", " ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:900])
                    cdp.events.clear()
                await asyncio.sleep(0.25)
                frames[t] = await J("document.querySelector('canvas.screen').toDataURL('image/png')")
            try:
                await cdp.shot("ui_v2_edit.png")
            except Exception as e:  # noqa: BLE001 - screenshots are a nice-to-have here
                print("   (screenshot skipped:", type(e).__name__, ")")
            await J("fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({quality:'draft'})})")
            for _ in range(800):
                await asyncio.sleep(0.5)
                if await J("window.__vs.S.exportJob === null && !!window.__vs.S.lastExport"):
                    break
            last = await J("window.__vs.S.lastExport")
            print("export:", {k: last.get(k) for k in ("version", "frames", "seconds", "fps_render", "error")})
            proj = await J("window.__vs.S.projectName")
            compare(frames, TEST_PROJECTS / proj / "exports" / f"v{last['version']:02d}.mp4")
            # ---- 11. projects: create, switch back
            await J("window.__vs.A.newProject()")
            await asyncio.sleep(0.4)
            await J("(() => { const i = document.querySelector('.dialog input.input'); i.value = 'UI Test Project'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
            await asyncio.sleep(0.2)
            await J("[...document.querySelectorAll('.dialog .btn.primary')].find(b => b.textContent.includes('Create')).click()")
            await asyncio.sleep(1.0)
            nm = await J("[window.__vs.S.projectName, window.__vs.S.project.clips.length]")
            check("New Project creates and opens an empty project", nm == ["UI Test Project", 0], f"{nm}")
            await J("window.__vs.A.switchProject('vlog')")
            await asyncio.sleep(1.0)
            nm2 = await J("[window.__vs.S.projectName, window.__vs.S.project.clips.length]")
            check("switch back to 'vlog' keeps its timeline", nm2[0] == "vlog" and nm2[1] > 5, f"{nm2}")
            await J("fetch('/api/projects/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({name:'UI Test Project'})})")
            errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            check("no JS exceptions", not errs, "; ".join(e["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:200] for e in errs[:3]))
    finally:
        proc.terminate()
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
