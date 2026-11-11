"""Self-contained projects: import routing, per-project library, project folders, migration remap, Reels default,
watermark placement."""
from pathlib import Path

import pytest

from app import library as lib_mod
from app.library import asset_id, route
from app.project import BRAND_DEFAULT, Editor, new_project
from app.render.timeline import brand_clip, brand_motion


@pytest.mark.parametrize("path,kind,dest", [
    ("company logo.png", "image", "assets/brand/logo"),
    ("Brand/white.png", "image", "assets/brand/logo"),
    ("watermark_white.png", "image", "assets/brand/watermark"),
    ("bgm/summer.mp3", "audio", "assets/audio/music"),
    ("Music - happy.m4a", "audio", "assets/audio/music"),
    ("whoosh.wav", "audio", "assets/audio/sfx"),
    ("sfx/pop.wav", "audio", "assets/audio/sfx"),
    ("Ansell voice.m4a", "audio", "assets/audio/voiceover"),
    ("narration take 2.wav", "audio", "assets/audio/voiceover"),
    ("random.mp3", "audio", "assets/audio/music"),
    ("Day 1 - Kaohsiung/IMG_2041.MOV", "video", "assets/video"),
    ("photo_park.jpg", "image", "assets/photos"),
    ("IMG_2200.jpg", "image", "assets/photos"),
    ("Vlog script v2.docx", "doc", "docs/script"),
    ("notes.pdf", "doc", "docs/script"),
    ("storyboard/shot 3.png", "image", "docs/storyboard"),
    ("music license.pdf", "doc", "assets/licenses"),
    ("clip.srt", "subtitle", "assets/subtitles"),
    ("logo animation.mp4", "video", "assets/brand/logo"),
    ("voice memo.mp4", "video", "assets/audio/voiceover"),
])
def test_import_routing(path, kind, dest):
    assert route(Path(path), kind) == dest


def test_library_scopes_to_project(tmp_path, monkeypatch):
    projects, library = tmp_path / "projects", tmp_path / "library"
    for p in ("A/assets/video/x.mp4", "B/assets/audio/music/song.mp3"):
        (projects / p).parent.mkdir(parents=True, exist_ok=True)
        (projects / p).write_bytes(b"0")
    for p in ("samples/demo.mp4", "ir/hall.wav", "voices/K/neutral_1.wav", "ambience/rain.mp3"):
        (library / p).parent.mkdir(parents=True, exist_ok=True)
        (library / p).write_bytes(b"0")
    monkeypatch.setattr(lib_mod, "ROOT", tmp_path)
    monkeypatch.setattr(lib_mod, "LIBRARY", library)
    monkeypatch.setattr(lib_mod, "project_assets", lambda n: projects / n / "assets")
    monkeypatch.setattr(lib_mod, "project_import", lambda n: projects / n / "import")
    monkeypatch.setattr(lib_mod, "rel", lambda p: Path(p).resolve().relative_to(tmp_path.resolve()).as_posix())
    L = lib_mod.Library(project="A")
    L._enqueue = lambda aid: None
    names = {a["name"]: a for a in L.scan().values()}
    assert "x.mp4" in names and "song.mp3" not in names                 # project B's music isn't visible in A
    assert names["x.mp4"]["scope"] == "project" and names["x.mp4"]["folder"] == "video"
    assert names["demo.mp4"]["scope"] == "library" and names["demo.mp4"]["folder"] == "library/samples"
    assert "hall.wav" not in names and "neutral_1.wav" not in names     # internal library folders stay hidden
    names = {a["name"] for a in L.set_project("B").values()}
    assert "song.mp3" in names and "x.mp4" not in names and "rain.mp3" in names


def test_import_sorting_into_project(tmp_path, monkeypatch):
    proj = tmp_path / "projects" / "A"
    imp = proj / "import"
    for p in ("logo.png", "bgm/track.mp3", "Day 2 - E-DA/clip.mp4", "my script.docx"):
        (imp / p).parent.mkdir(parents=True, exist_ok=True)
        (imp / p).write_bytes(b"0")
    monkeypatch.setattr(lib_mod, "project_import", lambda n: tmp_path / "projects" / n / "import")
    monkeypatch.setattr(lib_mod, "project_assets", lambda n: tmp_path / "projects" / n / "assets")
    monkeypatch.setattr(lib_mod, "rel", lambda p: Path(p).resolve().relative_to(tmp_path.resolve()).as_posix())
    monkeypatch.setattr(lib_mod, "_busy", lambda p: False)
    L = lib_mod.Library(project="A")
    moved = {m["to"].split("projects/A/")[1] for m in L.sort_import()}
    assert moved == {"assets/brand/logo/logo.png", "assets/audio/music/track.mp3", "assets/video/Day 2 - E-DA/clip.mp4",
                     "docs/script/my script.docx"}
    assert not any(imp.rglob("*.*"))                                     # import/ emptied, subfolders tidied


