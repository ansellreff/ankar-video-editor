import numpy as np
import pytest

from app import captions
from app.project import Editor
from app.subtitles import chunk_captions, realign, review_flags
from tests.test_project import ASSETS


@pytest.fixture
def ed(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=ASSETS.get)
    e.p["format"]["fps"] = "30/1"
    e.save()
    return e


def W(*spec):
    """W(('Hello', 0, .4), ...) → word dicts."""
    return [{"w": w, "t0": a, "t1": b} for w, a, b in spec]


UTT = {"lang": "en", "translated": False,
       "words": W(("We", 1.0, 1.2), ("went", 1.2, 1.5), ("to", 1.5, 1.6), ("Kaohsiung", 1.6, 2.2), ("today.", 2.2, 2.6),
                  ("It", 3.4, 3.5), ("was", 3.5, 3.7), ("so", 3.7, 3.9), ("much", 3.9, 4.1), ("fun", 4.1, 4.4),
                  ("and", 4.4, 4.6), ("we", 4.6, 4.7), ("loved", 4.7, 5.0), ("it", 5.0, 5.2))}


def test_chunking_breaks_on_punctuation_pause_and_count():
    caps = chunk_captions([UTT], max_words=5, max_chars=28)
    texts = [" ".join(w["w"] for w in c["words"]) for c in caps]
    assert texts == ["We went to Kaohsiung today.", "It was so much fun", "and we loved it"]
    assert caps[0]["start"] == 1.0 and caps[0]["words"][0]["t0"] == 0.0           # word times relative to the line
    assert caps[1]["words"][-1]["t1"] == pytest.approx(1.0)
    for a, b in zip(caps, caps[1:]):
        assert a["end"] <= b["start"] + 1e-9


def test_translated_lines_wrapped_and_unclear_flagged():
    u = {"lang": "id", "translated": True, "original": "Kita pergi", "line_conf": 0.3,
         "words": W(("We", 0, .3), ("are", .3, .5), ("going", .5, .9))}
    (c,) = chunk_captions([u], max_words=5, max_chars=30)
    assert c["words"][0]["w"] == "(We" and c["words"][-1]["w"] == "going)"
    assert any("translation unsure" in r for r in c["review"])
    lo = {"lang": "en", "translated": False, "words": [{"w": "mumble", "t0": 0, "t1": .4, "conf": 0.1}, {"w": "ok", "t0": .4, "t1": .6, "conf": 0.9}]}
    assert review_flags(chunk_captions([lo])[0]) == ["unclear: mumble"]


def test_realign_keeps_conf_and_spreads():
    ws = [{"w": "yida", "t0": 0, "t1": .5, "conf": .3}, {"w": "world", "t0": .5, "t1": 1, "conf": .9}]
    r = realign(ws, "E-DA World")
    assert [w["w"] for w in r] == ["E-DA", "World"] and r[0]["conf"] == .3
    r = realign(ws, "E-DA Theme Park")
    assert len(r) == 3 and r[0]["t0"] == 0 and r[-1]["t1"] == pytest.approx(1)


def _add(ed, template="karaoke_line"):
    caps = chunk_captions([UTT], max_words=5, max_chars=28)
    return ed.apply("add_captions", {"captions_": caps, "template": template})


def test_add_captions_and_emphasis(ed):
    ids = _add(ed)
    assert len(ids) == 3
    c = ed.clip(ids[0])
    cap = c["text"]["caption"]
    assert cap["template"] == "karaoke_line" and cap["style"]["mode"] == "karaoke"
    assert c["text"]["content"] == "We went to Kaohsiung today."
    assert next(w for w in cap["words"] if w["w"] == "Kaohsiung").get("emph")          # glossary name → emphasis
    assert c["meta"]["subtitle"] and c["text"]["y"] == pytest.approx(0.74)


def test_split_and_trim_rebase_words(ed):
    (a, *_rest) = _add(ed)
    (r,) = ed.apply("split", {"t": 1.6, "ids": [a]})
    left, right = ed.clip(a), ed.clip(r)
    assert left["text"]["content"] == "We went to"                                     # 'to' ends exactly at the cut
    assert right["text"]["content"] == "Kaohsiung today."
    k = next(w for w in right["text"]["caption"]["words"] if w["w"] == "Kaohsiung")
    assert right["start"] + k["t0"] == pytest.approx(1.6, abs=0.02)                   # same timeline time
    ed.apply("trim", {"id": r, "edge": "end", "t": 2.2})
    assert ed.clip(r)["text"]["content"].endswith("Kaohsiung")


