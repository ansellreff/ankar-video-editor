"""Typewriter intro: synthesizes keystroke audio and a matching ASS file where
the text types on letter by letter (centered layout stays fixed)."""
import sys, numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
from scipy.io import wavfile

SR = 48000
DUR = 8.0
N = int(SR * DUR)
LINE1 = "October 30th 2026"
LINE2 = "05:00PM"

variant = sys.argv[1]
wav_out, ass_out = sys.argv[2], sys.argv[3]
rng = np.random.default_rng(11)

def bp(x, lo, hi, o=2): return sosfilt(butter(o, [lo, hi], 'bandpass', fs=SR, output='sos'), x)
def lp(x, f, o=2): return sosfilt(butter(o, f, 'lowpass', fs=SR, output='sos'), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, 'highpass', fs=SR, output='sos'), x)
def env(n, a, d):
    t = np.arange(n) / SR
    return np.clip(t / max(a, 1e-5), 0, 1) * np.exp(-t / d)

def strike(p):
    """One typebar hitting the platen: high click + low thud + short metallic ring."""
    n = int(SR * 0.25); t = np.arange(n) / SR
    v = rng.uniform(0.8, 1.15)
    click = bp(rng.standard_normal(n), p['click_lo'], p['click_hi']) * env(n, 0.0002, p['click_d'])
    thud = lp(rng.standard_normal(n), p['thud_f']) * env(n, 0.001, p['thud_d']) * p['thud']
    f = p['ring_f'] * rng.uniform(0.97, 1.03)
    ring = (np.sin(2*np.pi*f*t) + 0.5*np.sin(2*np.pi*f*1.53*t)) * env(n, 0.0005, p['ring_d']) * p['ring']
    # key release: a small second click shortly after
    rel = np.zeros(n); k = int(SR * rng.uniform(0.05, 0.07))
    r = bp(rng.standard_normal(n - k), p['click_lo'], p['click_hi']) * env(n - k, 0.0002, 0.003) * p['release']
    rel[k:] = r
    return v * (click + thud + ring + rel)

def space(p):
    s = strike(p); return lp(s, 2500) * 1.3

def bell(f0=2300, length=1.6):
    n = int(SR * length); t = np.arange(n) / SR
    parts = [(1, 1), (2.32, .45), (4.25, .25), (6.8, .12)]
    return sum(a*np.sin(2*np.pi*f0*r*t)*env(n, .001, .55/r**.6) for r, a in parts) * 0.6

def carriage(length=0.55, clicks=22):
    """Carriage return: fast ratchet clicks over a sliding rumble, then a clunk."""
    n = int(SR * (length + 0.3)); x = np.zeros(n)
    slide = bp(rng.standard_normal(int(SR*length)), 300, 2500) * np.linspace(0.25, 0.1, int(SR*length))
    x[:len(slide)] += slide
    for i in range(clicks):
        k = int(SR * length * (i / clicks) ** 0.85)
        c = bp(rng.standard_normal(1200), 2500, 7000) * env(1200, 0.0002, 0.002) * 0.6
        x[k:k+1200] += c
    k = int(SR * length)
    m = int(SR * 0.3)
    x[k:k+m] += lp(rng.standard_normal(m), 600) * env(m, 0.001, 0.04) * 2.0
    return x

def motor(level):
    t = np.arange(N) / SR
    hum = (np.sin(2*np.pi*60*t) + 0.5*np.sin(2*np.pi*120*t) + 0.25*np.sin(2*np.pi*180*t))
    return (hum * 0.3 + lp(rng.standard_normal(N), 400) * 0.6) * level

def reverb(x, sec, wet, damp=4500):
    n = int(SR * sec)
    ir = lp(rng.standard_normal(n), damp) * np.exp(-np.arange(n) / SR / (sec / 5))
    ir /= np.abs(ir).sum() ** 0.5 * 6
    return (1 - wet) * x + wet * fftconvolve(x, ir)[:len(x)]

