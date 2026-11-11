"""Print 'task' and 'tts' progress events from the server (raw socket, no buffering): python -m tests.sse_log [seconds]"""
import json
import socket
import sys
import time

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 600
s = socket.create_connection(("127.0.0.1", 8765))
s.sendall(b"GET /api/events HTTP/1.1\r\nHost: localhost\r\nAccept: text/event-stream\r\n\r\n")
s.settimeout(1.0)
buf, t0, last = b"", time.time(), None
while time.time() - t0 < secs:
    try:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    except socket.timeout:
        continue
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        line = line.strip()
        if line.startswith(b"data:"):
            try:
                m = json.loads(line[5:])
            except Exception:
                continue
            d = m.get("data") or {}
            if m["type"] == "task":
                key = (d.get("stage"), round(d.get("value") or 0, 2))
            elif m["type"] == "tts":
                key = (d.get("state"), d.get("stage"))
            else:
                continue
            if key != last:
                print(f"{time.time() - t0:6.1f}s  {m['type']:4s}  {key}", flush=True)
                last = key
