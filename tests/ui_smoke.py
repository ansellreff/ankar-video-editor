"""UI smoke test: drives headless Edge via the DevTools protocol against a running server (localhost:8765).

python -m tests.ui_smoke [--keep]   → screenshots + console errors in cache/work/ui_*.png
Builds a v3-style edit through the same actions the menus/shortcuts use, checks the monitor renders.
"""
import asyncio
import os
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
TEST_PROJECTS = __import__("pathlib").Path(__import__("os").environ.get("VLOG_PROJECTS_DIR") or ROOT / "cache" / "test_projects")  # the TEST server (:8766) keeps its projects (and their exports/) here
OUT = ROOT / "cache" / "work"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333
TEST_URL = os.environ.get("VLOG_TEST_URL", "http://localhost:8766")   # test server (never the user's editor)


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.pending, self.events = ws, 0, {}, []

    async def reader(self):
        async for msg in self.ws:
            m = json.loads(msg)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m)
            else:
                self.events.append(m)

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        r = await asyncio.wait_for(fut, 60)
        if "error" in r:
            raise RuntimeError(r["error"])
        return r["result"]

    async def js(self, expr, await_promise=True):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]))
        return r["result"].get("value")

    async def shot(self, name, clip=None):
        p = {"format": "png"}
        if clip:
            p["clip"] = {**clip, "scale": 1}
        r = await self.call("Page.captureScreenshot", **p)
        (OUT / name).write_bytes(base64.b64decode(r["data"]))
        return OUT / name


def compare(frames: dict, mp4: Path):
    """Mean absolute difference (0-255) between browser monitor frames and the exported video at the same times."""
    import io

    import av
    import numpy as np
    from PIL import Image

    from app.colors import to_rgb
    want = sorted(frames)
    got = {}
    with av.open(str(mp4)) as c:
        for f in c.decode(video=0):
            t = float(f.time)
            for w in want:
                if w not in got and abs(t - w) < 0.5 / 29.97:       # the same frame index
                    got[w] = Image.fromarray(to_rgb(f))
    print("preview vs export (mean abs diff, 0-255; < 8 = visually identical):")
    for w in want:
        if w not in got:
            continue
        prev = Image.open(io.BytesIO(base64.b64decode(frames[w].split(",", 1)[1]))).convert("RGB")
        exp = got[w].resize(prev.size, Image.BILINEAR)
        d = np.abs(np.asarray(prev, np.float32) - np.asarray(exp, np.float32)).mean()
        print(f"  t={w:5.2f}s  diff={d:5.2f}")
        Image.fromarray(np.hstack([np.asarray(prev), np.asarray(exp)])).save(OUT / f"ui_cmp_{w:05.2f}.png")


