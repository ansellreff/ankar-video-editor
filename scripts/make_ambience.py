"""Noise beds for Voice effects ▸ Noise → library/ambience/<id>.mp3 (+ ambience.json).

Realistic beds are generated ONCE with the ElevenLabs Sound Effects API (loopable, 22 s) — the first one is generated
alone to measure its credit cost, then the rest only within --cap. Free beds are made locally: room tone and keyboard
typing (from the CC0 "Keyboard Soundpack #1" human typing recordings already in library/sfx/keyboard/unicae).
Your own ambience files (mp3/wav/m4a/ogg) dropped into library/ambience/ show up too.
python scripts/make_ambience.py [--cap 3500] [--only id,id]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, resample_poly, sosfilt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402
from app.tts import elevenlabs as el  # noqa: E402
from app.tts.manager import wav_to_mp3  # noqa: E402

OUT = ROOT / "library" / "ambience"
SR = 48000
BEDS = {   # id: (name, prompt)  — all "no music, no speech you can understand"
    "cafe": ("Café", "Seamless loop: busy cafe ambience, soft indistinct chatter, cups and plates clinking, espresso machine in the distance, no music, no clear words"),
    "city_street": ("City street", "Seamless loop: city street ambience, steady distant traffic, cars passing, footsteps on pavement, no horns, no music"),
    "night_market": ("Night market", "Seamless loop: busy Asian night market crowd, lively indistinct chatter, food sizzling on grills, vendors far away, no music, no clear words"),
    "theme_park": ("Theme park", "Seamless loop: amusement park ambience, distant crowd bustle, faint roller coaster rumble and far-away happy screams, no music"),
    "rain": ("Light rain", "Seamless loop: steady light rain falling on leaves and pavement, gentle and even, no thunder"),
    "park_birds": ("Park & birds", "Seamless loop: peaceful park ambience, birds singing in trees, light breeze in leaves, distant children playing"),
    "wind": ("Wind outdoors", "Seamless loop: steady gentle wind outdoors in an open field, soft gusts, no other sounds"),
    "station": ("Train station", "Seamless loop: train station hall ambience, crowd footsteps and murmur, low train hum, unintelligible distant announcements, no music"),
}


def sound_generation(key, text, seconds=22.0) -> bytes:
    return el._req("POST", "/sound-generation?output_format=mp3_44100_128", key,
                   {"text": text, "duration_seconds": seconds, "loop": True, "prompt_influence": 0.5},
                   accept="audio/mpeg", timeout=300)


def room_tone(seconds=20.0):
    rng = np.random.default_rng(7)
    n = int(SR * seconds)
    w = rng.standard_normal((2, n)).astype(np.float32)
    pink = np.cumsum(w, axis=1)                                  # brown-ish, then shape
    pink -= sosfilt(butter(1, 20 / (SR / 2), "low", output="sos"), pink, axis=1)
    pink = sosfilt(butter(2, 1800 / (SR / 2), "low", output="sos"), pink, axis=1)
    pink /= np.abs(pink).max() + 1e-9
    return (pink * 0.25).astype(np.float32)


def keyboard_bed(seconds=24.0):
    src = sorted((ROOT / "library/sfx/keyboard/unicae/x/Human Typing").glob("*.wav"))
    parts, total = [], 0
    for f in src:
        sr, x = wavfile.read(f)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        x = x.mean(axis=1) if x.ndim > 1 else x
        if sr != SR:
            x = resample_poly(x, SR // 100, sr // 100) if sr % 100 == 0 else x
        parts += [x, np.zeros(int(SR * 0.6), np.float32)]
        total += len(x) + int(SR * 0.6)
        if total > SR * seconds:
            break
    y = np.concatenate(parts)[: int(SR * seconds)]
    fade = int(SR * 0.3)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    y /= np.abs(y).max() + 1e-9
    return np.stack([y, y * 0.92]).astype(np.float32) * 0.5


def save_wav_mp3(stem, x):
    wav = OUT / f"{stem}.wav"
    wavfile.write(wav, SR, (np.clip(x.T, -1, 1) * 32767).astype(np.int16))
    mp3 = wav_to_mp3(wav, OUT / f"{stem}.mp3")
    wav.unlink(missing_ok=True)
    return mp3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=3500)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    meta_f = OUT / "ambience.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    # free beds
    save_wav_mp3("room_tone", room_tone())
    meta["room_tone"] = {"name": "Room tone", "file": "library/ambience/room_tone.mp3", "source": "generated locally"}
    save_wav_mp3("keyboard", keyboard_bed())
    meta["keyboard"] = {"name": "Keyboard typing", "file": "library/ambience/keyboard.mp3",
                        "source": "Keyboard Soundpack #1 by Unicae Games (CC0)"}
    key = config.get_secret("elevenlabs_api_key")
    want = [b for b in BEDS if (not args.only or b in args.only.split(",")) and not (OUT / f"{b}.mp3").exists()]
    if want and key:
        start = el.account(key)["used"]
        per = None
        for i, bid in enumerate(want):
            spent = max(el.account(key)["used"] - start, (per or 0) * i)
            if per is not None and spent + per > args.cap:
                print(f"credit cap {args.cap} reached after {i} beds — stopping")
                break
            name, prompt = BEDS[bid]
            data = sound_generation(key, prompt)
            (OUT / f"{bid}.mp3").write_bytes(data)
            meta[bid] = {"name": name, "file": f"library/ambience/{bid}.mp3", "source": "ElevenLabs Sound Effects (generated for this project)"}
            if per is None:
                import time
                time.sleep(15)                                  # the credit counter updates with a delay
                per = el.account(key)["used"] - start
                if per <= 0:
                    per = 400                                   # unknown yet → assume a conservative cost per bed
                print(f"first bed cost ≈{per} credits → up to {args.cap // max(per, 1)} beds within the cap")
            print(f"  {bid}: {name}")
        print(f"ElevenLabs credits used: {el.account(key)['used'] - start}")
    meta_f.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (OUT / "README.txt").write_text("Noise beds for Voice effects. Generated by scripts/make_ambience.py; drop your own ambience files here too.\n", encoding="utf-8")
    print("beds:", ", ".join(m["name"] for m in meta.values()))


if __name__ == "__main__":
    main()
