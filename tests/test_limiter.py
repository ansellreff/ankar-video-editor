import numpy as np
import pyloudnorm as pyln

from app.render.audio import CEILING, SR, limit


def program(seconds=20, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = 0.08 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t))
    x += 0.01 * rng.standard_normal(len(t))
    for s in (3.0, 9.5, 15.2):                     # a few short loud bangs (like a drumroll crash or a scream)
        i = int(s * SR)
        x[i:i + 2400] += 0.9 * np.sin(2 * np.pi * 900 * t[:2400]) * np.exp(-np.arange(2400) / 600)
    return np.stack([x, x * 0.95]).astype(np.float32)


def test_peaks_held_and_body_untouched():
    x = program() * 4.0                            # pushed so peaks are way over the ceiling
    y = limit(x)
    assert np.abs(y).max() <= CEILING + 1e-6
    quiet = slice(int(5 * SR), int(8 * SR))       # far from any bang: gain must be ~1 (no pumping)
    assert np.allclose(y[:, quiet], x[:, quiet], atol=1e-4)


def test_reaches_target_loudness_through_mix_path():
    meter = pyln.Meter(SR)
    x = program()
    target = -14.0
    loud = meter.integrated_loudness(x.T.astype(np.float64))
    out = x
    for _ in range(2):
        out = limit(out * 10 ** ((target - loud) / 20))
        loud = meter.integrated_loudness(out.T.astype(np.float64))
    assert abs(loud - target) < 0.5
    assert np.abs(out).max() <= CEILING + 1e-6
