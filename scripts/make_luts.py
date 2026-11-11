"""Generate the built-in LUT pack (our own color math, CC0) → library/luts/*.cube (33³).
python scripts/make_luts.py   (re-runnable; overwrites only the built-in files)"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.luts import LUT_DIR, identity, write_cube  # noqa: E402

N = 33
W_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luma(x):
    return (x * W_LUMA).sum(-1, keepdims=True)


def sat(x, s):
    y = luma(x)
    return y + (x - y) * s


def contrast(x, c, pivot=0.45):
    return pivot + (x - pivot) * c


def s_curve(x, k):
    """Smooth S-curve, k=0 none … 1 strong (keeps 0 and 1)."""
    s = x * x * (3 - 2 * x)
    return x + (s - x) * k


def lift_gain(x, lift=0.0, gain=1.0):
    return lift + x * (gain - lift)


def split_tone(x, shadow, highlight, amount=1.0):
    y = luma(x)
    ws, wh = (1 - y) ** 2, y ** 2
    return x + amount * (ws * np.array(shadow, np.float32) + wh * np.array(highlight, np.float32))


def balance(x, r=0.0, g=0.0, b=0.0):
    return x * (1 + np.array([r, g, b], np.float32))


def hue_mask(x, center, width):
    """Weight 0..1 for pixels whose hue (degrees) is near `center` (weighted by saturation)."""
    mx, mn = x.max(-1), x.min(-1)
    d = mx - mn + 1e-6
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    dist = np.minimum(abs(h - center), 360 - abs(h - center))
    return (np.clip(1 - dist / width, 0, 1) * np.clip(d / (mx + 1e-6) * 1.5, 0, 1))[..., None]


def vibrance(x, v):
    mx, mn = x.max(-1, keepdims=True), x.min(-1, keepdims=True)
    s = (mx - mn) / (mx + 1e-6)
    return sat(x, 1 + v * (1 - s))


LOOKS = {}


def look(name):
    def deco(fn):
        LOOKS[name] = fn
        return fn
    return deco


@look("Teal & Orange")
def teal_orange(x):
    x = split_tone(x, (-0.06, 0.03, 0.07), (0.07, 0.02, -0.06))
    skin = hue_mask(x, 25, 35)
    cool = hue_mask(x, 200, 70) + hue_mask(x, 120, 50)
    x = x + skin * np.array([0.05, 0.01, -0.04], np.float32) + cool * np.array([-0.06, 0.02, 0.05], np.float32)
    return sat(s_curve(x, 0.35), 1.1)


@look("Warm Film")
def warm_film(x):
    x = balance(x, 0.06, 0.02, -0.07)
    x = lift_gain(x, 0.04, 0.96)
    x = s_curve(x, 0.25)
    return sat(x, 0.9)


@look("Bleach Bypass")
def bleach_bypass(x):
    y = luma(x)
    ov = np.where(y < 0.5, 2 * x * y, 1 - 2 * (1 - x) * (1 - y))
    x = x * 0.45 + ov * 0.55
    return sat(contrast(x, 1.15), 0.45)


@look("Cross Process")
def cross_process(x):
    r = s_curve(x[..., 0], 0.7)
    g = s_curve(x[..., 1], 0.35) * 1.03
    b = 0.12 + x[..., 2] * 0.72
    return sat(np.stack([r, g, b], -1), 1.08)


@look("Moody Blue")
def moody_blue(x):
    x = balance(x, -0.05, 0.0, 0.07)
    x = split_tone(x, (-0.02, 0.01, 0.06), (0.0, 0.0, 0.02))
    x = lift_gain(x, 0.03, 0.9)
    return sat(s_curve(x, 0.3), 0.75)


@look("Golden Hour")
def golden_hour(x):
    x = balance(x, 0.09, 0.04, -0.1)
    x = split_tone(x, (0.02, 0.0, -0.03), (0.08, 0.05, -0.05))
    return sat(s_curve(x, 0.2), 1.15)


@look("Night Neon")
def night_neon(x):
    mag = hue_mask(x, 300, 60)
    cy = hue_mask(x, 185, 50)
    x = x + mag * np.array([0.08, -0.04, 0.08], np.float32) + cy * np.array([-0.06, 0.04, 0.08], np.float32)
    x = split_tone(x, (0.0, -0.01, 0.07), (0.02, 0.0, 0.03))
    return sat(s_curve(x, 0.45), 1.3)


@look("Pastel Dream")
def pastel_dream(x):
    x = lift_gain(x, 0.12, 0.98)
    x = contrast(x, 0.85, 0.55)
    x = split_tone(x, (0.02, 0.0, 0.05), (0.05, 0.01, 0.03))
    return sat(x, 0.8)


@look("Matte Fade")
def matte_fade(x):
    x = lift_gain(x, 0.08, 0.92)
    return sat(s_curve(x, 0.15), 0.9)


@look("Emerald")
def emerald(x):
    gr = hue_mask(x, 120, 60)
    x = x + gr * np.array([-0.04, 0.06, 0.01], np.float32)
    x = split_tone(x, (-0.03, 0.04, 0.03), (0.02, 0.02, -0.02))
    return sat(s_curve(x, 0.3), 1.12)


@look("Sepia Warm")
def sepia_warm(x):
    y = luma(x)
    tone = np.concatenate([y * 1.07 + 0.03, y * 0.93 + 0.01, y * 0.74], -1)
    return s_curve(tone * 0.8 + x * 0.2, 0.2)


@look("Crisp Travel")
def crisp_travel(x):
    x = balance(x, 0.02, 0.01, -0.01)
    x = s_curve(x, 0.4)
    return vibrance(x, 0.35)


def main():
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    base = identity(N)
    for name, fn in LOOKS.items():
        out = np.clip(fn(base.copy()), 0, 1).astype(np.float32)
        fname = name.lower().replace(" & ", "_").replace(" ", "_") + ".cube"
        write_cube(LUT_DIR / fname, out, name)
        print("wrote", fname)
    (LUT_DIR / "README.txt").write_text(
        "Built-in looks made by scripts/make_luts.py (original color math, free to use - CC0).\n"
        "Drop any 3D .cube LUT here (e.g. from your camera maker) and it shows up under Effects > Color > LUTs.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