def test_new_project_is_reels_and_has_folders(tmp_path, monkeypatch):
    from app import projects as pm_mod
    monkeypatch.setattr(pm_mod, "PROJECTS", tmp_path)
    monkeypatch.setattr(pm_mod, "project_assets", lambda n: tmp_path / n / "assets")
    monkeypatch.setattr(pm_mod, "project_import", lambda n: tmp_path / n / "import")
    monkeypatch.setattr(pm_mod, "project_docs", lambda n: tmp_path / n / "docs")
    monkeypatch.setattr(pm_mod, "project_exports", lambda n: tmp_path / n / "exports")
    monkeypatch.setattr(pm_mod, "RECENT", tmp_path / ".recent.json")
    pm = pm_mod.ProjectManager(asset_info=lambda a: None)
    pm.new("Fresh")
    f = pm.editor.p["format"]
    assert (f["preset"], f["w"], f["h"], f["fps"]) == ("reels", 1080, 1920, "30/1")
    for d in ("import", "exports", "assets/video", "assets/photos", "assets/brand/logo", "assets/brand/watermark",
              "assets/audio/music", "assets/audio/sfx", "assets/audio/voiceover", "docs/script", "docs/storyboard"):
        assert (tmp_path / "Fresh" / d).is_dir(), d
    assert (tmp_path / "Fresh" / "import" / "README.txt").exists()
    # duplicate copies the assets and points the copy's project.json at its own files
    (tmp_path / "Fresh" / "assets" / "brand" / "logo" / "l.png").write_bytes(b"0")
    path = f"{tmp_path.name}/Fresh/assets/brand/logo/l.png"
    pm.editor.p["assets"][asset_id(path)] = {"path": path, "kind": "image"}
    pm.editor.save()
    pm.duplicate("Fresh", "Copy")
    import json
    p2 = json.loads((tmp_path / "Copy" / "project.json").read_text(encoding="utf-8"))
    new_path = f"{tmp_path.name}/Copy/assets/brand/logo/l.png"
    assert list(p2["assets"]) == [asset_id(new_path)] and (tmp_path / "Copy" / "assets" / "brand" / "logo" / "l.png").exists()


def test_migration_remaps_paths_and_ids():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mig", Path(__file__).resolve().parent.parent / "scripts" / "migrate_projects.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    old = "assets/video/_samples/a.mp4"
    p = {"assets": {asset_id(old): {"path": old, "kind": "video"}},
         "clips": [{"id": "c1", "asset": asset_id(old), "filters": [{"type": "lut", "file": "assets/luts/x.cube"}]},
                   {"id": "c2", "type": "tts", "tts": {"file": "assets/audio/voiceover/generated/tts_1.wav"}}]}
    new, n, remap = mig.remap_project(p)
    assert new["clips"][0]["asset"] == asset_id("library/samples/a.mp4") and list(new["assets"]) == [asset_id("library/samples/a.mp4")]
    assert new["clips"][0]["filters"][0]["file"] == "library/luts/x.cube"
    assert new["clips"][1]["tts"]["file"] == "library/generated/narration/tts_1.wav"
    assert mig.new_path("assets/video/Scene 2.MOV") == "projects/vlog/assets/video/Scene 2.MOV"
    assert mig.new_path("assets/images/a.png") == "projects/vlog/assets/photos/a.png"


def test_set_format_reels_snaps_fps(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=lambda a: None)
    e.p["format"].update(preset="9:16", fps="30000/1001")
    e.apply("set_format", {"preset": "reels"})
    assert e.p["format"]["fps"] == "30/1" and e.p["format"]["w"] == 1080


def test_brand_placement_and_normalize(tmp_path):
    e = Editor(tmp_path / "project.json", asset_info=lambda a: {"path": "projects/x/assets/brand/logo/l.png", "kind": "image", "meta": {"w": 800, "h": 400}})
    assert e.p["settings"]["brand"] == BRAND_DEFAULT and brand_clip(e.p) is None
    e.apply("set_brand", {"asset": "abc", "position": "tr", "size": 0.2, "opacity": 0.8})
    br = e.p["settings"]["brand"]
    assert br["enabled"] and "abc" in e.p["assets"] and brand_clip(e.p)["asset"] == "abc"
    m = brand_motion(1080, 1920, 800, 400, br)                          # 20% of 1080 = 216 px wide logo
    assert m["scale"] == pytest.approx(216 / 800)
    assert m["x"] == pytest.approx(540 - 0.04 * 1080 - 108) and m["y"] == pytest.approx(-(960 - 0.04 * 1080 - 54))
    m = brand_motion(1080, 1920, 800, 400, {**br, "position": "bl"})
    assert m["x"] < 0 and m["y"] > 0
    assert new_project()["format"]["preset"] == "reels"
