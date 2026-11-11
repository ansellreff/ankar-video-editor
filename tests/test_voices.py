"""Voice profile housekeeping (delete / rename / move sample / reset) on a temporary voices folder."""
import numpy as np
import pytest

from app.tts import manager
from app.tts.manager import SR, Voices


@pytest.fixture
def vdir(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(manager, "VOICES", root / "assets" / "voices")
    monkeypatch.setattr(manager, "CACHE", root / "cache")
    monkeypatch.setattr(manager, "WORK", root / "cache" / "work")
    monkeypatch.setattr(manager, "ROOT", root)
    monkeypatch.setattr(manager, "rel", lambda p: p.relative_to(root).as_posix())
    (root / "cache" / "work").mkdir(parents=True)
    return root


def speech(sec=3.0):
    t = np.arange(int(SR * sec)) / SR
    return (0.3 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def test_delete_rename_move_reset(vdir):
    Voices.create("Karina", True)
    Voices.create("Ansell", True)
    f1 = Voices.add_sample("Karina", "neutral", speech())
    f2 = Voices.add_sample("Karina", "cheerful", speech())
    assert {v["name"] for v in Voices.list()} == {"Karina", "Ansell"}
    # sample uploaded under the wrong person → move it (and retag)
    moved = Voices.move_sample(f2, "Ansell", "serious")
    assert moved.endswith("Ansell/serious_1.wav") and (vdir / moved).exists() and not (vdir / f2).exists()
    # rename a voice made under the wrong name
    assert Voices.rename("Karina", "Karina Test") == "Karina Test"
    with pytest.raises(ValueError):
        Voices.rename("Karina Test", "Ansell")                     # won't overwrite another voice
    # delete one sample and one voice → both go to cache/trash, not gone
    s = Voices.list()[1]["samples"][0]["file"] if Voices.list()[1]["name"] == "Karina Test" else None
    b = Voices.delete_sample(s)
    assert (vdir / b).exists() and "trash" in b
    b2 = Voices.delete("Karina Test")
    assert (vdir / b2 / "voice.json").exists() and [v["name"] for v in Voices.list()] == ["Ansell"]
    # reset everything (incl. the speaker-extraction cache)
    (vdir / "cache" / "work" / "speakers" / "job1").mkdir(parents=True)
    (vdir / "cache" / "work" / "voiceref_x.wav").write_bytes(b"x")
    r = Voices.reset_all()
    assert r["voices"] == ["Ansell"] and Voices.list() == []
    assert (vdir / r["backup"] / "Ansell" / "serious_1.wav").exists()
    assert (vdir / r["backup"] / "speaker_extraction_cache" / "job1").exists()
    assert not list((vdir / "cache" / "work").glob("voiceref_*"))
    with pytest.raises(ValueError):
        Voices.delete("Nobody")
