import json

import pytest

from app.project import Editor, OpError

ASSETS = {
    "v1": {"path": "assets/video/a.mp4", "kind": "video", "meta": {"dur": 20.0, "has_audio": True, "has_video": True, "w": 1440, "h": 2560}},
    "v2": {"path": "assets/video/b.mp4", "kind": "video", "meta": {"dur": 10.0, "has_audio": True, "has_video": True, "w": 1440, "h": 2560}},
    "m1": {"path": "assets/audio/music/song.mp3", "kind": "audio", "meta": {"dur": 120.0, "has_audio": True}},
    "i1": {"path": "assets/images/logo.png", "kind": "image", "meta": {"w": 500, "h": 500}},
}


@pytest.fixture
def ed(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=ASSETS.get)
    e.p["format"]["fps"] = "30/1"        # whole-second times land exactly on frames (29.97 snaps 8 s → 8.008 s)
    e.save()
    return e


def clips(ed, track):
    return [(round(c["start"], 2), round(ed.end(c), 2)) for c in ed.on_track(track)]


def test_add_video_creates_linked_audio(ed):
    ids = ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0})
    assert len(ids) == 2
    v, a = ed.clip(ids[0]), ed.clip(ids[1])
    assert v["track"] == "V1" and a["track"] == "A1" and v["link"] == a["link"] is not None
    assert clips(ed, "V1") == [(0, 20)]


def test_music_goes_to_music_track(ed):
    (i,) = ed.apply("add_media", {"asset": "m1", "start": 2})
    assert ed.clip(i)["track"] == "A2"


def test_overwrite_splits_underlying_clip(ed):
    ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0, "link_audio": False})
    ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 5, "in_": 0, "out": 4, "link_audio": False})
    assert clips(ed, "V1") == [(0, 5), (5, 9), (9, 20)]
    tail = ed.on_track("V1")[2]
    assert tail["in"] == pytest.approx(9, abs=0.02)        # source continues where it was cut


def test_split_and_links(ed):
    v, a = ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0})
    ed.apply("split", {"t": 8})
    assert clips(ed, "V1") == [(0, 8), (8, 20)] and clips(ed, "A1") == [(0, 8), (8, 20)]
    rv, ra = ed.on_track("V1")[1], ed.on_track("A1")[1]
    assert rv["link"] == ra["link"] and rv["link"] != ed.clip(v)["link"]
    assert rv["in"] == pytest.approx(8, abs=0.02)


def test_trim_end_respects_source_length(ed):
    v, _ = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})
    ed.apply("trim", {"id": v, "edge": "end", "t": 50})         # can't extend past 10 s of media
    assert clips(ed, "V1") == [(0, 10)] and clips(ed, "A1") == [(0, 10)]
    ed.apply("trim", {"id": v, "edge": "end", "t": 6})
    assert clips(ed, "V1") == [(0, 6)] and clips(ed, "A1") == [(0, 6)]


def test_ripple_trim_and_ripple_delete(ed):
    a, _ = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})
    b, _ = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10})
    ed.apply("trim", {"id": a, "edge": "end", "t": 7, "ripple": True})
    assert clips(ed, "V1") == [(0, 7), (7, 17)]
    ed.apply("delete", {"ids": [a], "ripple": True})
    assert clips(ed, "V1") == [(0, 10)] and clips(ed, "A1") == [(0, 10)]


def test_ripple_trim_start_keeps_position(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})
    ed.apply("trim", {"id": a, "edge": "start", "t": 3, "ripple": True})
    assert clips(ed, "V1") == [(0, 7), (7, 17)]
    assert ed.clip(a)["in"] == pytest.approx(3, abs=0.02)


def test_move_overwrites_and_clamps_at_zero(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    b = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})[0]
    ed.apply("move", {"ids": [b], "delta": -4})
    assert clips(ed, "V1") == [(0, 6), (6, 16)]
    ed.apply("move", {"ids": [b], "delta": -100})
    assert clips(ed, "V1") == [(0, 10)]                         # b covered a completely


def test_move_to_other_track_kind_check(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})[0]
    ed.apply("move", {"ids": [a], "track": "V2"})
    assert ed.clip(a)["track"] == "V2"
    with pytest.raises(OpError):
        ed.apply("move", {"ids": [a], "track": "A2"})


def test_transition_between_adjacent_clips_and_cleanup(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    b = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})[0]
    (x,) = ed.apply("add_transition", {"type": "inward_wipe", "track": "V1", "t": 10, "dur": 0.8})
    tr = ed.p["transitions"][0]
    assert tr["a"] == a and tr["b"] == b and tr["dur"] == 0.8
    ed.apply("move", {"ids": [b], "delta": 2})                  # no longer adjacent → transition dropped
    assert ed.p["transitions"] == []


def test_fade_from_black_single_sided(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    ed.apply("add_transition", {"type": "dip_black", "b": a, "dur": 1})
    assert ed.p["transitions"][0]["a"] is None


def test_speed_change_ripples_following(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})
    ed.apply("update", {"ids": [a], "patch": {"speed": 2.0}})
    assert clips(ed, "V1") == [(0, 5), (5, 15)]


def test_text_and_image(ed):
    (t,) = ed.apply("add_text", {"track": "T1", "start": 1, "dur": 2, "content": "Hello"})
    assert ed.clip(t)["text"]["style"]["font"] == "Poppins"
    (i,) = ed.apply("add_media", {"asset": "i1", "track": "V2", "start": 0, "still_dur": 4})
    assert clips(ed, "V2") == [(0, 4)]
    ed.apply("trim", {"id": i, "edge": "end", "t": 30})          # stills can be any length
    assert clips(ed, "V2") == [(0, 30)]


def test_undo_redo_round_trip_and_persistence(ed, tmp_path):
    ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0})
    s1 = json.dumps(ed.p)
    ed.apply("split", {"t": 5})
    s2 = json.dumps(ed.p)
    assert ed.undo() == "Split" and json.dumps(ed.p) == s1
    assert ed.redo() == "Split" and json.dumps(ed.p) == s2
    reloaded = Editor(tmp_path / "project.json", asset_info=ASSETS.get)
    assert json.dumps(reloaded.p) == s2


def test_external_edit_is_detected_and_undoable(ed, tmp_path):
    ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0})
    data = json.loads((tmp_path / "project.json").read_text())
    data["markers"].append({"id": "m99", "t": 3.0, "label": "from Claude"})
    (tmp_path / "project.json").write_text(json.dumps(data))
    assert ed.check_external() is True
    assert ed.p["markers"][0]["label"] == "from Claude"
    assert ed.check_external() is False
    ed.undo()
    assert ed.p["markers"] == []


def test_failed_op_leaves_project_untouched(ed):
    ed.apply("add_media", {"asset": "v1", "track": "V1", "start": 0})
    before = json.dumps(ed.p)
    with pytest.raises(OpError):
        ed.apply("add_text", {"track": "V1"})
    assert json.dumps(ed.p) == before and ed.history()["depth"] == 1


def test_paste_offsets_and_relinks(ed):
    v, a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})
    src = [ed.clip(v), ed.clip(a)]
    new = ed.apply("paste", {"clips": src, "t": 20})
    nv, na = ed.clip(new[0]), ed.clip(new[1])
    assert nv["start"] == pytest.approx(20, abs=0.02) and nv["link"] == na["link"] != ed.clip(v)["link"]
