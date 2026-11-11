"""Leak check before pushing to GitHub: finds API keys in files that git would commit.

Looks for (1) your saved keys themselves (decrypted locally, compared, never printed) and (2) anything shaped like an
API key (sk-ant-…, sk_…, sk-…, AIza…, ghp_…). Exit code 1 = something found (the commit / push should stop).

  python -m scripts.check_secrets            # every file git would track (or the whole folder if not a git repo yet)
  python -m scripts.check_secrets --staged   # only staged files (used by the pre-commit hook)
Enable the hook once:  git config core.hooksPath .githooks"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".venv-tts", "cache", "models", "node_modules", "__pycache__"}
SKIP_FILES = {"config/keys.enc", "config/master.key", "config/auth.json", "config/secrets.json"}
TEXT_EXT = {".py", ".js", ".json", ".md", ".txt", ".html", ".css", ".ps1", ".bat", ".cfg", ".ini", ".toml", ".yml",
            ".yaml", ".env", ".sh", ".cube", ".srt", ".vtt", ""}


def files(staged: bool) -> list[Path]:
    try:
        if staged:
            out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
        else:
            out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout
        return [ROOT / p for p in out.splitlines() if p.strip()]
    except (OSError, subprocess.CalledProcessError):            # not a git repo yet: walk, skipping ignored folders
        res = []
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and "/exports/" not in f"/{rel}":
                res.append(p)
        return res


PUBLIC_HAVING_FUN = {"__init__.py", "api.py", "builder.py"}      # the generic build engine (the AI Editor uses it)


def private(rel: str) -> str | None:
    """Files that must never go to the public repo, even if .gitignore is changed by mistake."""
    parts = rel.split("/")
    if parts[0] in ("config", "cache", "models", "runtime", "runtime-tts", ".venv", ".venv-tts", "tools"):
        return f"{parts[0]}/ is private to this PC"
    if parts[0] == "projects" and len(parts) > 1 and parts[1] != "Demo":
        return "your own projects stay on this PC (only projects/Demo is public)"
    if rel.startswith(("library/voices/", "library/generated/", "library/reports/", "library/styles/")):
        return "your voices / generated media / styles stay on this PC"
    if rel == "CLAUDE.md":
        return "CLAUDE.md holds your private working notes"
    if rel.startswith("scripts/having_fun/") and parts[-1] not in PUBLIC_HAVING_FUN:
        return "your personal Taiwan edit scripts stay on this PC"
    if parts[-1] in ("keys.enc", "master.key", "auth.json", "secrets.json") or parts[-1].startswith(".env"):
        return "secret file"
    return None


def _is_git() -> bool:
    try:
        return subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip() == "true"
    except OSError:
        return False


def main():
    sys.path.insert(0, str(ROOT))
    from app import keystore
    import os
    try:
        saved = [e["value"] for e in keystore._load().values() if len(e.get("value", "")) >= 8]
    except Exception:  # noqa: BLE001 — no store yet / other user: pattern check still runs
        saved = []
    pw = os.environ.get("VLOG_KEYS_PASSWORD")                  # optional: also make sure the key-page password isn't anywhere
    if pw and len(pw) >= 6:
        saved.append(pw)
    found = []
    git = _is_git()
    for p in files("--staged" in sys.argv):
        rel = p.relative_to(ROOT).as_posix()
        why = private(rel) if git else None
        if why:
            found.append(f"{rel}: {why}")
            continue
        if rel in SKIP_FILES or p.suffix.lower() not in TEXT_EXT or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(v in text for v in saved):
            found.append(f"{rel}: contains one of YOUR saved API keys (or your key-page password)")
            continue
        for pat in keystore.KEY_PATTERNS:
            m = pat.search(text)
            if m and "fake" not in m.group(0).lower():
                found.append(f"{rel}: something that looks like an API key ({m.group(0)[:7]}…)")
                break
    if found:
        print("⚠ Possible leak — remove these before committing / pushing (git rm --cached <file> keeps your copy):")
        print("\n".join("  - " + f for f in found))
        sys.exit(1)
    print("No API keys or private files found in the files git would commit.")


if __name__ == "__main__":
    main()