def test_edit_text_keeps_timing_and_marks_emphasis(ed):
    (a, *_rest) = _add(ed)
    before = [w["t0"] for w in ed.clip(a)["text"]["caption"]["words"]]
    ed.apply("update", {"ids": [a], "patch": {"text": {"content": "We drove to *Kaohsiung* today."}}})
    c = ed.clip(a)
    ws = c["text"]["caption"]["words"]
    assert [w["t0"] for w in ws] == before and ws[1]["w"] == "drove" and ws[3]["emph"]
    assert c["text"]["content"] == "We drove to Kaohsiung today." and c["meta"]["edited"]
    ed.apply("update", {"ids": [a], "patch": {"text": {"content": "We went there"}}})            # fewer words → spread
    ws = ed.clip(a)["text"]["caption"]["words"]
    assert len(ws) == 3 and ws[0]["t0"] == 0 and ws[-1]["t1"] == pytest.approx(1.6)


def test_restyle_and_overrides(ed):
    ids = _add(ed)
    ed.apply("update", {"ids": [ids[0]], "patch": {"text": {"y": 0.5}}})
    ed.apply("restyle_captions", {"ids": "all", "template": "word_pop"})
    c = ed.clip(ids[0])
    assert c["text"]["caption"]["style"]["mode"] == "pop" and c["text"]["caption"]["template"] == "word_pop"
    assert c["text"]["y"] == 0.5                                                        # position kept
    ed.apply("restyle_captions", {"ids": [ids[1]], "overrides": {"active": {"color": "#00FF00"}}})
    assert ed.clip(ids[1])["text"]["caption"]["style"]["active"]["color"] == "#00FF00"
    (t,) = ed.apply("add_text", {"track": "T2", "start": 10, "dur": 2, "content": "plain title here"})
    ed.apply("restyle_captions", {"ids": [t], "template": "bounce"})
    ws = ed.clip(t)["text"]["caption"]["words"]
    assert [w["w"] for w in ws] == ["plain", "title", "here"] and ws[-1]["t1"] == pytest.approx(2)


def test_rechunk_changes_words_per_line(ed):
    _add(ed)
    made = ed.apply("rechunk_captions", {"ids": "all", "max_words": 2, "max_chars": 40})
    texts = [ed.clip(i)["text"]["content"] for i in made]
    assert texts[:3] == ["We went", "to Kaohsiung", "today."]
    k = next(ed.clip(i) for i in made if ed.clip(i)["text"]["content"] == "to Kaohsiung")
    assert k["start"] + k["text"]["caption"]["words"][1]["t0"] == pytest.approx(1.6, abs=0.02)


def test_unclear_markers_and_review(ed):
    caps = chunk_captions([UTT])
    caps[0]["review"] = ["unclear: Kaohsiung"]
    ids = ed.apply("add_captions", {"captions_": caps, "unclear": [{"start": 8.0, "end": 9.0, "lang": "en"}]})
    m = next(m for m in ed.p["markers"] if m.get("kind") == "unclear")
    assert m["t"] == pytest.approx(8.0) and m["color"] == "red"
    ed.apply("set_review", {"ids": [ids[0], m["id"]]})
    assert ed.clip(ids[0])["meta"]["review_ok"] and not any(x.get("kind") == "unclear" for x in ed.p["markers"])
    ed.apply("add_captions", {"captions_": chunk_captions([UTT]), "replace": [0, 20]})          # replace = no duplicates
    assert len([c for c in ed.p["clips"] if c["type"] == "text"]) == 3


def test_templates_are_complete():
    ts = captions.templates()
    assert len(ts) >= 15 and ts[0]["id"] == "karaoke_line"
    modes = {t.get("mode") for t in ts}
    assert {"karaoke", "karaoke_box", "pop", "bounce", "reveal", "typewriter", "none"} <= modes
    from app.render.text import _font_table
    fams = {f for f, _ in _font_table()}
    assert all(t["font"] in fams for t in ts)


@pytest.mark.parametrize("tid", [t["id"] for t in captions.templates()])
def test_every_template_renders(ed, tid):
    from app.render.caption import render_caption
    (a, *_r) = _add(ed, tid)
    c = ed.clip(a)
    img = render_caption(c, c["start"] + 0.5, 540, 960)
    assert img is not None and img.shape == (960, 540, 4) and img[..., 3].max() > 200
    ys = np.where(img[..., 3].max(axis=1) > 0)[0]
    assert 0 < ys.min() and ys.max() < 959                                             # on screen
