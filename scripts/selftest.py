"""Quick check after Setup: are the parts AnKar Video Editor needs working on this PC?
python -m scripts.selftest   (exit code 1 only when something essential is missing)"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ok, bad, warn = [], [], []

    def need(label, fn, essential=True):
        try:
            r = fn()
            ok.append(label + (f" ({r})" if isinstance(r, str) and r else ""))
        except Exception as e:  # noqa: BLE001
            (bad if essential else warn).append(f"{label}: {type(e).__name__}: {str(e)[:160]}")

    need(f"Python {sys.version.split()[0]}", lambda: None if sys.version_info[:2] == (3, 12) else (_ for _ in ()).throw(RuntimeError("needs 3.12")))
    for mod in ("fastapi", "uvicorn", "numpy", "scipy", "PIL", "av", "moderngl", "pyloudnorm", "watchfiles", "audiotsm",
                "cryptography", "anthropic", "yt_dlp"):
        need(f"package {mod}", lambda m=mod: getattr(importlib.import_module(m), "__version__", "") or "")
    need("subtitles engine (pywhispercpp)", lambda: importlib.import_module("pywhispercpp.model") and "", essential=False)

    def gpu():
        import moderngl
        ctx = moderngl.create_standalone_context(require=330)
        name = ctx.info.get("GL_RENDERER", "?")
        ctx.release()
        return name
    need("graphics (OpenGL 3.3 for preview-matching export)", gpu, essential=False)

    def video():
        import av
        import numpy as np
        p = Path(tempfile.mkdtemp(dir=ROOT / "cache")) / "t.mp4"
        with av.open(str(p), "w") as out:
            s = out.add_stream("libx264", rate=30)
            s.width, s.height, s.pix_fmt = 64, 64, "yuv420p"
            for i in range(5):
                f = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i * 40, np.uint8), format="rgb24")
                for pkt in s.encode(f):
                    out.mux(pkt)
            for pkt in s.encode():
                out.mux(pkt)
        with av.open(str(p)) as inp:
            n = sum(1 for _ in inp.decode(video=0))
        p.unlink()
        p.parent.rmdir()
        if n != 5:
            raise RuntimeError(f"read back {n} frames")
        return "H.264 encode + decode"
    (ROOT / "cache").mkdir(exist_ok=True)
    need("video export", video)

    model = ROOT / "models" / "ggml-medium-q5_0.bin"
    need("subtitle model", lambda: None if model.exists() and model.stat().st_size > 500e6 else (_ for _ in ()).throw(FileNotFoundError(str(model))), essential=False)

    def server():
        importlib.import_module("app.server")
        return ""
    need("AnKar Video Editor itself", server)

    print()
    for x in ok:
        print("  OK    ", x)
    for x in warn:
        print("  NOTE  ", x)
    for x in bad:
        print("  ERROR ", x)
    if any(w.startswith("graphics") for w in warn):
        print("\n  Your graphics driver doesn't offer OpenGL 3.3, so exporting may fail. Update the graphics driver"
              " (Windows Update or your PC maker's site).")
    print()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
