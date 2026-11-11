"""Typing SFX from REAL recorded keystrokes, synced to letter-appearance times.

Each letter's keystroke is aligned so its click (detected onset, not the file start) lands on the first
video frame that shows the letter. Samples are level-matched, given small natural velocity variation,
never repeated back-to-back, then the whole track is set to a soft target loudness.

CLI:     python scripts/keys_real.py <pack> <intro.ass> <out.wav> [--lufs -28.5] [--crisp]
Module:  make_track(letters=[(t, ch), ...], pack="slim") -> float32 (n, 2) at 48 kHz   (used by app/generators.py)
packs (sources + licenses in library/sfx/keyboard/CREDITS.md):
  slim    Cherry KC 1000 slim office keyboard (Unicae Games, CC0)
  mac     Apple scissor keys (eklee / qubodup, CC-BY 3.0, credit required)
  laptop  laptop keys sliced from a typing take (johndekale, CC0)
"""
import argparse
import re
from functools import lru_cache
from pathlib import Path

import av
import numpy as np
import pyloudnorm as pyln
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 48000
FPS = 30000 / 1001
ROOT = Path(__file__).resolve().parent.parent / "library" / "sfx" / "keyboard"
PACK_INFO = {
    "slim": {"name": "Slim keyboard (Cherry KC 1000)", "license": "CC0"},
    "slim_crisp": {"name": "Slim keyboard, crisp", "license": "CC0"},
    "mac": {"name": "Mac scissor keys", "license": "CC-BY 3.0 (credit: eklee & qubodup)"},
    "laptop": {"name": "Laptop keys", "license": "CC0"},
}


def load(p):
    c = av.open(str(p))
    rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
    out = []
    for fr in c.decode(audio=0):
        out += [o.to_ndarray().reshape(-1) for o in rs.resample(fr)]
    out += [o.to_ndarray().reshape(-1) for o in rs.resample(None)]
    c.close()
    return np.concatenate(out).astype(np.float64)


def onset(x):
    """Index of the first sharp transient (2 ms envelope, > -30 dB of peak, +8 dB jump)."""
    hop = int(SR * 0.002)
    e = np.array([np.abs(x[i:i + hop]).max() for i in range(0, len(x) - hop, hop)]) + 1e-12
    db = 20 * np.log10(e / e.max())
    for i in range(1, len(db)):
        if db[i] > -30 and db[i] - db[i - 1] > 8:
            seg = np.abs(x[(i - 1) * hop:(i + 1) * hop])
            return (i - 1) * hop + int(np.argmax(seg > seg.max() * 0.2))
    return int(np.argmax(np.abs(x) > np.abs(x).max() * 0.2))


def trim(x, pre=0.004, length=0.26):
    k = onset(x)
    s = max(0, k - int(pre * SR))
    y = x[s:s + int(length * SR)].copy()
    fade = int(0.03 * SR)
    if len(y) > fade:
        y[-fade:] *= np.linspace(1, 0, fade)
    return y, k - s


def keys_from_take(path, min_gap=0.11, take=0.15):
    """Slice isolated keystrokes out of a continuous typing recording."""
    x = load(path)
    hop = int(SR * 0.002)
    e = np.array([np.abs(x[i:i + hop]).max() for i in range(0, len(x) - hop, hop)]) + 1e-12
    db = 20 * np.log10(e / e.max())
    hits = [i * hop for i in range(1, len(db)) if db[i] > -26 and db[i] - db[i - 1] > 8]
    hits = [h for j, h in enumerate(hits) if (j == 0 or h - hits[j - 1] > 0.05 * SR)]
    out = []
    for j, h in enumerate(hits):
        prev_ok = j == 0 or h - hits[j - 1] > min_gap * SR
        next_ok = j == len(hits) - 1 or hits[j + 1] - h > min_gap * SR
        if prev_ok and next_ok:
            out.append(x[max(0, h - int(0.01 * SR)):h + int(take * SR)])
    return out


PACKS = {
    "slim": dict(files=[ROOT / "unicae/x/Single Keys" / f"keypress-{n:03d}.wav"
                        for n in range(1, 33) if n not in (9, 10, 12, 14, 15, 20, 23, 27, 31)]),
    "mac": dict(files=lambda: sorted((ROOT / "eklee/x/eklee-KeyPresses-cc0-opengameart/flac48000").glob("eklee-KeyPressMac*.flac"))),
    "laptop": dict(take=ROOT / "laptop/typing.ogg"),
}


