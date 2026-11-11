"""All workspace locations in one place.

Layout (self-contained projects):
  projects/<name>/            one folder = one complete project
    project.json  autosave/  checkpoints/
    import/                   drop zone for this project (auto-sorted into assets/ and docs/)
    assets/{video, photos, brand/logo, brand/watermark, audio/music, audio/sfx, audio/voiceover, subtitles, licenses}
    docs/{script, storyboard}
    exports/                  vNN.mp4 (+ timeline copy), voice/ MP3s, frames/
  library/                    shared by all projects: voices, fonts, luts, ambience, ir, sfx, samples, generated
VLOG_PROJECTS_DIR / VLOG_EXPORTS_DIR override where projects live (the test server on port 8766 uses them, so automated
tests never touch the user's real projects)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "library"
CACHE = ROOT / "cache"
MEDIA_CACHE = CACHE / "media"
WORK = CACHE / ("work" if not os.environ.get("VLOG_PROJECTS_DIR") else "work_test")
PROJECTS = Path(os.environ.get("VLOG_PROJECTS_DIR") or ROOT / "projects")
EFFECTS = ROOT / "effects"
WEB = ROOT / "web"
MODELS = ROOT / "models"

# shared library (all projects)
FONTS = LIBRARY / "fonts"
VOICES = LIBRARY / "voices"
LUTS = LIBRARY / "luts"
AMBIENCE = LIBRARY / "ambience"
IRS = LIBRARY / "ir"
SAMPLES = LIBRARY / "samples"
GENERATED = LIBRARY / "generated"
GENERATED_SFX = GENERATED / "sfx"                 # typed-intro keyboard tracks
GENERATED_NARRATION = GENERATED / "narration"     # AI narration (cache, shared by all projects)
LIBRARY_HIDDEN = ("ir", "voices", "fonts", "luts", "reports")   # internal: never listed as clips in the Project panel

# per-project folders
PROJECT_ASSET_DIRS = ("video", "photos", "brand/logo", "brand/watermark", "audio/music", "audio/sfx", "audio/voiceover",
                      "subtitles", "licenses")
PROJECT_DOC_DIRS = ("script", "storyboard")


def project_dir(name: str) -> Path:
    return PROJECTS / name


def project_assets(name: str) -> Path:
    return PROJECTS / name / "assets"


def project_import(name: str) -> Path:
    return PROJECTS / name / "import"


def project_docs(name: str) -> Path:
    return PROJECTS / name / "docs"


def project_exports(name: str) -> Path:
    return PROJECTS / name / "exports"


def rel(p) -> str:
    """Workspace-relative POSIX path (what project.json stores)."""
    return Path(p).resolve().relative_to(ROOT).as_posix()


def absp(r: str) -> Path:
    p = (ROOT / r).resolve()
    if ROOT not in p.parents and p != ROOT:
        raise ValueError(f"path escapes workspace: {r}")
    return p


for d in (LIBRARY, MEDIA_CACHE, WORK, PROJECTS, GENERATED_SFX, GENERATED_NARRATION):
    d.mkdir(parents=True, exist_ok=True)
