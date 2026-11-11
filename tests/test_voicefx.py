"""Voice effects DSP (app/render/voicefx.py) + clean speaker extraction helpers."""
import numpy as np
import pytest
from scipy.signal import freqz

from app.render import voicefx as vf
from app.tts.speakers import is_clean

SR = vf.SR


def tone(f, sec=1.0, amp=0.3):
    t = np.arange(int(SR * sec)) / SR
    s = (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
    return np.stack([s, s])


def rms(x):
    return float(np.sqrt((x[:, SR // 4:] ** 2).mean()))


def test_biquads_match_cookbook_response():
    b, a = vf.biquad("lp", 1000, 0.7071)
    w, h = freqz(b, a, worN=[100, 1000, 8000], fs=SR)
    db = 20 * np.log10(np.abs(h))
    assert abs(db[0]) < 0.2 and abs(db[1] + 3.01) < 0.1 and db[2] < -30
    b, a = vf.biquad("peak", 2000, 1.0, 6)
    _, h = freqz(b, a, worN=[2000], fs=SR)
    assert abs(20 * np.log10(abs(h[0])) - 6) < 0.05
    b, a = vf.biquad("lowshelf", 200, g=4)
    _, h = freqz(b, a, worN=[20, 10000], fs=SR)
    assert abs(20 * np.log10(abs(h[0])) - 4) < 0.3 and abs(20 * np.log10(abs(h[1]))) < 0.2


def test_phone_filter_band():
    fx = {"filter": "phone"}
    mid = rms(vf.process(tone(1200), fx))
    low = rms(vf.process(tone(150), fx))
    high = rms(vf.process(tone(7000), fx))
    assert 20 * np.log10(low / mid) < -12 and 20 * np.log10(high / mid) < -20


def test_distance_darkens_and_quiets():
    near = vf.process(tone(6000), {"distance": 0.0})
    far = vf.process(tone(6000), {"distance": 1.0})
    assert rms(far) < rms(near) * 0.3
    assert rms(vf.process(tone(300), {"distance": 1.0})) > rms(far) * 2      # lows survive distance


def test_space_adds_a_tail():
    x = np.zeros((2, SR * 2), np.float32)
    x[:, 1000] = 1.0                                                        # a click
    y = vf.process(x, {"space": "hall", "space_mix": 0.6})
    tail = np.abs(y[:, SR // 2: SR]).mean()
    assert tail > 1e-4 and np.abs(x[:, SR // 2: SR]).mean() == 0
    y2 = vf.process(x, {"space": "car", "space_mix": 0.6})
    assert np.abs(y2[:, SR // 2: SR]).mean() < tail * 0.2                  # a car is tiny compared with a hall


def test_pan_law_matches_web_audio():
    x = tone(500)
    left = vf.process(x, {"pan": -1})
    assert rms(left[1:2]) < 1e-6 and rms(left[0:1]) > rms(x[0:1]) * 1.3
    c = vf.pan_stereo(x, 0.0)
    assert np.allclose(c, x)


def test_noise_bed_loops_aligned_to_clip_time():
    beds = {b["id"]: b for b in vf.ambience_list()}
    assert {"room_tone", "keyboard", "cafe", "rain"} <= set(beds)
    silent = np.zeros((2, SR), np.float32)
    a = vf.process(silent, {"noise": "rain", "noise_db": -12}, t_rel=3.0)
    b = vf.process(np.zeros((2, SR * 4), np.float32), {"noise": "rain", "noise_db": -12}, t_rel=0.0)[:, SR * 3:]
    assert np.allclose(a, b, atol=1e-6)                                    # same bed position for the same clip time
    assert rms(a) > 1e-3


def test_normalize_and_inactive():
    assert vf.normalize({"pan": 5, "distance": -1})["pan"] == 1.0 and not vf.active(vf.normalize({}))
    x = tone(440)
    assert vf.process(x, {}) is x


def test_export_mix_applies_voice_fx(tmp_path):
    """A clip with the phone filter, rendered by the export mixer, is band-limited; the same clip without effects isn't."""
    from scipy.io import wavfile
    from app.render.audio import mix
    t = np.arange(SR * 2) / SR
    sig = (0.2 * (np.sin(2 * np.pi * 150 * t) + np.sin(2 * np.pi * 1200 * t) + np.sin(2 * np.pi * 7000 * t))).astype(np.float32)
    f = tmp_path / "voice.wav"
    wavfile.write(f, SR, sig)
    def project(fx):
        c = {"id": "c1", "type": "media", "asset": "a1", "track": "A1", "start": 0.0, "in": 0.0, "out": 2.0, "speed": 1.0}
        if fx:
            c["voice_fx"] = fx
        return {"tracks": [{"id": "A1", "kind": "audio", "role": "dialogue", "volume_db": 0}], "clips": [c], "settings": {}}
    assets = {"a1": {"abs": str(f), "start": 0.0, "has_audio": True, "kind": "audio", "dur": 2.0}}
    def band(y, f0):
        spec = np.abs(np.fft.rfft(y[0, SR // 2:]))
        fr = np.fft.rfftfreq(len(y[0, SR // 2:]), 1 / SR)
        return spec[np.argmin(np.abs(fr - f0))]
    dry, _ = mix(project(None), assets, 0, 2)
    wet, _ = mix(project({"filter": "phone"}), assets, 0, 2)
    assert band(dry, 7000) / band(dry, 1200) > 0.5
    assert band(wet, 7000) / band(wet, 1200) < 0.05 and band(wet, 150) / band(wet, 1200) < 0.3


def test_purity_filter_drops_other_speaker(tmp_path):
    from scipy.io import wavfile
    from app.tts import speakers
    rng = np.random.default_rng(3)
    a, b = rng.standard_normal(256), rng.standard_normal(256)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    def near(v):                                            # same voice, a little variation (cos ≈ 0.9)
        w = v + 0.03 * rng.standard_normal(256)
        return w / np.linalg.norm(w)
    # S1 talks 0–8 s (windows every 0.8 s), S2 talks 10–12 s; one S1 window (4.0–5.6) actually sounds like S2,
    # and one S1 window (8.8–10.4) touches S2's turn
    wins, labels, emb = [], [], []
    for s in np.arange(0, 6.5, 0.8):
        wins.append((s, s + 1.6)); labels.append("S1"); emb.append(near(b) if abs(s - 4.0) < 0.01 else near(a))
    wins.append((8.8, 10.4)); labels.append("S1"); emb.append(near(a))
    for s in (10.0, 10.8):
        wins.append((s, s + 1.6)); labels.append("S2"); emb.append(near(b))
    d = tmp_path
    x = (0.1 * rng.standard_normal(48000 * 13)).astype(np.float32)
    wavfile.write(d / "audio48k.wav", 48000, x)
    np.savez(d / "windows.npz", wins=np.array(wins, np.float32), labels=np.array(labels), emb=np.array(emb, np.float32), bg=np.full(len(wins), -60, np.float32))
    speakers.JOBS["t1"] = {"id": "t1", "isolated": False, "speakers": [{"id": "S1", "turns": [[0, 8]]}, {"id": "S2", "turns": [[10, 12.4]]}],
                           "src": {"audio48": str(d / "audio48k.wav"), "mix48": None, "windows": str(d / "windows.npz"), "path": "x", "t0": 0, "t1": 13}}
    info = {}
    y = speakers.speaker_audio("t1", "S1", max_sec=100, info=info)
    assert info["dropped_windows"] == 2                     # the misassigned window + the one touching S2
    assert info["source"] == "original" and len(y) > 48000 * 2


def test_is_clean():
    rng = np.random.default_rng(0)
    speech = np.concatenate([np.zeros(SR // 2, np.float32), tone(200, 2)[0], np.zeros(SR // 2, np.float32)]) * 1.0
    assert is_clean(speech + rng.standard_normal(len(speech)).astype(np.float32) * 1e-4)
    music = speech + 0.05 * np.sin(2 * np.pi * 440 * np.arange(len(speech)) / SR).astype(np.float32)
    assert not is_clean(music)
