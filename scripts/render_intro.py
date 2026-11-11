"""Render the typed-text intro (black screen + keyboard SFX) to MP4 without ffmpeg.exe / libass.

Windows Smart App Control blocks the portable ffmpeg.exe, so this uses PyAV (ffmpeg libs inside the
venv) for encoding and Pillow for text. Typing times, fade, layout and styles are read from the
.ass file written by scripts/keys.py, mimicking libass: font size = line height (ascent+descent),
\\an5 + \\pos centres the full line (hidden letters included, so the layout never shifts).

usage: python scripts/render_intro.py <intro.wav> <intro.ass> <out.mp4> [fonts_dir (default library/fonts)]
"""
import re, sys
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile

wav_in, ass_in, out_mp4 = sys.argv[1:4]
FONTS = Path(sys.argv[4] if len(sys.argv) > 4 else Path(__file__).resolve().parent.parent / "library" / "fonts")
W, H, FPS, DUR = 1080, 1920, Fraction(30000, 1001), 8.0

def secs(ts):
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

# --- parse styles + events from the .ass -------------------------------------------------------
styles, events = {}, []
for line in Path(ass_in).read_text(encoding="utf-8", errors="replace").splitlines():
    if line.startswith("Style:"):
        f = [x.strip() for x in line[6:].split(",")]
        styles[f[0]] = dict(font=f[1], size=float(f[2]), bold=f[7] != "0", spacing=float(f[13]))
    elif line.startswith("Dialogue:"):
        f = line[9:].split(",", 9)
        text = f[9]
        pos = tuple(map(float, re.search(r"\\pos\(([\d.]+),([\d.]+)\)", text).groups()))
        fade = re.search(r"\\t\((\d+),(\d+),\\alpha&HFF&\)", text)
        visible_full = re.sub(r"\{[^}]*\}", "", text)          # all letters, shown + hidden
        shown = re.sub(r"\{[^}]*\}", "", text.split(r"{\alpha&HFF&}")[0])
        st = secs(f[1].strip())
        events.append(dict(st=st, en=secs(f[2].strip()), style=f[3].strip(), pos=pos, full=visible_full,
                           shown=shown, fade=(st + int(fade[1]) / 1000, st + int(fade[2]) / 1000) if fade else None))

def font_file(st):
    name = st["font"].replace(" ", "-")
    if name == "Poppins":
        name = "Poppins-Bold" if st["bold"] else "Poppins-Regular"
    return str(FONTS / f"{name}.ttf")

font_cache = {}
def get_font(style):
    if style not in font_cache:
        st = styles[style]
        probe = ImageFont.truetype(font_file(st), 1000)
        a, d = probe.getmetrics()
        px = round(st["size"] * 1000 / (a + d))                # libass: Fontsize = ascent+descent
        fnt = ImageFont.truetype(font_file(st), px)
        font_cache[style] = (fnt, st["spacing"])
    return font_cache[style]

def draw_event(img, ev, alpha):
    fnt, sp = get_font(ev["style"])
    full = ev["full"]
    adv = [fnt.getlength(full[:k]) + k * sp for k in range(len(full) + 1)]
    total = adv[-1] - sp
    asc, desc = fnt.getmetrics()
    x0 = ev["pos"][0] - total / 2
    top = ev["pos"][1] - (asc + desc) / 2
    layer = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(layer)
    for k, ch in enumerate(ev["shown"]):
        d.text((x0 + adv[k], top), ch, font=fnt, fill=255)
    white = Image.new("RGB", img.size, (255, 255, 255))
    img.paste(white, (0, 0), layer.point(lambda v: int(v * alpha)))

def frame_at(t):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    for ev in events:
        if not (ev["st"] <= t < ev["en"]):
            continue
        alpha = 1.0
        if ev["fade"]:
            a, b = ev["fade"]
            alpha = 1.0 - min(max((t - a) / (b - a), 0.0), 1.0)
        if alpha > 0:
            draw_event(img, ev, alpha)
    return img

# --- encode -------------------------------------------------------------------------------------
sr, audio = wavfile.read(wav_in)
audio = audio.astype(np.float32)
if audio.ndim == 1:
    audio = np.stack([audio, audio], 1)

out = av.open(out_mp4, "w", options={"movflags": "+faststart"})
vs = out.add_stream("libx264", rate=FPS, options={"crf": "18", "preset": "medium"})
vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
as_ = out.add_stream("aac", rate=48000, layout="stereo")
as_.bit_rate = 192000

nframes = round(DUR * FPS)
last_key, last_frame = None, None
for i in range(nframes):
    t = float(i / FPS)
    img = frame_at(t)
    key = img.tobytes()                                     # reuse identical frames (cheap)
    if key != last_key:
        last_frame, last_key = av.VideoFrame.from_image(img), key
    vf = last_frame.reformat(format="yuv420p")
    vf.pts = i
    for p in vs.encode(vf):
        out.mux(p)
for p in vs.encode():
    out.mux(p)

if sr != 48000:
    raise SystemExit(f"expected 48 kHz audio, got {sr}")
CH = 1024
planar = np.ascontiguousarray(audio.T)
for s in range(0, planar.shape[1], CH):
    af = av.AudioFrame.from_ndarray(np.ascontiguousarray(planar[:, s:s + CH]), format="fltp", layout="stereo")
    af.sample_rate, af.pts = 48000, s
    for p in as_.encode(af):
        out.mux(p)
for p in as_.encode():
    out.mux(p)
out.close()
print(f"wrote {out_mp4}: {nframes} frames @ {float(FPS):.3f} fps, {planar.shape[1]/sr:.2f} s audio, {len(events)} text events")
