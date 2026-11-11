"""Narration sentence timing (app/tts/layout.py), Match to video (placement.py) and video context (context.py)."""
import av
import numpy as np
import pytest
from scipy.io import wavfile

from app.project import Editor
from app.tts import context as tctx
from app.tts import layout as tlay
from app.tts import pacing, placement
from app.tts.pacing import SR
from tests.test_pacing import fake_speech
from tests.test_project import ASSETS


def _pieces():
    ps = pacing.split_text("We finally made it to Kaohsiung today. The night market is right over there. Let's go and eat!")
    audio = [fake_speech(6 + 2 * i, 4.5) for i in range(len(ps))]
    return ps, audio


def test_assemble_records_sentence_spans():
    ps, audio = _pieces()
    y, info = pacing.assemble(ps, audio)
    segs = info["segs"]
    assert len(segs) == len(ps) == 3
    assert [s["text"] for s in segs] == [p["text"] for p in ps]
    for s, nxt in zip(segs, segs[1:]):
        assert s["a"] < s["b"] <= nxt["a"]                     # in order, never overlapping
        gap = y[int(s["b"] * SR) + 200:int(nxt["a"] * SR) - 200]
        assert np.abs(gap).max() < 1e-6                        # between sentences = the pause (silence)
    assert segs[-1]["b"] <= len(y) / SR + 1e-3
    for s in segs:                                             # each span really contains that sentence's sound
        assert np.abs(y[int(s["a"] * SR):int(s["b"] * SR)]).max() > 0.1


def test_assemble_fit_target_keeps_spans_inside():
    ps, audio = _pieces()
    y0, _ = pacing.assemble(ps, audio)
    target = round(len(y0) / SR * 1.08, 2)
    y, info = pacing.assemble(ps, audio, target=target)
    assert info["fitted"] and abs(len(y) / SR - target) < 0.01
    assert all(s["b"] <= target + 1e-3 for s in info["segs"])
    assert info["segs"][-1]["a"] > [s for s in pacing.assemble(ps, audio)[1]["segs"]][-1]["a"]   # longer pauses


def _base(tmp_path):
    ps, audio = _pieces()
    y, info = pacing.assemble(ps, audio)
    f = tmp_path / "tts_base.wav"
    wavfile.write(f, SR, (np.clip(y, -1, 1) * 32767).astype(np.int16))
    return f, info["segs"], y


def test_clean_orders_and_limits():
    segs = [{"text": "a", "a": 0.0, "b": 1.0}, {"text": "b", "a": 1.4, "b": 2.4}]
    lay = tlay.clean(segs, [{"at": 0.0, "speed": 3}, {"at": 0.2, "speed": 0.1}])
    assert lay[0]["speed"] == 1.12 and lay[1]["speed"] == 0.88
    assert lay[1]["at"] >= lay[0]["at"] + 1.0 / 1.12            # pushed after the first sentence
    assert tlay.clean(segs, None) == tlay.natural_layout(segs)
    assert tlay.is_natural(segs, tlay.natural_layout(segs))


def test_compose_moves_sentences(tmp_path):
    f, segs, y = _base(tmp_path)
    lay = tlay.natural_layout(segs)
    lay[1]["at"] += 1.5                                        # second sentence 1.5 s later
    lay[2]["at"] += 1.5
    lay[2]["speed"] = 1.1
    lay = tlay.clean(segs, lay)
    out = tlay.compose(f, segs, lay, tmp_path)
    assert out.name.startswith("lay_") and tlay.compose(f, segs, lay, tmp_path) == out       # cached
    sr, z = wavfile.read(out)
    z = z.astype(np.float32) / 32768
    a0 = int(segs[1]["a"] * SR)                                # where it used to be: silence now
    assert np.abs(z[a0 + 2000:a0 + 20000]).max() < 1e-3
    n1 = int(lay[1]["at"] * SR)                                # where it is now: the same audio
    ref = y[int(segs[1]["a"] * SR):int(segs[1]["b"] * SR)]
    got = z[n1:n1 + len(ref)]
    assert np.corrcoef(ref[:len(got)], got)[0, 1] > 0.98
    want = (segs[2]["b"] - segs[2]["a"]) / 1.1                 # faster sentence is shorter
    assert abs(len(z) / SR - (lay[2]["at"] + want + tlay.TAIL)) < 0.05


