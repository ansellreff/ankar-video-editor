"""UI test of the update reminder. Needs the TEST server started with a fake website:
    $env:ANKAR_SITE = "http://127.0.0.1:8799"; .\\tests\\test_server.ps1; Remove-Item Env:ANKAR_SITE
    python -m tests.ui_update
The fake site says 9.9.9 is out → red dot on Help, banner, What's new dialog with the notes + Download."""
from __future__ import annotations

import asyncio
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests.site_shots import session, size
from tests.ui_smoke import TEST_URL

LATEST = {"version": "9.9.9", "date": "2026-12-24", "download_page": "http://127.0.0.1:8799/account",
          "releases": [{"version": "9.9.9", "date": "2026-12-24", "notes": ["A shiny new feature", "Faster export"]},
                       {"version": "1.0.0", "date": "2026-11-12", "notes": ["First"]}]}


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(LATEST).encode())

    def log_message(self, *a):
        pass


async def run(cdp):
    ok = True
    await size(cdp, 1500, 950)
    await cdp.call("Page.navigate", url=TEST_URL + "/")
    for _ in range(150):
        await asyncio.sleep(0.2)
        if await cdp.js("!!window.__vs && !!document.querySelector('.tl-toolbar')"):
            break
    await cdp.js("localStorage.removeItem('vs-update-dismissed')")
    await asyncio.sleep(5)                                               # first check runs 4 s after start
    dot = await cdp.js("!!document.querySelector('.menubar .dot-new')")
    banner = await cdp.js("document.querySelector('.update-banner')?.textContent || ''")
    print("red dot on Help:", dot, "· banner:", banner.strip()[:80])
    ok &= dot and "9.9.9" in banner
    await cdp.js("window.__vs.set({dialog: 'whatsnew'})")
    await asyncio.sleep(0.6)
    txt = await cdp.js("document.querySelector('.dialog')?.textContent || ''")
    print("dialog shows notes:", "A shiny new feature" in txt, "· download button:", "Download 9.9.9" in txt)
    ok &= "A shiny new feature" in txt and "Download 9.9.9" in txt and "First public version" in txt
    await cdp.shot("ui_update_dialog.png")
    await cdp.js("window.__vs.set({dialog: null}); document.querySelector('.update-banner .btn.ghost').click()")
    await asyncio.sleep(0.4)
    hidden = await cdp.js("!document.querySelector('.update-banner')")
    print("banner can be hidden:", hidden)
    ok &= hidden
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


def main():
    srv = HTTPServer(("127.0.0.1", 8799), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    r = json.loads(urllib.request.urlopen(TEST_URL + "/api/update?force=1").read())
    assert r["site"] == "http://127.0.0.1:8799", "start the test server with ANKAR_SITE=http://127.0.0.1:8799 (see docstring)"
    print("server sees:", r["current"], "→", r["latest"], "newer:", r["newer"])
    asyncio.run(session(run))


if __name__ == "__main__":
    main()