# ---- variants -------------------------------------------------------------
V = {
 "1": dict(name="Classic manual", gap=0.13, jit=0.04, bell=True, cr=True,
           click_lo=1800, click_hi=7000, click_d=0.004, thud=0.9, thud_f=350, thud_d=0.02,
           ring=0.25, ring_f=2900, ring_d=0.03, release=0.35, rev=(0.5, 0.18)),
 "2": dict(name="Vintage soft", gap=0.15, jit=0.06, bell=True, cr=True,
           click_lo=900, click_hi=3500, click_d=0.006, thud=1.1, thud_f=250, thud_d=0.03,
           ring=0.12, ring_f=2100, ring_d=0.025, release=0.25, rev=(1.2, 0.38), muffle=3200),
 "3": dict(name="Electric", gap=0.10, jit=0.015, bell=False, cr=False, motor=0.015,
           click_lo=1200, click_hi=5000, click_d=0.003, thud=1.3, thud_f=300, thud_d=0.012,
           ring=0.05, ring_f=1800, ring_d=0.01, release=0.15, rev=(0.4, 0.12)),
 "4": dict(name="Fast and crisp", gap=0.075, jit=0.02, bell=False, cr=False,
           click_lo=3000, click_hi=10000, click_d=0.0025, thud=0.4, thud_f=500, thud_d=0.01,
           ring=0.1, ring_f=4200, ring_d=0.015, release=0.3, rev=(0.3, 0.1)),
 "5": dict(name="Cinematic", gap=0.15, jit=0.03, bell=True, cr=True, boom=True,
           click_lo=1500, click_hi=6500, click_d=0.005, thud=1.4, thud_f=280, thud_d=0.035,
           ring=0.3, ring_f=2600, ring_d=0.04, release=0.3, rev=(1.8, 0.35)),
}[variant]

# ---- schedule -------------------------------------------------------------
t = 0.9
l1_times = []
for ch in LINE1:
    l1_times.append(t)
    t += V['gap'] + rng.uniform(-V['jit'], V['jit']) + (0.08 if ch == " " else 0)
t += 0.25
bell_t = t if V['bell'] else None
cr_t = t + 0.15 if V['cr'] else None
t += 1.0 if V['cr'] else 0.55
l2_times = []
for ch in LINE2:
    l2_times.append(t)
    t += V['gap'] * 1.25 + rng.uniform(-V['jit'], V['jit'])
last = l2_times[-1]
FADE_START = min(max(6.4, last + 1.0), 6.9)
FADE_END = FADE_START + 0.6

# ---- audio ----------------------------------------------------------------
x = np.zeros(N)
def put(t0, s, g=1.0):
    i = int(t0 * SR); j = min(N, i + len(s)); x[i:j] += g * s[:j-i]
for ch, tt in zip(LINE1, l1_times): put(tt, space(V) if ch == " " else strike(V))
for ch, tt in zip(LINE2, l2_times): put(tt, strike(V))
if bell_t: put(bell_t, bell(), 0.4 if variant != "2" else 0.3)
if cr_t: put(cr_t, carriage(), 0.55)
if V.get('boom'):
    n = int(SR*1.6); tb = np.arange(n)/SR
    boom = np.sin(2*np.pi*np.cumsum(55*np.exp(-tb/0.4)+38)/SR) * env(n, 0.005, 0.5) * 1.6
    put(last + 0.02, boom)
if V.get('muffle'): x = lp(x, V['muffle'])
x = reverb(x, *V['rev'])
if V.get('motor'):
    m = motor(V['motor']); fade = np.clip((np.arange(N)/SR - 0.3)/0.4, 0, 1) * np.clip((7.6 - np.arange(N)/SR)/0.5, 0, 1)
    x += m * fade
x = hp(x, 40)
x = x / np.abs(x).max() * 0.89
wavfile.write(wav_out, SR, np.stack([x, x], 1).astype(np.float32))

# ---- ASS (type-on, layout fixed) --------------------------------------------
def ts(s):
    h = int(s // 3600); m = int(s % 3600 // 60); sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"
HIDE = r"{\alpha&HFF&}"
def fade_tag(start, end):
    # visible part fades out during FADE_START..FADE_END
    if end <= FADE_START: return ""
    a0 = max(0, int((FADE_START - start) * 1000)); a1 = int((FADE_END - start) * 1000)
    return rf"{{\t({a0},{a1},\alpha&HFF&)}}"
hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Date,Poppins Medium,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,0,0,5,0,0,0,1
Style: Time,Poppins,150,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,4,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
lines = []
def typed(text, times, style, pos):
    for k in range(len(text)):
        start = times[k]
        end = times[k+1] if k + 1 < len(text) else FADE_END
        shown, hidden = text[:k+1], text[k+1:]
        body = shown + (HIDE + hidden if hidden else "")
        lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},{style},,0,0,0,,{{\\pos({pos})}}" + fade_tag(start, end) + body)
typed(LINE1, l1_times, "Date", "540,880")
typed(LINE2, l2_times, "Time", "540,1020")
open(ass_out, "w").write(hdr + "\n".join(lines) + "\n")
print(f"{variant} {V['name']}: line1 {l1_times[0]:.2f}-{l1_times[-1]:.2f}, line2 {l2_times[0]:.2f}-{last:.2f}")
