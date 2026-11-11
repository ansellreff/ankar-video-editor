"""Electric-typewriter / mechanical-keyboard intro: keystroke audio + matching
type-on ASS subtitles (centered layout stays fixed while typing)."""
import sys, numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
from scipy.io import wavfile

SR = 48000; DUR = 8.0; N = int(SR * DUR)
LINE1 = "Friday, October 30th 2026"
LINE2 = "05:00 PM"
variant, wav_out, ass_out = sys.argv[1], sys.argv[2], sys.argv[3]
rng = np.random.default_rng(23)

def bp(x, lo, hi, o=2): return sosfilt(butter(o, [lo, hi], 'bandpass', fs=SR, output='sos'), x)
def lp(x, f, o=2): return sosfilt(butter(o, f, 'lowpass', fs=SR, output='sos'), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, 'highpass', fs=SR, output='sos'), x)
def env(n, a, d):
    t = np.arange(n) / SR
    return np.clip(t / max(a, 1e-5), 0, 1) * np.exp(-t / d)
def tone(n, f, d, a=0.0005):
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * f * t) * env(n, a, d)
def noise(n, lo, hi, d, a=0.0002):
    return bp(rng.standard_normal(n), lo, hi) * env(n, a, d)
def at(buf, k, snd, g=1.0):
    j = min(len(buf), k + len(snd)); buf[k:j] += g * snd[:j - k]

L = int(SR * 0.3)

# --- building blocks ---------------------------------------------------------
def electric_thunk(body=1.0):
    """IBM-style electric typewriter strike (the sound of preview #3)."""
    x = noise(L, 1200, 5000, 0.003) + lp(rng.standard_normal(L), 300) * env(L, 0.001, 0.012) * 1.3 * body
    x += (tone(L, 1800, 0.01) + 0.5 * tone(L, 2750, 0.01)) * 0.05
    return x

def red_switch(deep=False):
    """Linear switch: no click, just keycap bottoming out on the plate + softer top-out."""
    x = np.zeros(L)
    if deep:   # lubed / foam-dampened 'thock'
        down = noise(L, 300, 1600, 0.007) * 1.2 + tone(L, 230 * rng.uniform(.95, 1.05), 0.03) * 0.55 + tone(L, 520, 0.012) * 0.25
        up = noise(L, 500, 2200, 0.004) * 0.35
    else:      # standard red: brighter 'clack'
        down = noise(L, 700, 4500, 0.005) * 1.1 + tone(L, 380 * rng.uniform(.95, 1.05), 0.018) * 0.4 + tone(L, 1350, 0.008) * 0.2
        up = noise(L, 1500, 6000, 0.003) * 0.4
    at(x, 0, down); at(x, int(SR * rng.uniform(0.07, 0.10)), up)
    return x

def blue_switch():
    """Clicky switch: sharp click-jacket snap, bottom-out a few ms later, click again on release."""
    x = np.zeros(L)
    snap = noise(L, 3500, 11000, 0.0012) * 1.3 + tone(L, 5200 * rng.uniform(.97, 1.03), 0.004) * 0.25
    bottom = noise(L, 700, 4000, 0.004) * 0.7 + tone(L, 400, 0.015) * 0.3
    rel_click = noise(L, 3000, 9000, 0.001) * 0.6
    at(x, 0, snap); at(x, int(SR * 0.006), bottom)
    at(x, int(SR * rng.uniform(0.07, 0.095)), rel_click)
    return x

def brown_switch():
    """Tactile switch: soft bump (no click) as the stem passes the leaf, then bottom-out, faint bump on release."""
    x = np.zeros(L)
    bump = noise(L, 1800, 6000, 0.0015) * 0.45 + tone(L, 2400 * rng.uniform(.95, 1.05), 0.003) * 0.08
    bottom = noise(L, 600, 3800, 0.005) * 0.95 + tone(L, 360 * rng.uniform(.95, 1.05), 0.018) * 0.38 + tone(L, 1200, 0.007) * 0.15
    up_bump = noise(L, 1500, 5000, 0.0012) * 0.2
    top_out = noise(L, 1200, 5000, 0.003) * 0.3
    k = int(SR * rng.uniform(0.008, 0.013))
    r = int(SR * rng.uniform(0.07, 0.10))
    at(x, 0, bump); at(x, k, bottom); at(x, r, up_bump); at(x, r + int(SR * 0.012), top_out)
    return x

def classic_key():
    """Classic office membrane / rubber-dome keyboard: mushy press, plastic clack, hollow case resonance."""
    x = np.zeros(L)
    mush = noise(L, 200, 1400, 0.010, a=0.002) * 0.7
    clack = noise(L, 900, 3200, 0.006) * 0.9
    body = tone(L, 780 * rng.uniform(.94, 1.06), 0.022) * 0.22 + tone(L, 1650 * rng.uniform(.95, 1.05), 0.010) * 0.08
    release = noise(L, 700, 2600, 0.006, a=0.0015) * 0.35 + tone(L, 820, 0.012) * 0.07
    at(x, 0, mush); at(x, int(SR * 0.003), clack + body)
    at(x, int(SR * rng.uniform(0.08, 0.12)), release)
    return x

