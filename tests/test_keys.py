"""API key safety: encrypted store, password + lockout, same-origin guard, redaction, leak scanner.
Uses temporary files — the real key store is never touched. python -m pytest tests/test_keys.py"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from app import keyauth, keystore

FAKE = "sk-ant-api03-" + "Ab1" * 20


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(keystore, "CONFIG", tmp_path)
    monkeypatch.setattr(keystore, "STORE", tmp_path / "keys.enc")
    monkeypatch.setattr(keystore, "MASTER", tmp_path / "master.key")
    monkeypatch.setattr(keystore, "LEGACY", tmp_path / "secrets.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    keystore.reset_cache()
    yield tmp_path
    keystore.reset_cache()


def test_keys_are_encrypted_and_never_listed(store):
    keystore.set_key("anthropic_api_key", FAKE)
    raw = (store / "keys.enc").read_text()
    assert FAKE not in raw and json.loads(raw)["alg"] == "AES-256-GCM"
    assert FAKE.encode() not in (store / "master.key").read_bytes()
    keystore.reset_cache()
    assert keystore.get("anthropic_api_key") == FAKE                    # decrypts again after a restart
    pub = json.dumps(keystore.public_list())
    assert FAKE not in pub and FAKE[-4:] in pub                          # only the last 4 characters


def test_validation_and_custom_keys(store):
    with pytest.raises(ValueError):
        keystore.set_key("anthropic_api_key", "sk_wrong_prefix_123456789")
    with pytest.raises(ValueError):
        keystore.set_key("Bad Name!", "abcdefghijk")
    with pytest.raises(ValueError):
        keystore.set_key("openai_api_key", "has space inside")
    keystore.set_key("openai_api_key", "sk-proj-" + "x" * 40, "my OpenAI")
    assert [c["name"] for c in keystore.public_list()["custom"]] == ["openai_api_key"]
    assert keystore.remove("openai_api_key") and not keystore.remove("openai_api_key")


def test_old_plain_secrets_file_is_imported_then_deleted(store):
    (store / "secrets.json").write_text(json.dumps({"elevenlabs_api_key": "sk_" + "a1" * 24}))
    assert keystore.get("elevenlabs_api_key") == "sk_" + "a1" * 24
    assert not (store / "secrets.json").exists() and (store / "keys.enc").exists()


def test_environment_variable_wins(store, monkeypatch):
    keystore.set_key("anthropic_api_key", FAKE)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env-" + "z" * 30)
    assert keystore.get("anthropic_api_key").startswith("sk-ant-from-env-")
    assert keystore.public_list()["services"][0]["source"] == "environment"


def test_redaction_hides_saved_and_key_shaped_strings(store):
    keystore.set_key("custom_token", "plainsecretvalue123")
    t = keystore.redact(f"error with {FAKE} and plainsecretvalue123 and sk_{'b2' * 20} and ghp_{'c' * 36}")
    assert FAKE not in t and "plainsecretvalue123" not in t and "sk_b2" not in t and "ghp_" not in t
    assert t.count("[hidden key]") == 4
    assert keystore.redact("asset 94554ad57d at 12.5 s") == "asset 94554ad57d at 12.5 s"   # normal text untouched


def test_no_builtin_password_then_create_change(monkeypatch, tmp_path):
    monkeypatch.setattr(keyauth, "AUTH", tmp_path / "auth.json")
    keyauth._state.update(fails=0, locked_until=0.0)
    assert keyauth.status()["password"] == "unset"
    with pytest.raises(keyauth.AuthError):
        keyauth.verify("anything at all")                       # nothing works before a password is created
    for weak in ("short", "password123", "aaaaaaaaaaaa", "1234567890"):
        with pytest.raises(ValueError):
            keyauth.set_password(weak)
    keyauth.set_password("purple tiger sings")
    rec = json.loads((tmp_path / "auth.json").read_text())
    assert "purple" not in json.dumps(rec) and rec["alg"] == "scrypt" and len(rec["salt"]) == 32
    keyauth.verify("purple tiger sings")
    with pytest.raises(keyauth.AuthError):
        keyauth.set_password("another long one", "wrong current")  # changing needs the current password
    keyauth._state.update(fails=0, locked_until=0.0)
    keyauth.set_password("another long one", "purple tiger sings")
    keyauth.verify("another long one")
    with pytest.raises(keyauth.AuthError):
        keyauth.verify("purple tiger sings")
    keyauth._state.update(fails=0, locked_until=0.0)


def test_password_lockout(monkeypatch, tmp_path):
    monkeypatch.setattr(keyauth, "AUTH", tmp_path / "auth.json")
    keyauth._state.update(fails=0, locked_until=0.0)
    keyauth.set_password("correct horse battery")
    with pytest.raises(keyauth.AuthError):
        keyauth.verify("")
    for _ in range(keyauth.MAX_TRIES - 2):
        with pytest.raises(keyauth.AuthError):
            keyauth.verify("wrong")
    with pytest.raises(keyauth.AuthError) as e:
        keyauth.verify("wrong")
    assert "locked" in str(e.value)
    assert keyauth.status()["locked_s"] > 0
    keyauth._state.update(fails=0, locked_until=0.0)


def test_password_is_not_in_the_source():
    """Only the salted hash is in the code. Give the real password via the environment to check (never write it here)."""
    import os
    from pathlib import Path
    pw = os.environ.get("VLOG_KEYS_PASSWORD")
    if not pw:
        pytest.skip("set VLOG_KEYS_PASSWORD to check that the password is nowhere in the repo")
    root = Path(__file__).resolve().parents[1]
    files = [p for d in ("app", "web", "scripts", "tests", "tools", "website", ".github", ".githooks", "projects/Demo", "docs") for p in (root / d).rglob("*") if p.is_file()
             and p.suffix in (".py", ".js", ".html", ".css", ".md", ".json", "")]
    for p in files + [root / n for n in ("CLAUDE.md", "README.md", "CHANGELOG.md", "CREDITS.md", "Setup AnKar Video Editor.bat", "Start AnKar Video Editor.bat", "Update AnKar Video Editor.bat")]:
        if p.exists():
            assert pw not in p.read_text(encoding="utf-8", errors="ignore"), p


def test_guard_blocks_other_websites_and_missing_header():
    from fastapi import HTTPException
    from app.server import PORT, _keys_guard
    good = NS(headers={"origin": f"http://localhost:{PORT}", "x-vlog-keys": "1"})
    _keys_guard(good)
    for h in ({"origin": "https://evil.example", "x-vlog-keys": "1"}, {"origin": "null", "x-vlog-keys": "1"},
              {"referer": "https://evil.example/page", "x-vlog-keys": "1"}, {"origin": f"http://localhost:{PORT}"}):
        with pytest.raises(HTTPException):
            _keys_guard(NS(headers=h))


def test_leak_scanner_finds_a_key(tmp_path, monkeypatch):
    from scripts import check_secrets as cs
    bad = tmp_path / "notes.md"
    bad.write_text(f"my key {FAKE}")
    ok = tmp_path / "ok.md"
    ok.write_text("nothing here, sk-ant- prefix only")
    monkeypatch.setattr(cs, "ROOT", tmp_path)
    monkeypatch.setattr(cs, "files", lambda staged: [bad, ok])
    with pytest.raises(SystemExit) as e:
        cs.main()
    assert e.value.code == 1
