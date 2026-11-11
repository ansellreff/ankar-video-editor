"""Voice effects parity on the TEST server (:8766): the browser's WebAudio graph (web/js/voicefx.js, rendered offline)
vs the export engine (app/render/voicefx.py) on the same test tones. Levels must agree within 1 dB.
python -m tests.ui_voicefx"""
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import numpy as np
import websockets

from app.render import voicefx as vf
from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9347
SR = 48000
CASES = [
    ("phone @1.2 kHz", {"filter": "phone"}, 1200), ("phone @150 Hz", {"filter": "phone"}, 150), ("phone @7 kHz", {"filter": "phone"}, 7000),
    ("megaphone @2.4 kHz", {"filter": "megaphone"}, 2400), ("lo-fi @1 kHz", {"filter": "lofi"}, 1000),
    ("through a wall @2 kHz", {"filter": "through_wall"}, 2000), ("robot @800 Hz", {"filter": "robot"}, 800),
    ("vintage mic @8 kHz", {"filter": "vintage_mic"}, 8000),
    ("far @6 kHz", {"distance": 1.0}, 6000), ("medium @1 kHz", {"distance": 0.5}, 1000),
    ("pan left", {"pan": -0.7}, 500), ("hall reverb", {"space": "hall", "space_mix": 0.5}, 700),
    ("phone + café space + far", {"filter": "phone", "space": "cafe", "distance": 0.6}, 1500),
]

JS = """async (cases) => {
  const vfx = await import('/web/js/voicefx.js');
  const out = [];
  // warm the IR cache (files load asynchronously)
  const warm = new OfflineAudioContext(2, 4800, 48000);
  for (const [, fx] of cases) vfx.buildChain(warm, fx);
  await new Promise(r => setTimeout(r, 2500));
  for (const [label, fx, f] of cases) {
    const ctx = new OfflineAudioContext(2, 48000, 48000);
    const buf = ctx.createBuffer(1, 48000, 48000);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = 0.3 * Math.sin(2 * Math.PI * f * i / 48000);
    const src = new AudioBufferSourceNode(ctx, { buffer: buf });
    const ch = vfx.buildChain(ctx, fx);
    src.connect(ch.input); ch.output.connect(ctx.destination); src.start();
    const r = await ctx.startRendering();
    const rms = c => { const x = r.getChannelData(c).subarray(12000); let s = 0; for (const v of x) s += v * v; return Math.sqrt(s / x.length); };
    out.push([label, rms(0), rms(1)]);
  }
  return out;
}"""


async def main():
    prof = OUT / "edge-profile-vfx"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                             "--no-first-run", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "about:blank"])
    ok = True
    try:
        for _ in range(50):
            try:
                page = next(p for p in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read()) if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            cdp = CDP(ws)
            asyncio.create_task(cdp.reader())
            await cdp.call("Runtime.enable")
            await cdp.call("Page.enable")
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            for _ in range(100):
                await asyncio.sleep(0.2)
                if await cdp.js("!!window.__vs && !!window.__vs.S.presets && !!window.__vs.S.ambience"):
                    break
            r = await cdp.call("Runtime.evaluate", expression=f"({JS})({json.dumps(CASES)})", awaitPromise=True, returnByValue=True)
            res = r["result"]["value"]
            for (label, fx, f), (_, l_js, r_js) in zip(CASES, res):
                t = np.arange(SR) / SR
                x = (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)
                y = vf.process(np.stack([x, x]), fx, 0.0)
                l_py, r_py = (float(np.sqrt((y[c, 12000:] ** 2).mean())) for c in range(2))
                db = lambda a: 20 * np.log10(max(a, 1e-7))  # noqa: E731
                dl, dr = db(l_js) - db(l_py), db(r_js) - db(r_py)
                good = (abs(dl) < 1.0 or max(l_js, l_py) < 1e-4) and (abs(dr) < 1.0 or max(r_js, r_py) < 1e-4)
                ok &= good
                print(f"{'PASS' if good else 'FAIL'} {label:28s} browser L/R {db(l_js):6.1f}/{db(r_js):6.1f} dB   export {db(l_py):6.1f}/{db(r_py):6.1f} dB")
    finally:
        proc.terminate()
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