async def main(keep=False):
    prof = OUT / "edge-profile"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--window-size=1680,1000", "--autoplay-policy=no-user-gesture-required", "--mute-audio",
                             "--no-first-run", "--disable-extensions", "about:blank"])
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
            for d in ("Runtime", "Log", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!document.querySelector('.timeline .tl-toolbar')"):
                    break
            await asyncio.sleep(1.0)
            await cdp.shot("ui_1_empty.png")

            # ---- build an edit with the same actions the UI uses
            steps = r"""
            (async () => {
              const { S, A } = window.__vs;
              const find = n => Object.values(S.assets).find(a => a.name === n).id;
              const wait = ms => new Promise(r => setTimeout(r, ms));
              const api = (p, b) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.json());
              if (S.project.clips.length) await api('/api/op', { op: 'delete', args: { ids: S.project.clips.map(c => c.id) }, label: 'Reset (test)' });
              for (const m of S.project.markers) await api('/api/op', { op: 'remove_marker', args: { id: m.id } });
              await wait(400);
              await A.typedIntro({ start: 0 });
              await A.addAsset(find('sample_A_street_night.mp4'), 8.008, 'V1');
              const tEnd = Math.max(...S.project.clips.filter(c => c.track === 'V1').map(c => c.start + (c.out - c.in)));
              await A.addAsset(find('sample_B_bikes_morning.mp4'), tEnd, 'V1');
              await A.addAsset(find('sample_C_theme_park.mp4'), tEnd + 6.006, 'V1');
              const v1 = S.project.clips.filter(c => c.track === 'V1').sort((a, b) => a.start - b.start);
              await A.applyTransition('cross_dissolve', v1[0].id, 'start');
              await A.applyTransition('inward_wipe', v1[0].id, 'end');
              await A.applyTransition('circle_iris', v1[1].id, 'end');
              await A.applyTransition('dip_black', v1[2].id, 'end');
              await A.applyFilter('warm_sun', [v1[1].id]);
              await A.applyFilter('vignette', [v1[1].id]);
              await A.applyFilter('night_boost', [v1[0].id]);
              await A.addText('caption', v1[1].start + 0.3, 'T1');
              await A.addText('lower_third', v1[2].start + 0.3, 'T2');
              A.selectClips?.([v1[1].id]);
              await wait(300);
              return { clips: S.project.clips.length, transitions: S.project.transitions.length, history: S.history };
            })()
            """
            res = await cdp.js(steps)
            print("built:", res)
            await cdp.js("window.__vs.A.zoomFit()")
            await cdp.js("window.__vs.set({ sel: { clips: [window.__vs.S.project.clips.find(c => c.track === 'V1' && c.filters.length === 2).id], transition: null, asset: null } })")
            frames = {}
            FPS = 30000 / 1001
            for t in [round(round(x * FPS) / FPS, 4) for x in (2.0, 5.5, 8.6, 14.03, 15.5, 20.5, 24.5)]:
                await cdp.js(f"window.__vs.player.seek({t})")
                await asyncio.sleep(1.2)
                frames[t] = await cdp.js("document.querySelector('canvas.screen').toDataURL('image/png')")
                if abs(t - 15.5) < 0.05:
                    await cdp.shot("ui_2_edit.png")
            for t, url in frames.items():
                (OUT / f"ui_frame_{t:05.2f}.png").write_bytes(base64.b64decode(url.split(",", 1)[1]))
            # playback for 2 s
            await cdp.js("window.__vs.player.seek(8.0); window.__vs.player.play()")
            await asyncio.sleep(2.0)
            tnow = await cdp.js("window.__vs.S.t")
            await cdp.js("window.__vs.player.pause()")
            print(f"playback advanced to t={tnow:.2f} (expected ~10)")
            # export through the dialog's API and compare preview vs export frames
            await cdp.js("window.__vs.A.dialog('export')")
            await asyncio.sleep(0.4)
            await cdp.js("fetch('/api/export', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({quality:'draft'})})")
            await asyncio.sleep(3.0)
            await cdp.shot("ui_3_export.png")
            for _ in range(600):
                await asyncio.sleep(0.5)
                if await cdp.js("window.__vs.S.exportJob === null && !!window.__vs.S.lastExport"):
                    break
            last = await cdp.js("window.__vs.S.lastExport")
            print("export:", {k: last.get(k) for k in ("version", "frames", "seconds", "fps_render", "lufs", "error")})
            await cdp.js("window.__vs.set({ dialog: null })")
            if last and not last.get("error"):
                proj = await cdp.js("window.__vs.S.projectName")
                compare(frames, TEST_PROJECTS / proj / "exports" / f"v{last['version']:02d}.mp4")

            errs = [e for e in cdp.events if e.get("method") in ("Runtime.exceptionThrown",) or
                    (e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error", "warning")) or
                    (e.get("method") == "Log.entryAdded" and e["params"]["entry"]["level"] in ("error",))]
            print(f"console problems: {len(errs)}")
            for e in errs[:20]:
                p = e["params"]
                if e["method"] == "Runtime.exceptionThrown":
                    print("  EXC", p["exceptionDetails"].get("exception", {}).get("description", p["exceptionDetails"].get("text"))[:400])
                elif e["method"] == "Runtime.consoleAPICalled":
                    print("  CON", p["type"], " ".join(str(a.get("value", a.get("description", "")))[:300] for a in p["args"]))
                else:
                    print("  LOG", p["entry"]["text"][:300], p["entry"].get("url", ""))
    finally:
        if not keep:
            proc.terminate()


if __name__ == "__main__":
    asyncio.run(main(keep="--keep" in sys.argv))