def test_timeline_spans_follow_clip_in_and_layout():
    segs = [{"text": "one two", "a": 0.1, "b": 1.1}, {"text": "three", "a": 1.5, "b": 2.0}]
    c = {"start": 10.0, "dur": 3.0, "in": 0.0, "tts": {"segs": segs, "layout": None}}
    sp = tlay.timeline_spans(c)
    assert [(s["t0"], s["t1"]) for s in sp] == [(10.1, 11.1), (11.5, 12.0)]
    c["in"], c["start"], c["dur"] = 1.2, 11.2, 1.8             # head trimmed past the first sentence
    assert [s["i"] for s in tlay.timeline_spans(c)] == [1]
    c["tts"]["layout"] = [{"at": 0.1, "speed": 1.0}, {"at": 2.5, "speed": 1.0}]
    assert tlay.timeline_spans(c)[0]["t0"] == pytest.approx(12.5)


SEGS = [{"text": "First sentence here.", "a": 0.0, "b": 2.0}, {"text": "Second one.", "a": 2.4, "b": 3.4},
        {"text": "And the third.", "a": 3.8, "b": 5.3}]


def test_place_avoids_speech():
    speech = [[1.0, 3.0], [6.0, 7.0]]
    r = placement.place(SEGS, 0.0, 14.0, speech=speech, cuts=[], snap=False)
    durs = [s["b"] - s["a"] for s in SEGS]
    for s, d in zip(r["starts"], durs):
        for a, b in speech:
            assert s + d / r["speed"] <= a - placement.PAD + 1e-6 or s >= b + placement.PAD - 1e-6
    assert r["fits"] and r["collisions"] == 0
    assert r["starts"] == placement.place(SEGS, 0.0, 14.0, speech=speech, cuts=[], snap=False)["starts"]   # deterministic


def test_place_snaps_to_cuts():
    r = placement.place(SEGS, 0.0, 20.0, cuts=[0.0, 2.9, 9.0], snap=True)
    assert r["starts"][0] == pytest.approx(0.05)
    assert r["starts"][1] == pytest.approx(2.95)               # waited < 1 s for the shot change
    r2 = placement.place(SEGS, 0.0, 20.0, cuts=[0.0, 2.9, 9.0], snap=False)
    assert r2["starts"][1] == pytest.approx(2.4)               # natural pause


def test_place_squeezes_then_reports_overflow():
    r = placement.place(SEGS, 0.0, 5.0)                         # natural 5.3 s → shorter pauses / slightly faster
    assert r["fits"] and r["end"] <= 5.02
    r = placement.place(SEGS, 0.0, 3.0, wpm=180)
    assert not r["fits"] and r["over"] > 1.0 and r["words"] >= 3
    r = placement.place(SEGS, 0.0, 15.0)
    assert r["spare"] > 9 and r["add_words"] > 0


def test_next_gap_and_snap_target():
    assert placement.next_gap(1.0, 1.0, [[1.5, 3.0]]) == pytest.approx(3.0 + placement.PAD)
    assert placement.snap_target(4.1, [1.0, 4.0, 8.0]) == pytest.approx(4.05)


# ---------------------------------------------------------------- context from the project
def _proj():
    return {"tracks": [{"id": "V1", "kind": "video", "name": "Video 1"}, {"id": "A1", "kind": "audio", "name": "Dialogue", "role": "dialogue"},
                       {"id": "A2", "kind": "audio", "name": "Music", "duck": True}, {"id": "A4", "kind": "audio", "name": "Narration", "role": "narration"},
                       {"id": "T1", "kind": "text", "name": "Text"}],
            "clips": [{"id": "v1", "type": "media", "track": "V1", "asset": None, "start": 0.0, "in": 0.0, "out": 5.0, "dur": 5.0},
                      {"id": "v2", "type": "media", "track": "V1", "asset": None, "start": 5.0, "in": 0.0, "out": 4.0, "dur": 4.0},
                      {"id": "a1", "type": "media", "track": "A1", "asset": "spk", "start": 0.0, "in": 2.0, "out": 11.0, "speed": 1.0},
                      {"id": "m1", "type": "media", "track": "A2", "asset": "spk", "start": 0.0, "in": 0.0, "out": 9.0}]}


