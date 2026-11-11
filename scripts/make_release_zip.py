"""Build the download: dist/AnKar-Video-Editor-<version>.zip (+ .sha256).

Contents = the files git publishes (so nothing private can end up in it), minus developer-only parts (tests, website,
git files). Files sit at the zip's top level: "Extract all" makes a new folder, and an update can be unzipped straight
into an existing AnKar folder. Run locally or in GitHub Actions:  python -m scripts.make_release_zip"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.version import VERSION  # noqa: E402
from scripts.check_secrets import private  # noqa: E402

DEV_ONLY = ("tests/", "website/", ".github/", ".githooks/", ".gitignore", ".gitattributes", "start.ps1", "scripts/legacy/")
# must be in every download
REQUIRED = ("Setup AnKar Video Editor.bat", "Start AnKar Video Editor.bat", "Update AnKar Video Editor.bat",
            "requirements-lock.txt", "requirements-tts-lock.txt", "Install local AI voice (optional).bat", "app/server.py", "app/version.py", "web/index.html", "CHANGELOG.md", "LICENSE",
            "CREDITS.md", "README.md", "projects/Demo/project.json", "scripts/selftest.py")


def publishable() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted({p for p in out.splitlines() if p and (ROOT / p).is_file()})


def main() -> Path:
    files = [p for p in publishable() if not p.startswith(DEV_ONLY)]
    leaks = [f"{p}: {private(p)}" for p in files if private(p)]
    if leaks:
        sys.exit("Refusing to build — private files would be in the zip:\n  " + "\n  ".join(leaks))
    missing = [r for r in REQUIRED if r not in files]
    if missing:
        sys.exit("Missing from the download: " + ", ".join(missing))
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"AnKar-Video-Editor-{VERSION}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(ROOT / p, p)
        for d in ("config", "cache", "models"):                 # empty folders Setup / the app fill
            z.writestr(f"{d}/README.txt", {"config": "Your settings, encrypted API keys and password hash (stays on this PC).\n",
                                           "cache": "Preview copies and temporary files (safe to delete).\n",
                                           "models": "The subtitle model (downloaded by Setup).\n"}[d])
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / (out.name + ".sha256")).write_text(f"{sha}  {out.name}\n", encoding="ascii")
    print(f"{out.relative_to(ROOT)}: {len(files)} files, {out.stat().st_size / 1e6:.1f} MB, sha256 {sha}")
    return out


if __name__ == "__main__":
    main()
