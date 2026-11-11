import sys, numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
from scipy.io import wavfile

SR = 48000
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
rng = np.random.default_rng(7)
N = int(SR * DUR)

def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], 'bandpass', fs=SR, output='sos'), x)

def lp(x, f):
    return sosfilt(butter(2, f, 'lowpass', fs=SR, output='sos'), x)

def env(n, attack, decay):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-5), 0, 1)
    return a * np.exp(-t / decay)

def click(length, decay, lo, hi, modes=(), noise_amt=1.0):
    """Noise transient through a band + a few damped resonant modes (the clock body)."""
    n = int(SR * length)
    t = np.arange(n) / SR
    x = bp(rng.standard_normal(n), lo, hi) * env(n, 0.0003, decay) * noise_amt
    for f, amp, d in modes:
        x += amp * np.sin(2 * np.pi * f * t) * env(n, 0.0005, d)
    return x

def reverb(x, seconds, wet, damp=4000):
    n = int(SR * seconds)
    ir = lp(rng.standard_normal(n), damp) * np.exp(-np.arange(n) / SR / (seconds / 5))
    ir /= np.abs(ir).sum() ** 0.5 * 6
    y = fftconvolve(x, ir)[: len(x)]
    return (1 - wet) * x + wet * y

def place(events):
    out = np.zeros(N)
    for t0, snd in events:
        i = int(t0 * SR)
        j = min(N, i + len(snd))
        out[i:j] += snd[: j - i]
    return out

def norm(x, peak=0.9):
    return x / (np.abs(x).max() + 1e-9) * peak

def bell(f0, length=2.5, decay=0.9):
    n = int(SR * length); t = np.arange(n) / SR
    partials = [(1, 1.0), (2.0, 0.5), (2.76, 0.35), (5.4, 0.2), (8.93, 0.1)]
    return sum(a * np.sin(2 * np.pi * f0 * r * t) * env(n, 0.002, decay / r ** 0.5) for r, a in partials)

TIMES = [float(i) for i in range(int(DUR))]
v = sys.argv[1]

if v == "1":   # Classic wall clock: woody tick-tock, small room
    tick = click(0.12, 0.010, 1800, 6000, [(2350, 0.25, 0.015), (3900, 0.12, 0.008)])
    tock = click(0.14, 0.013, 900, 4200, [(1450, 0.35, 0.02), (2700, 0.12, 0.01)])
    x = place([(t, tick if i % 2 == 0 else tock) for i, t in enumerate(TIMES)])
    x = reverb(x, 0.6, 0.25)

elif v == "2":  # Wristwatch / quartz: tiny, crisp, very close and dry
    tk = click(0.05, 0.0025, 4000, 12000, [(6200, 0.15, 0.003)])
    x = place([(t, tk) for t in TIMES])
    x = reverb(x, 0.15, 0.08, 9000)

elif v == "3":  # Grandfather clock: deep, slow, wooden, big hall
    tick = click(0.4, 0.03, 300, 2200, [(520, 0.8, 0.08), (1100, 0.35, 0.05), (210, 0.5, 0.12)])
    tock = click(0.4, 0.035, 250, 1800, [(430, 0.9, 0.09), (880, 0.3, 0.05), (180, 0.6, 0.14)])
    x = place([(t, tick if i % 2 == 0 else tock) for i, t in enumerate(TIMES)])
    x = reverb(x, 2.2, 0.45, 3000)

elif v == "4":  # Cinematic tension: sharp tick + sub-bass pulse, last ticks speed up
    tk = click(0.1, 0.006, 2500, 9000, [(3100, 0.2, 0.01)])
    n = int(SR * 0.6); t = np.arange(n) / SR
    sweep = 70 * np.exp(-t / 0.25) + 42           # pitch drops like a heartbeat thump
    sub = np.sin(2 * np.pi * np.cumsum(sweep) / SR) * env(n, 0.004, 0.18) * 1.6
    times = [0.0, 1.0, 1.9, 2.6, 3.1, 3.45]
    x = place([(tt, tk) for tt in times] + [(tt, sub) for tt in times[:4]])
    x = reverb(x, 1.5, 0.3, 5000)
    x *= np.where(np.arange(N) / SR > 3.6, np.exp(-(np.arange(N) / SR - 3.6) / 0.12), 1)

elif v == "5":  # Wall clock + soft chime when "5:00 PM" appears
    tick = click(0.12, 0.010, 1800, 6000, [(2350, 0.25, 0.015)])
    tock = click(0.14, 0.013, 900, 4200, [(1450, 0.35, 0.02)])
    x = place([(t, tick if i % 2 == 0 else tock) for i, t in enumerate(TIMES)])
    chime = place([(0.62, bell(1046.5) * 0.5), (0.95, bell(784.0) * 0.4)])
    x = reverb(norm(x, 0.8) + norm(chime, 0.55), 1.2, 0.3)

x = norm(x, 0.89)
st = np.stack([x, x], axis=1).astype(np.float32)
wavfile.write(sys.argv[2], SR, st)