def test_context_cuts_and_speech_mapping(monkeypatch):
    monkeypatch.setattr(tctx, "speech_of", lambda a: [[3.0, 4.0], [9.0, 10.0]])
    assets = {"spk": {"id": "spk", "kind": "video", "meta": {"has_audio": True}}}
    ctx = tctx.context(_proj(), assets.get, 0.0, 9.0, scenes=False)
    assert ctx["cuts"] == [0.0, 5.0, 9.0]
    assert ctx["speech"] == [[1.0, 2.0], [7.0, 8.0]]           # source 3..4 with in=2 → 1..2; music track ignored
    assert ctx["sources"] == [{"clip": "a1", "how": "sound"}]


def test_context_prefers_caption_words(monkeypatch):
    monkeypatch.setattr(tctx, "speech_of", lambda a: [[2.0, 11.0]])
    p = _proj()
    p["clips"].append({"id": "t1", "type": "text", "track": "T1", "start": 1.0, "dur": 2.0, "meta": {"subtitle": True},
                       "text": {"caption": {"words": [{"w": "hello", "t0": 0.0, "t1": 0.4}, {"w": "there", "t0": 0.5, "t1": 0.9}]}}})
    assets = {"spk": {"id": "spk", "kind": "video", "meta": {"has_audio": True}}}
    ctx = tctx.context(p, assets.get, 0.0, 9.0, scenes=False)
    assert ctx["speech"] == [[1.0, 1.9]] and ctx["sources"][0]["how"] == "captions"


def test_scene_scan_finds_hard_cut(tmp_path, monkeypatch):
    f = tmp_path / "two.mp4"
    with av.open(str(f), "w") as out:
        s = out.add_stream("libx264", rate=25)
        s.width, s.height, s.pix_fmt = 160, 96, "yuv420p"
        for i in range(100):                                   # 2 s red-ish, 2 s blue-ish, with a moving bar
            img = np.zeros((96, 160, 3), np.uint8)
            img[:] = (200, 40, 30) if i < 50 else (20, 60, 210)
            img[:, (i * 3) % 160:(i * 3) % 160 + 8] = 255
            for pkt in s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(pkt)
        for pkt in s.encode():
            out.mux(pkt)
    monkeypatch.setattr(tctx, "MEDIA_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tctx, "ROOT", tmp_path)
    cuts = tctx.scenes_of({"id": "x", "path": "two.mp4", "mtime": 1})
    assert len(cuts) == 1 and abs(cuts[0] - 2.0) < 0.25
    assert (tmp_path / "cache" / "x" / "scenes.json").exists()


# ---------------------------------------------------------------- project ops
@pytest.fixture
def ed(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=ASSETS.get)
    e.p["format"]["fps"] = "30/1"
    e.save()
    return e


def test_tts_layout_op_and_captions_follow(ed):
    segs = [{"text": "Hello there everyone.", "a": 0.05, "b": 1.4}, {"text": "Welcome to Taiwan!", "a": 1.8, "b": 3.0}]
    (cid,) = ed.apply("add_tts", {"start": 2.0, "dur": 3.2, "text": "Hello there everyone. Welcome to Taiwan!", "caption": True,
                                  "extra": {"file": "x.wav", "base": "x.wav", "segs": segs, "stale": False}})
    ed.apply("narration_captions", {"id": cid})
    caps = [k for k in ed.p["clips"] if (k.get("meta") or {}).get("narration") == cid]
    assert caps and " ".join(k["text"]["content"] for k in caps) == "Hello there everyone. Welcome to Taiwan!"
    lay = [{"at": 0.05, "speed": 1.0}, {"at": 3.0, "speed": 1.0}]
    ed.apply("tts_layout", {"id": cid, "layout": lay, "file": "lay.wav", "dur": 4.4}, "Move Sentence")
    c = ed.clip(cid)
    assert c["tts"]["layout"] == lay and c["tts"]["file"] == "lay.wav" and c["dur"] == pytest.approx(4.4)
    caps = sorted((k for k in ed.p["clips"] if (k.get("meta") or {}).get("narration") == cid), key=lambda k: k["start"])
    welcome = next(k for k in caps if k["text"]["content"].startswith("Welcome"))
    assert welcome["start"] == pytest.approx(5.0, abs=0.04)    # moved with its sentence (2.0 + 3.0)
    ed.undo()
    assert ed.clip(cid)["tts"]["layout"] is None


def test_tts_layout_needs_segments(ed):
    from app.project import OpError
    (cid,) = ed.apply("add_tts", {"start": 0.0, "dur": 3.0, "text": "Hi."})
    with pytest.raises(OpError):
        ed.apply("tts_layout", {"id": cid, "layout": []})
