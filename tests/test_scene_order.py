"""Footage names = the user's chronological order (scripts/having_fun/builder.scene_key)."""
from scripts.having_fun.builder import scene_key


def test_scene_key_parses_series_and_numbers():
    assert scene_key("Scene 3_20_1.mp4") == ("", (3, 20, 1))
    assert scene_key("Scene 3_20_2") == ("", (3, 20, 2))
    assert scene_key("Intro Ansell Scene 1_4.mp4") == ("Intro Ansell", (1, 4))
    assert scene_key("Disclosure - Latch.mp3") is None


def test_chronological_comparison():
    k = lambda n: scene_key(n)[1]
    assert k("Scene 3_20") < k("Scene 3_20_1") < k("Scene 3_20_2") < k("Scene 3_21")
    assert k("Scene 3_9_3") < k("Scene 3_10_1")          # numbers, not text ("10" > "9")
    assert k("Scene 5_11_2") < k("Scene 5_12")