@lru_cache(maxsize=8)
def load_samples(pack: str, crisp: bool):
    P = PACKS[pack]
    files = P.get("files")
    if callable(files):
        files = files()
    raw = [load(f) for f in files] if files is not None else keys_from_take(P["take"])
    hp_sos = butter(2, 250 if crisp else 90, "highpass", fs=SR, output="sos")
    shelf_sos = butter(1, 5000, "highpass", fs=SR, output="sos")
    samples = []
    for x in raw:
        y, off = trim(x, length=0.18 if crisp else 0.26)
        y = sosfilt(hp_sos, y)
        if crisp:
            y = y + 0.4 * sosfilt(shelf_sos, y)           # ~+3 dB air above 5 kHz
        ref = np.sqrt(np.mean(y[off:off + int(0.025 * SR)] ** 2)) + 1e-12   # level-match on the click itself
        samples.append((y / ref, off))
    return samples


def make_track(letters, pack="slim", crisp=False, lufs=-28.5, seed=7, dur=None, fps=FPS):
    """letters: [(time_s, char)] in appearance order. Returns float32 (n, 2) stereo at 48 kHz."""
    if pack == "slim_crisp":
        pack, crisp = "slim", True
    rng = np.random.default_rng(seed)
    samples = load_samples(pack, crisp)
    dur = dur or (max(t for t, _ in letters) + 1.0)
    out = np.zeros(int(SR * dur) + SR)
    last = -1
    # spaces get the lowest-pitched (thockiest) samples, like a real spacebar
    cents = [(np.abs(np.fft.rfft(s)) * np.fft.rfftfreq(len(s), 1 / SR)).sum() / np.abs(np.fft.rfft(s)).sum() for s, _ in samples]
    low_idx = list(np.argsort(cents)[:max(2, len(samples) // 5)])
    for t, ch in letters:
        frame_t = np.ceil(t * fps - 1e-6) / fps                # first frame that shows this letter
        pool = low_idx if ch == " " else [i for i in range(len(samples)) if i not in low_idx or len(samples) < 6]
        choices = [i for i in pool if i != last] or pool
        i = int(rng.choice(choices)); last = i
        s, off = samples[i]
        vel = 10 ** (rng.uniform(-2.0, 0.5) / 20) * (1.15 if ch == " " else 1.0)
        k = int(frame_t * SR) - off
        out[max(0, k):k + len(s)] += (s * vel)[max(0, -k):]
    out = out[:int(SR * dur)]
    meter = pyln.Meter(SR)
    loud = meter.integrated_loudness(out)
    out *= 10 ** ((lufs - loud) / 20)
    peak = np.abs(out).max()
    if peak > 0.708:                                           # keep peaks <= -3 dBFS
        out *= 0.708 / peak
    return np.stack([out, out], 1).astype(np.float32)


def letters_from_ass(path):
    def secs(ts):
        h, m, s = ts.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)
    letters = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Dialogue:"):
            f = line[9:].split(",", 9)
            shown = re.sub(r"\{[^}]*\}", "", f[9].split(r"{\alpha&HFF&}")[0])
            letters.append((secs(f[1].strip()), shown[-1]))
    return letters


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pack"); ap.add_argument("ass"); ap.add_argument("out")
    ap.add_argument("--lufs", type=float, default=-28.5)   # soft: clicks clearly audible, never loud
    ap.add_argument("--crisp", action="store_true", help="tighten: low-cut 250 Hz, gentle 5 kHz+ lift, shorter tails")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    letters = letters_from_ass(a.ass)
    track = make_track(letters, a.pack, a.crisp, a.lufs, a.seed, dur=8.0)
    wavfile.write(a.out, SR, track)
    meter = pyln.Meter(SR)
    print(f"{a.pack}: {len(load_samples(a.pack, a.crisp))} usable keystrokes")
    print(f"wrote {a.out}: {len(letters)} keystrokes, {meter.integrated_loudness(track[:, 0].astype(np.float64)):.1f} LUFS, "
          f"peak {20*np.log10(np.abs(track).max()):.1f} dBFS")
