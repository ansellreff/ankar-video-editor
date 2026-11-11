"""Sentence blocks on the timeline (TEST server :8766, run tests.e2e_sentences first — it leaves the project open):
blocks render inside the narration clip, the "people talking" overlay shows, dragging a block moves that sentence
(one undo step), the Inspector lists the sentences and Match to video opens with a plan.
python -m tests.ui_sentences"""
import asyncio
import json
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9351


async def mouse(cdp, kind, x, y, buttons=1, mods=0):
    await cdp.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left", buttons=buttons, clickCount=1, modifiers=mods)


async def main():
    prof = OUT / "edge-profile-sent"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1680,1000",
                             "--no-first-run", "--mute-audio", "about:blank"])
    ok = True
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
            for d in ("Runtime", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Emulation.setDeviceMetricsOverride", width=1680, height=1000, deviceScaleFactor=1, mobile=False)
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            await asyncio.sleep(5)
            await cdp.js("(() => { const {S, set} = window.__vs; set({ pps: 160 }); })()")
            await asyncio.sleep(2.5)                                       # context (talking / cuts) arrives after ~0.7 s
            await cdp.js("document.querySelector('.clip.tts').scrollIntoView({ block: 'center' })")
            await asyncio.sleep(0.4)
            info = await cdp.js("""(() => {
              const segs = [...document.querySelectorAll('.clip.tts .tseg')].map(e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, e.textContent.trim()]; });
              return { segs, talk: document.querySelectorAll('.talkband .talk').length, cuts: document.querySelectorAll('.talkband .cutmark').length,
                       ctx: window.__vs.S.narrCtx };
            })()""")
            print(f"sentence blocks: {len(info['segs'])}  talking overlay: {info['talk']}  shot marks: {info['cuts']}")
            ok &= len(info["segs"]) == 3 and info["talk"] == 2 and info["cuts"] >= 2
            await cdp.shot("ui_sentences_before.png")
            x, y, w, h, _ = info["segs"][2]
            before = await cdp.js("""(() => { const c = window.__vs.S.project.clips.find(k => k.type === 'tts');
              const l = c.tts.layout || c.tts.segs.map(s => ({ at: s.a })); return c.start - c.in + l[2].at; })()""")
            await mouse(cdp, "mouseMoved", x + w / 2, y + h / 2, 0)
            await mouse(cdp, "mousePressed", x + w / 2, y + h / 2)
            for k in range(1, 9):
                await mouse(cdp, "mouseMoved", x + w / 2 + k * 6, y + h / 2)  # 48 px at 160 px/s = 0.3 s
                await asyncio.sleep(0.03)
            await mouse(cdp, "mouseReleased", x + w / 2 + 48, y + h / 2, 0)
            await asyncio.sleep(1.5)
            after = await cdp.js("""(() => { const S = window.__vs.S, c = S.project.clips.find(k => k.type === 'tts');
              return { layout: c.tts.layout, start: c.start, in: c.in, sent: S.sent, label: S.history?.undo_label || S.history?.undo?.slice?.(-1)?.[0],
                       toasts: S.toasts.map(t => t.text), pending: S.sentPending }; })()""")
            print("toasts:", after.get("toasts"), "pending:", after.get("pending"))
            lay = after["layout"]
            print("after drag:", lay, "selected:", after["sent"], "history:", after["label"])
            shift = (after["start"] - after["in"] + lay[2]["at"]) - before if lay else 0
            print(f"sentence 3 moved by {shift:+.2f} s (dragged ≈ +0.30 s)")
            ok &= bool(lay) and after["sent"] and after["sent"]["i"] == 2 and 0.2 < shift < 0.4
            # Inspector lists the sentences
            rows = await cdp.js("document.querySelectorAll('.sent-row').length")
            print("inspector sentence rows:", rows)
            ok &= rows == 3
            # nudge with the arrow key (selected sentence)
            await cdp.call("Input.dispatchKeyEvent", type="keyDown", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
            await cdp.call("Input.dispatchKeyEvent", type="keyUp", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
            await asyncio.sleep(1.2)
            lay2 = await cdp.js("window.__vs.S.project.clips.find(k => k.type === 'tts').tts.layout")
            nudged = abs(lay2[2]["at"] - lay[2]["at"] - 0.1) < 0.02 or abs(lay2[2]["at"] - lay[2]["at"]) > 0.05
            print("nudged +0.1 s:", nudged, round(lay2[2]["at"] - lay[2]["at"], 3))
            ok &= nudged
            await cdp.js("document.querySelector('.sent-list')?.scrollIntoView({ block: 'center' })")
            await asyncio.sleep(0.3)
            await cdp.shot("ui_sentences_after.png")
            # Match to video dialog with a plan
            await cdp.js("(() => { const {S, set} = window.__vs; set({ dialog: 'match', matchClip: S.project.clips.find(k => k.type === 'tts').id }); })()")
            await asyncio.sleep(2.0)
            dlg = await cdp.js("""(() => ({ res: document.querySelector('.match-res')?.textContent?.trim(), sn: document.querySelectorAll('.match-viz .sn').length,
                                           talk: document.querySelectorAll('.match-viz .talk').length }))()""")
            print("match dialog:", dlg)
            ok &= dlg["sn"] == 3 and dlg["talk"] == 2 and (dlg["res"] or "").startswith("Fits")
            await cdp.shot("ui_sentences_match.png")
            errs = [e for e in cdp.events if e.get("method") == "Runtime.exceptionThrown"]
            for e in errs:
                print("EXC", e["params"]["exceptionDetails"].get("exception", {}).get("description"))
            ok &= not errs
    finally:
        proc.terminate()
        from app.paths import GENERATED_NARRATION                       # leave the shared narration cache as it was
        for f in GENERATED_NARRATION.glob("tts_e2e_sentences.*"):
            f.unlink(missing_ok=True)
    print("ALL PASS" if ok else "SOME FAILED")


if __name__ == "__main__":
    asyncio.run(main())
