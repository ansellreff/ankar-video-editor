"""Steady narration pacing (app/tts/pacing.py) and ElevenLabs voice settings."""
import numpy as np
import pytest

from app import config
from app.tts import elevenlabs as el
from app.tts import pacing
from app.tts.pacing import SR


def fake_speech(n_syl, rate, hesitation=0.0):
    """n_syl 'syllables' (tone bursts) at `rate` syllables/s, optional long pause in the middle."""
    per = 1.0 / rate
    parts = []
    t = np.arange(int(per * 0.7 * SR)) / SR
    burst = (0.4 * np.sin(2 * np.pi * 220 * t) * np.hanning(len(t))).astype(np.float32)
    for i in range(n_syl):
        parts += [burst, np.zeros(int(per * 0.3 * SR), np.float32)]
        if hesitation and i == n_syl // 2:
            parts.append(np.zeros(int(hesitation * SR), np.float32))
    return np.concatenate([np.zeros(SR // 5, np.float32), *parts, np.zeros(SR // 4, np.float32)])


def test_split_text_sentences_pauses_and_markers():
    ps = pacing.split_text("Hi there everyone! We finally made it to Kaohsiung today. [pause 1.2] Next stop... the night market.\nSee you!")
    texts = [p["text"] for p in ps]
    assert texts[0] == "Hi there everyone!" and texts[1] == "We finally made it to Kaohsiung today."
    assert ps[1]["pause"] == 1.2 and ps[1]["kind"] == "manual"
    assert ps[2]["text"] == "Next stop" and ps[2]["kind"] == "hesitation"
    assert ps[-1]["text"].endswith("See you!") and ps[-1]["pause"] == 0          # 2-word "See you!" merged, last = no pause
    assert ps[-2]["kind"] in ("paragraph", "end") or "night market" in ps[-1]["text"]
    long = pacing.split_text("After a long and challenging week working as engineers in Taiwan, we decided to close it with a fun day at the theme park.")
    assert len(long) == 2 and long[0]["kind"] == "clause"                           # long sentence breathes at the comma
    assert pacing.split_text("The price was 2.5 dollars.")[0]["text"] == "The price was 2.5 dollars."


def test_syllables():
    assert pacing.syllables("Taiwan") == 2 and pacing.syllables("beautiful") == 3 and pacing.syllables("make") == 1


def test_tidy_caps_hesitations():
    y = fake_speech(10, 4.0, hesitation=1.5)
    z, speech = pacing.tidy(y, 0.28)
    assert len(z) / SR < len(y) / SR - 1.2                                          # the 1.5 s hesitation is gone
    assert 1.6 < speech < 2.4


def test_assemble_evens_out_rate_and_fits():
    pieces = [{"text": "one two three four five six seven eight nine ten.", "pause": 0.42, "kind": "sentence"},
              {"text": "eleven twelve thirteen fourteen fifteen sixteen seventeen.", "pause": 0.0, "kind": "end"}]
    n0, n1 = (pacing.syllables(p["text"]) for p in pieces)
    a, b = fake_speech(n0, 4.4), fake_speech(n1, 3.6)                # one rushed, one dragging sentence
    y, info = pacing.assemble(pieces, [a, b], rate=None)
    assert info["speeds"][0] < 1.0 < info["speeds"][1] and not info["limited"]
    # after evening out, both sentences are spoken at (nearly) the same rate (measured like the engine: phrase length)
    la = len(pacing.tidy(a, 0.28)[0]) / SR - 0.09
    lb = len(pacing.tidy(b, 0.28)[0]) / SR - 0.09
    ra, rb = n0 / (la / info["speeds"][0]), n1 / (lb / info["speeds"][1])
    assert abs(ra - rb) / max(ra, rb) < 0.08, (ra, rb)
    # extreme differences are only partly evened out (±12% keeps the voice natural) and reported
    _, lim = pacing.assemble(pieces, [fake_speech(n0, 6.0), fake_speech(n1, 3.0)], rate=None)
    assert lim["limited"] and max(lim["speeds"]) <= 1.12 and min(lim["speeds"]) >= 0.88
    # explicit rate: slower setting = longer audio
    y_slow, i_slow = pacing.assemble(pieces, [a, b], rate="slow")
    y_fast, i_fast = pacing.assemble(pieces, [a, b], rate="fast")
    assert len(y_slow) > len(y_fast) and i_slow["wpm"] < i_fast["wpm"]
    # longer pauses = longer audio, same speech
    y_lp, _ = pacing.assemble(pieces, [a, b], rate="natural", pause_scale=2.0)
    y_np, _ = pacing.assemble(pieces, [a, b], rate="natural", pause_scale=1.0)
    assert len(y_lp) > len(y_np)
    # fit to a clip: exact length when reachable, reported when not
    nat = len(y_np) / SR
    y_fit, i_fit = pacing.assemble(pieces, [a, b], rate="natural", target=nat + 0.25)
    assert i_fit["fitted"] and len(y_fit) == int(round((nat + 0.25) * SR))
    _, i_no = pacing.assemble(pieces, [a, b], rate="natural", target=nat * 2.5)
    assert i_no["fitted"] is False and i_no["natural"]


def test_estimate_scales_with_rate():
    t = "We are going to the theme park today. It will be so much fun!"
    assert pacing.estimate(t, "slow") > pacing.estimate(t, "natural") > pacing.estimate(t, "fast")


def test_elevenlabs_voice_settings():
    auto = el.voice_settings("cheerful", 0.5, 1.0, "eleven_multilingual_v2", {"auto": True})
    assert auto["similarity_boost"] == 0.9 and "speed" in auto
    user = config.clean_el_voice({"auto": False, "stability": 0.8, "similarity": 1.4, "style": -1})
    assert user == {"auto": False, "stability": 0.8, "similarity": 1.0, "style": 0.0, "speaker_boost": True}
    s = el.voice_settings("cheerful", 0.5, 1.0, "eleven_multilingual_v2", user)
    assert s["stability"] == 0.8 and s["similarity_boost"] == 1.0 and s["style"] == 0.0
    v3 = el.voice_settings("cheerful", 0.5, 1.0, "eleven_v3", {**user, "stability": 0.7})
    assert v3["stability"] == 0.5 and "style" not in v3                              # v3 takes 0 / 0.5 / 1 only
