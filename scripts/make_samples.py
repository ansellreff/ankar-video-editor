"""Synthetic test clips (phone-like 1440x2560, 29.97 fps, timecode + tone) → library/samples/."""
import sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.colors import rgb_to_yuv709, x264_options  # noqa: E402

OUT = ROOT / "library" / "samples"
FONT = ROOT / "library" / "fonts" / "Poppins-Bold.ttf"
W, H, FPS, SR = 1440, 2560, Fraction(30000, 1001), 48000
CLIPS = [("sample_A_street_night.mp4", 6.0, (30, 60, 140), 330.0, "A  NIGHT STREET"),
         ("sample_B_bikes_morning.mp4", 6.0, (230, 140, 40), 440.0, "B  MORNING BIKES"),
         ("sample_C_theme_park.mp4", 5.0, (40, 170, 110), 550.0, "C  THEME PARK")]


def make(name, dur, rgb, freq, label):
    OUT.mkdir(parents=True, exist_ok=True)
    out = av.open(str(OUT / name), "w")
    vs = out.add_stream("libx264", rate=FPS, options=x264_options(crf="23", preset="veryfast"))
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    as_ = out.add_stream("aac", rate=SR, layout="stereo")
    big, small = ImageFont.truetype(str(FONT), 230), ImageFont.truetype(str(FONT), 90)
    yy, xx = np.mgrid[0:H, 0:W]
    base = np.zeros((H, W, 3), np.float32)
    for i in range(3):
        base[..., i] = rgb[i] * (0.55 + 0.45 * yy / H)
    n = int(round(dur * FPS))
    for i in range(n):
        t = float(i / FPS)
        img = base.copy()
        band = ((xx + int(t * 300)) // 180) % 2 == 0                # moving diagonal-ish bars
        img[band] *= 0.8
        im = Image.fromarray(img.clip(0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im)
        d.text((W / 2, H * 0.42), label, font=small, fill="white", anchor="mm")
        d.text((W / 2, H * 0.52), f"{t:05.2f}s", font=big, fill="white", anchor="mm")
        d.ellipse((W / 2 - 60 + 400 * np.sin(t * 2), H * 0.66 - 60, W / 2 + 60 + 400 * np.sin(t * 2), H * 0.66 + 60), fill="white")
        f = rgb_to_yuv709(np.asarray(im))
        f.pts = i
        for p in vs.encode(f):
            out.mux(p)
    for p in vs.encode():
        out.mux(p)
    tt = np.arange(int(dur * SR)) / SR
    tone = (0.15 * np.sin(2 * np.pi * freq * tt) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.5 * tt))).astype(np.float32)
    pl = np.stack([tone, tone])
    for s in range(0, pl.shape[1], 1024):
        af = av.AudioFrame.from_ndarray(np.ascontiguousarray(pl[:, s:s + 1024]), format="fltp", layout="stereo")
        af.sample_rate, af.pts = SR, s
        for p in as_.encode(af):
            out.mux(p)
    for p in as_.encode():
        out.mux(p)
    out.close()
    print("wrote", OUT / name)


if __name__ == "__main__":
    for c in CLIPS:
        make(*c)
