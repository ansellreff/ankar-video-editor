from app.tts import pronounce


def test_respell_names_keeps_other_words(tmp_path, monkeypatch):
    monkeypatch.setattr(pronounce, "FILE", tmp_path / "p.json")
    pronounce._cache.update(mtime=None, rules=None)
    s = "Now I'm catching a bus to Kaohsiung from Hsinchu, then E-DA and Wanpi World in Tainan."
    out = pronounce.apply(s)
    assert "Gao-shyong" in out and "Ee-dah" in out and "Wahn-pee" in out
    assert "catching a bus" in out
    assert pronounce.apply("Fo Guang Shan on the hill") == "Foh Gwahng Shahn on the hill"
    assert pronounce.apply("No names here.") == "No names here."


def test_user_list_and_word_boundaries(tmp_path, monkeypatch):
    monkeypatch.setattr(pronounce, "FILE", tmp_path / "p.json")
    pronounce._cache.update(mtime=None, rules=None)
    pronounce.save({"Ansell": "An-sell"})
    assert pronounce.apply("Ansell's bike") == "An-sell's bike"
    assert pronounce.apply("Ansellx") == "Ansellx"
