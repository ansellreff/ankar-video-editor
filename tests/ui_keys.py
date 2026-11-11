"""UI test of the API Keys page (test server): the menu-bar button opens it, a wrong password is refused, the right
one saves a FAKE custom key that is shown only as ••••xxxx, then it is removed again. The password comes from the
environment (never written in the repo):  $env:VLOG_KEYS_PASSWORD = "…"; python -m tests.ui_keys"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import urllib.request

import websockets

from tests.ui_smoke import CDP, EDGE, OUT, TEST_URL

PORT = 9338
FAKE = "sk_fake_ui_" + "9f8e7d6c5b4a" * 4


async def wait_js(cdp, expr, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if await cdp.js(expr):
            return True
        await asyncio.sleep(0.25)
    return False


async def main():
    pw = os.environ.get("VLOG_KEYS_PASSWORD")
    assert pw, "set VLOG_KEYS_PASSWORD"
    prof = OUT / "edge-profile-keys"
    shutil.rmtree(prof, ignore_errors=True)
    proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--window-size=1400,1000", "about:blank"])
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
            for d in ("Runtime", "Page"):
                await cdp.call(f"{d}.enable")
            await cdp.call("Page.navigate", url=TEST_URL + "/")
            await asyncio.sleep(5)
            has_btn = await cdp.js("[...document.querySelectorAll('.menubar .menu > button')].map(b => b.textContent.trim()).join('|')")
            print("menu bar:", has_btn)
            ok &= has_btn.endswith("Help|API Keys")
            await cdp.call("Page.navigate", url=TEST_URL + "/keys")
            shown = await wait_js(cdp, "document.querySelectorAll('#services .card').length === 2")
            print("keys page with Claude + ElevenLabs cards:", shown)
            ok &= shown
            await cdp.shot("ui_keys_page.png")
            leak = await cdp.js("document.documentElement.outerHTML.includes('sk-ant-') && /sk-ant-[A-Za-z0-9]{20}/.test(document.documentElement.outerHTML)")
            ok &= not leak
            fill = lambda pwd: f"""(() => {{ const s = (id, v) => {{ const e = document.getElementById(id); e.value = v; }};
                s('fName', 'ui_test_key'); s('fLabel', 'UI test'); s('fValue', '{FAKE}'); s('fPass', {json.dumps(pwd)});
                document.getElementById('ok').click(); }})()"""
            await cdp.js("document.getElementById('addCustom').click()")
            await asyncio.sleep(0.3)
            await cdp.js(fill("not-the-password"))
            refused = await wait_js(cdp, "!document.getElementById('mErr').classList.contains('hidden')")
            msg = await cdp.js("document.getElementById('mErr').textContent")
            print("wrong password refused:", refused, "·", msg)
            ok &= refused and "Wrong password" in msg
            await cdp.js(fill(pw))
            saved = await wait_js(cdp, "[...document.querySelectorAll('#custom .card')].some(c => c.textContent.includes('UI test'))")
            masked = await cdp.js("document.getElementById('custom').textContent")
            print("saved + masked:", saved, "·", "••••" in masked, "· full key on page:", FAKE in await cdp.js("document.body.innerText"))
            ok &= saved and "••••" in masked and FAKE not in await cdp.js("document.body.innerText")
            await cdp.shot("ui_keys_saved.png")
            await cdp.js("[...document.querySelectorAll('#custom .card')].find(c => c.textContent.includes('UI test')).querySelector('.btn.danger').click()")
            await asyncio.sleep(0.3)
            await cdp.js(f"document.getElementById('fPass').value = {json.dumps(pw)}; document.getElementById('ok').click()")
            gone = await wait_js(cdp, "![...document.querySelectorAll('#custom .card')].some(c => c.textContent.includes('UI test'))")
            print("removed with password:", gone)
            ok &= gone
    finally:
        proc.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
