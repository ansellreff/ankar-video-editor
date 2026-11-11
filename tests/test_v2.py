import pytest

from app.project import Editor, OpError
from app.render.timeline import prop, src_time, motion_at
from tests.test_project import ASSETS, clips


@pytest.fixture
def ed(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=ASSETS.get)
    e.p["format"]["fps"] = "30/1"
    e.save()
    return e


def test_narration_track_and_roles(ed):
    roles = {t["id"]: t["role"] for t in ed.p["tracks"] if t["kind"] == "audio"}
    assert roles["A1"] == "dialogue" and "narration" in roles.values()


def test_freeze_insert_pushes_rest_later(ed):
    v, a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})
    (fz,) = ed.apply("freeze_frame", {"t": 4, "dur": 2})
    f = ed.clip(fz)
    assert f["hold"] == pytest.approx(4, abs=0.02) and f["dur"] == 2 and f["link"] is None
    assert clips(ed, "V1") == [(0, 4), (4, 6), (6, 12)]
    assert clips(ed, "A1") == [(0, 4), (6, 12)]                     # audio pushed with the video, gap under the freeze
    assert src_time(f, 5.0) == pytest.approx(4, abs=0.02)


def test_freeze_rest_of_clip(ed):
    v = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    (fz,) = ed.apply("freeze_frame", {"t": 3, "mode": "rest"})
    assert clips(ed, "V1") == [(0, 3), (3, 10)]
    assert ed.clip(fz)["hold"] == pytest.approx(3, abs=0.02)


def test_set_speed_duration_reverse_ripple(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0})[0]
    ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})
    ed.apply("set_speed", {"ids": [a], "duration": 20, "reverse": True})
    c = ed.clip(a)
    assert c["speed"] == pytest.approx(0.5) and c["reverse"] is True
    assert clips(ed, "V1") == [(0, 20), (20, 30)]
    assert clips(ed, "A1") == [(0, 20)]                                # linked audio follows
    assert src_time(c, 0.0) == pytest.approx(10 - 1 / 60, abs=0.02)     # reversed: starts at the source's end
    assert src_time(c, 10.0) == pytest.approx(5, abs=0.02)
    with pytest.raises(OpError):
        ed.apply("set_speed", {"ids": [a], "speed": 50})


def test_trim_reversed_clip_keeps_direction(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    ed.apply("set_speed", {"ids": [a], "speed": 1, "reverse": True})
    ed.apply("trim", {"id": a, "edge": "end", "t": 6})
    c = ed.clip(a)
    assert (c["in"], c["out"]) == (pytest.approx(4), pytest.approx(10))  # the tail of a reversed clip is the source head


def test_keyframes_interpolate_and_autokey(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 2, "link_audio": False})[0]
    ed.apply("toggle_anim", {"id": a, "path": "motion.scale", "t": 2})
    ed.apply("set_props", {"ids": [a], "values": {"motion.scale": 2.0}, "t": 6})   # auto-key at 6 s
    c = ed.clip(a)
    assert [k["t"] for k in c["keys"]["motion.scale"]] == [0, 4]
    assert prop(c, "motion.scale", 2) == 1 and prop(c, "motion.scale", 6) == 2
    assert 1 < prop(c, "motion.scale", 4) < 2
    ed.apply("set_props", {"ids": [a], "values": {"motion.x": 100}, "t": 4})       # not animated → static
    assert ed.clip(a)["motion"]["x"] == 100 and motion_at(ed.clip(a), 5)["x"] == 100
    ed.apply("toggle_anim", {"id": a, "path": "motion.scale", "t": 4})             # stop: keep value at 4 s
    c = ed.clip(a)
    assert "motion.scale" not in c["keys"] and 1 < c["motion"]["scale"] < 2


def test_split_rebases_keys(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    ed.apply("apply_anim_preset", {"ids": [a], "name": "ken_burns_in"})
    before = prop(ed.clip(a), "motion.scale", 7)
    (r,) = ed.apply("split", {"t": 5})
    assert prop(ed.clip(r), "motion.scale", 7) == pytest.approx(before)


def test_transition_pack_on_all_cuts(ed):
    ids = [ed.apply("add_media", {"asset": "v2", "track": "V1", "start": s, "link_audio": False})[0] for s in (0, 10, 20)]
    ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 40, "link_audio": False})        # gap before → no cut
    made = ed.apply("apply_transition_pack", {"pack": "energetic", "track": "V1"})
    xs = [x for x in ed.p["transitions"] if x["id"] in made]
    assert len(xs) == 2 and [x["type"] for x in xs] == ["whip_pan", "zoom_in"] and xs[0]["dur"] == pytest.approx(0.45)
    assert (xs[0]["a"], xs[0]["b"]) == (ids[0], ids[1])
    again = ed.apply("apply_transition_pack", {"pack": "smooth", "track": "V1"})                  # replaces, no duplicates
    assert len(ed.p["transitions"]) == 2 and {x["type"] for x in ed.p["transitions"]} == {"cross_dissolve", "blur_dissolve"}
    ed.apply("apply_transition_pack", {"pack": "glitchy", "ids": ids[1:]})                       # only between selected
    assert sum(1 for x in ed.p["transitions"] if x["type"] == "glitch") == 1
    with pytest.raises(OpError):
        ed.apply("apply_transition_pack", {"pack": "nope"})


def test_apply_look_replaces_grade(ed):
    a = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 0, "link_audio": False})[0]
    b = ed.apply("add_media", {"asset": "v2", "track": "V1", "start": 10, "link_audio": False})[0]
    ed.apply("update", {"ids": [a], "patch": {"filters": [{"type": "pixelate", "size": 16}], "color": {"exposure": 1}}})
    ed.apply("apply_look", {"ids": [a], "look": "vintage_vlog"})
    c = ed.clip(a)
    assert [f["type"] for f in c["filters"]] == ["lut", "film_grain", "vignette"] and c["color"] == {}
    assert c["filters"][0]["file"].endswith("warm_film.cube")
    ed.apply("apply_look", {"track": "V1", "look": "clean_natural"})
    assert all(ed.clip(i)["filters"] == [] and ed.clip(i)["color"]["contrast"] == 0.08 for i in (a, b))
    with pytest.raises(OpError):
        ed.apply("apply_look", {"ids": [a], "look": "nope"})


def test_anim_presets(ed):
    (t,) = ed.apply("add_text", {"track": "T1", "start": 0, "dur": 3, "x": 0.5})
    ed.apply("apply_anim_preset", {"ids": [t], "name": "slide_in_left"})
    c = ed.clip(t)
    assert prop(c, "text.x", 0) == pytest.approx(-0.5) and prop(c, "text.x", 1) == pytest.approx(0.5)
    ed.apply("apply_anim_preset", {"ids": [t], "name": "clear"})
    assert ed.clip(t)["keys"] == {}