def spacebar(kind):
    """Longer key with stabilizer rattle."""
    x = np.zeros(L)
    if kind == "electric":
        return electric_thunk(1.4) * 1.1
    if kind == "classic":     # big hollow bar, loud wire rattle
        base = noise(L, 180, 1300, 0.014, a=0.002) * 1.1 + noise(L, 700, 2600, 0.008) * 0.8 + tone(L, 520, 0.03) * 0.25
        rattle = noise(L, 1200, 3500, 0.002) * 0.5
        at(x, 0, base); at(x, int(SR * 0.005), rattle); at(x, int(SR * 0.013), rattle * 0.7); at(x, int(SR * 0.022), rattle * 0.4)
        at(x, int(SR * 0.12), noise(L, 500, 2400, 0.007) * 0.45 + rattle * 0.3)
        return x
    base = noise(L, 250, 1800, 0.012) * 1.1 + tone(L, 190, 0.035) * 0.5
    rattle = noise(L, 900, 2500, 0.002) * 0.35
    at(x, 0, base); at(x, int(SR * 0.004), rattle); at(x, int(SR * 0.011), rattle * 0.6)
    if kind == "blue":
        at(x, 0, noise(L, 3500, 10000, 0.0012) * 0.8)
    if kind == "brown":
        at(x, 0, noise(L, 1800, 6000, 0.0015) * 0.35)
    at(x, int(SR * 0.1), noise(L, 600, 3000, 0.005) * 0.3)
    return x

def motor(level):
    t = np.arange(N) / SR
    hum = np.sin(2*np.pi*60*t) + 0.5*np.sin(2*np.pi*120*t) + 0.25*np.sin(2*np.pi*180*t)
    return (hum * 0.3 + lp(rng.standard_normal(N), 400) * 0.6) * level

def reverb(x, sec, wet, damp=5000):
    n = int(SR * sec)
    ir = lp(rng.standard_normal(n), damp) * np.exp(-np.arange(n) / SR / (sec / 5))
    ir /= np.abs(ir).sum() ** 0.5 * 6
    return (1 - wet) * x + wet * fftconvolve(x, ir)[:len(x)]

V = {
 "1": dict(name="Electric (refined)", key=lambda: electric_thunk(1.0), space="electric",
           gap=0.10, jit=0.015, motor=0.012, rev=(0.4, 0.12)),
 "2": dict(name="Red switch", key=lambda: red_switch(False), space="red",
           gap=0.095, jit=0.03, motor=0, rev=(0.35, 0.1)),
 "3": dict(name="Red switch, deep thock", key=lambda: red_switch(True), space="red",
           gap=0.10, jit=0.03, motor=0, rev=(0.45, 0.14)),
 "4": dict(name="Blue switch", key=blue_switch, space="blue",
           gap=0.095, jit=0.03, motor=0, rev=(0.35, 0.1)),
 "5": dict(name="Electric + blue click", key=lambda: electric_thunk(0.9) * 0.9 + blue_switch() * 0.7, space="electric",
           gap=0.10, jit=0.02, motor=0.012, rev=(0.4, 0.12)),
 "6": dict(name="Brown switch", key=brown_switch, space="brown",
           gap=0.095, jit=0.03, motor=0, rev=(0.35, 0.1)),
 "7": dict(name="Classic office keyboard", key=classic_key, space="classic",
           gap=0.095, jit=0.03, motor=0, rev=(0.4, 0.14)),
}[variant]

# --- schedule ----------------------------------------------------------------
t = 0.9; l1 = []
for ch in LINE1:
    l1.append(t)
    t += V['gap'] + rng.uniform(-V['jit'], V['jit']) + (0.07 if ch in " ," else 0)
t += 0.75; l2 = []
for ch in LINE2:
    l2.append(t)
    t += V['gap'] * 1.3 + rng.uniform(-V['jit'], V['jit']) + (0.06 if ch == " " else 0)
last = l2[-1]
FADE_START = min(max(6.4, last + 1.0), 6.9); FADE_END = FADE_START + 0.6

# --- audio -------------------------------------------------------------------
x = np.zeros(N)
for ch, tt in list(zip(LINE1, l1)) + list(zip(LINE2, l2)):
    s = spacebar(V['space']) if ch == " " else V['key']()
    at(x, int(tt * SR), s * rng.uniform(0.85, 1.1))
x = reverb(x, *V['rev'])
if V['motor']:
    tt = np.arange(N) / SR
    x += motor(V['motor']) * np.clip((tt - 0.3) / 0.4, 0, 1) * np.clip((7.6 - tt) / 0.5, 0, 1)
x = hp(x, 40); x = x / np.abs(x).max() * 0.89
wavfile.write(wav_out, SR, np.stack([x, x], 1).astype(np.float32))

# --- ASS ---------------------------------------------------------------------
def ts(s): return f"{int(s//3600)}:{int(s%3600//60):02d}:{s%60:05.2f}"
HIDE = r"{\alpha&HFF&}"
def fade_tag(st, en):
    if en <= FADE_START: return ""
    return rf"{{\t({max(0,int((FADE_START-st)*1000))},{int((FADE_END-st)*1000)},\alpha&HFF&)}}"
hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Date,Poppins Medium,112,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,0,0,0,1
Style: Time,Poppins,150,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,4,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
out = []
def typed(text, times, style, pos):
    for k in range(len(text)):
        st = times[k]; en = times[k+1] if k + 1 < len(text) else FADE_END
        hidden = text[k+1:]
        out.append(f"Dialogue: 0,{ts(st)},{ts(en)},{style},,0,0,0,,{{\\pos({pos})}}{fade_tag(st,en)}{text[:k+1]}" + (HIDE + hidden if hidden else ""))
typed(LINE1, l1, "Date", "540,860")
typed(LINE2, l2, "Time", "540,1040")
open(ass_out, "w").write(hdr + "\n".join(out) + "\n")
print(f"{variant} {V['name']}: line1 {l1[0]:.2f}-{l1[-1]:.2f}, line2 {l2[0]:.2f}-{last:.2f}, fade {FADE_START:.2f}")
