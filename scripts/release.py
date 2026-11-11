"""Make a release:  python -m scripts.release 1.1.0      (first write the notes in CHANGELOG.md under "## 1.1.0 — date")

1. checks the version (newer than the last tag) and that CHANGELOG.md starts with its notes
2. sets app/version.py and website/api/_lib/releases.json (the website's version list + notes)
3. runs the unit tests and the leak check (API keys / private files)
4. commits "Release X.Y.Z" and tags vX.Y.Z
Then:  git push && git push origin vX.Y.Z   → GitHub Actions builds the zip + the Release; Vercel updates the site.
Only step 2:  python -m scripts.release --sync-site"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import releasenotes  # noqa: E402
from app.version import parse  # noqa: E402

VERSION_PY = ROOT / "app" / "version.py"
SITE_JSON = ROOT / "website" / "api" / "_lib" / "releases.json"


def sync_site():
    rels = releasenotes.load()
    old = json.loads(SITE_JSON.read_text(encoding="utf-8")) if SITE_JSON.exists() else {}
    SITE_JSON.write_text(json.dumps({"repo": old.get("repo", ""), "releases": rels}, indent=1, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(f"website releases.json: {len(rels)} versions, latest {rels[0]['version'] if rels else '-'}")


def git(*a, check=True) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=check).stdout.strip()


def main():
    if "--sync-site" in sys.argv:
        return sync_site()
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    v = sys.argv[1].lstrip("v")
    parse(v)
    tags = [t.lstrip("v") for t in git("tag", "--list", "v*").split()]
    if f"{v}" in tags:
        sys.exit(f"v{v} already exists.")
    if tags and parse(v) <= max(parse(t) for t in tags):
        sys.exit(f"{v} is not newer than the last release ({max(tags, key=parse)}).")
    rels = releasenotes.load()
    if not rels or rels[0]["version"] != v or not rels[0]["notes"] or not rels[0]["date"]:
        sys.exit(f'CHANGELOG.md must start with "## {v} — YYYY-MM-DD" and at least one "- note".')
    src = VERSION_PY.read_text(encoding="utf-8")
    VERSION_PY.write_text(re.sub(r'^VERSION = ".*?"', f'VERSION = "{v}"', src, flags=re.M), encoding="utf-8")
    sync_site()
    if "--no-tests" not in sys.argv:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-x"], cwd=ROOT)
        if r.returncode:
            sys.exit("Tests failed — nothing was committed.")
    r = subprocess.run([sys.executable, "-m", "scripts.check_secrets"], cwd=ROOT)
    if r.returncode:
        sys.exit("Leak check failed — nothing was committed.")
    git("add", "-A")
    r = subprocess.run([sys.executable, "-m", "scripts.check_secrets", "--staged"], cwd=ROOT)
    if r.returncode:
        sys.exit("Leak check on the staged files failed — nothing was committed (git reset to unstage).")
    git("commit", "-m", f"Release {v}", check=False)
    git("tag", "-a", f"v{v}", "-m", f"AnKar Video Editor {v}")
    print(f"\nReady. Publish with:\n  git push && git push origin v{v}")


if __name__ == "__main__":
    main()
