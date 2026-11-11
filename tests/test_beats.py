import numpy as np

from app import beats


def click_track(bpm=124.0, secs=30.0, sr=48000, offset=0.37):
    x = np.zeros(int(sr * secs), np.float32)
    rng = np.random.default_rng(3)
    x += 0.01 * rng.standard_normal(len(x)).astype(np.float32)
    period = 60.0 / bpm
    t = offset
    k = 0
    while t < secs - 0.1:
        i = int(t * sr)
        n = int(0.03 * sr)
        amp = 1.0 if k % 4 == 0 else 0.6                         # accented downbeat
        x[i:i + n] += amp * np.sin(2 * np.pi * 1800 * np.arange(n) / sr) * np.exp(-np.arange(n) / (0.006 * sr))
        t += period
        k += 1
    return x


def test_tempo_and_beat_times():
    bpm, off = 124.0, 0.37
    r = beats.analyze(click_track(bpm, offset=off), 48000)
    assert abs(r["bpm"] - bpm) < 1.0
    period = 60 / bpm
    inner = [t for t in r["beats"] if 2.0 < t < 28.0]
    errs = [abs(((t - off) / period - round((t - off) / period)) * period) for t in inner]
    assert np.median(errs) < 0.02
    assert len(inner) > 40


def test_downbeats_every_fourth():
    r = beats.analyze(click_track(100.0, offset=0.5), 48000)
    d = np.diff(r["downbeats"])
    assert np.allclose(np.median(d), 4 * 60 / 100.0, atol=0.05)
