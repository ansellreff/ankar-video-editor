"""Self-contained projects: projects/<name>/ holds project.json (+ autosave/, checkpoints/), its own assets/, import/,
docs/ and exports/. One Editor per opened project."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .paths import PROJECT_ASSET_DIRS, PROJECT_DOC_DIRS, PROJECTS, project_assets, project_docs, project_exports, project_import
from .project import DEFAULT_FORMAT, FORMAT_FPS, FORMATS, Editor, OpError, new_project
from .render.timeline import clip_end

RECENT = PROJECTS / ".recent.json"
FOLDER_NOTES = {
    "import": "Drop anything for this project here. It is sorted automatically (by subfolder or file name):\n"
              "  logo / brand -> assets/brand/logo     watermark -> assets/brand/watermark\n"
              "  music / bgm / song -> assets/audio/music     sfx -> assets/audio/sfx     voice / vo / narration -> assets/audio/voiceover\n"
              "  photo / pic -> assets/photos     script (.docx .pdf .md .txt) -> docs/script     storyboard -> docs/storyboard\n"
              "  other videos -> assets/video (one subfolder level is kept, e.g. 'Day 1 - Kaohsiung/clip.mp4')\n",
    "assets/video": "Footage. Make one subfolder per day or scene, e.g. 'Day 1 - Kaohsiung night', 'Day 2 - E-DA'.\n",
    "assets/photos": "Photos and stills (jpg, png, webp).\n",
    "assets/brand/logo": "Brand / sponsor logos. PNG with a transparent background, at least 1000 px wide.\n",
    "assets/brand/watermark": "Watermark image (transparent PNG, usually white or light). Turn it on in Inspector > Sequence > Watermark / logo.\n",
    "assets/audio/music": "Background music (royalty-free / licensed). Put the licence or credit text in assets/licenses.\n",
    "assets/audio/sfx": "Sound effects (whoosh, pop, click...).\n",
    "assets/audio/voiceover": "Voice recordings and narration you recorded yourself (also usable to train an AI voice).\n",
    "assets/subtitles": "Subtitle files (.srt, .ass, .vtt).\n",
    "assets/licenses": "Licences and credits for music, stock footage and fonts used in this project.\n",
    "docs/script": "Your script (.docx, .pdf, .md or .txt).\n",
    "docs/storyboard": "Storyboard images / PDF and the shot list.\n",
    "exports": "Final videos only (\"<title> - FINAL.mp4\", each with a copy of the timeline). Earlier drafts (vNN.mp4) are in "
               "draft/. Narration MP3s are in voice/, still frames in frames/.\n",
}


def ensure_folders(name: str):
    """Create the standard folder tree of a project (idempotent) with a short README in each folder."""
    root = PROJECTS / name
    dirs = ["import", "exports"] + [f"assets/{d}" for d in PROJECT_ASSET_DIRS] + [f"docs/{d}" for d in PROJECT_DOC_DIRS]
    for d in dirs:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        note = FOLDER_NOTES.get(d)
        if note and not (p / "README.txt").exists():
            (p / "README.txt").write_text(note, encoding="utf-8")


def clean_name(name: str) -> str:
    n = re.sub(r"[^\w\- ]+", "", (name or "").strip()).strip()
    if not n or n.startswith("_") or n.startswith("."):
        raise OpError("use letters, numbers, spaces, - or _ for the project name")
    return n[:60]


def _retarget(pj: Path, old: str, new: str):
    """After copying/renaming a project folder: point its asset paths and ids at projects/<new>/…"""
    from .library import asset_id
    if not pj.exists():
        return
    p = json.loads(pj.read_text(encoding="utf-8"))
    p["name"] = new
    old_pre, new_pre = f"{PROJECTS.name}/{old}/", f"{PROJECTS.name}/{new}/"
    remap = {}
    for aid, a in list(p.get("assets", {}).items()):
        path = a.get("path", "")
        if old_pre in path:
            a["path"] = path.replace(old_pre, new_pre, 1)
            remap[aid] = asset_id(a["path"])
    if remap:
        p["assets"] = {remap.get(k, k): v for k, v in p["assets"].items()}
        for c in p.get("clips", []):
            if c.get("asset") in remap:
                c["asset"] = remap[c["asset"]]
            if (c.get("meta") or {}).get("asset") in remap:
                c["meta"]["asset"] = remap[c["meta"]["asset"]]
        br = (p.get("settings") or {}).get("brand") or {}
        if br.get("asset") in remap:
            br["asset"] = remap[br["asset"]]
    pj.write_text(json.dumps(p, indent=1, ensure_ascii=False), encoding="utf-8")


class ProjectManager:
    def __init__(self, asset_info):
        self.asset_info = asset_info
        self.editors: dict[str, Editor] = {}
        PROJECTS.mkdir(parents=True, exist_ok=True)
        rec = self._recent()
        last = rec.get("last")
        names = self.names()
        if not last or last not in names:
            last = names[0] if names else "vlog"
        self.name = last
        self.editor = self._load(last)
        self._touch(last)

    # ---------------------------------------------------------------- bookkeeping
    def names(self):
        return sorted(p.name for p in PROJECTS.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "project.json").exists())

    def _recent(self):
        try:
            return json.loads(RECENT.read_text(encoding="utf-8"))
        except Exception:
            return {"recent": [], "last": None}

    def _touch(self, name):
        r = self._recent()
        r["recent"] = [name] + [n for n in r.get("recent", []) if n != name and (PROJECTS / n / "project.json").exists()][:9]
        r["last"] = name
        RECENT.write_text(json.dumps(r, indent=1), encoding="utf-8")

    def _load(self, name) -> Editor:
        if name not in self.editors:
            self.editors[name] = Editor(PROJECTS / name / "project.json", asset_info=self.asset_info)
        return self.editors[name]

    @property
    def path(self) -> Path:
        return PROJECTS / self.name / "project.json"

    @property
    def exports(self) -> Path:
        return project_exports(self.name)

    @property
    def assets(self) -> Path:
        return project_assets(self.name)

    @property
    def import_dir(self) -> Path:
        return project_import(self.name)

    @property
    def docs(self) -> Path:
        return project_docs(self.name)

    # ---------------------------------------------------------------- listing
    def list(self):
        out = []
        recent = self._recent().get("recent", [])
        for n in self.names():
            f = PROJECTS / n / "project.json"
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            first = next((c for c in sorted(p.get("clips", []), key=lambda c: c["start"]) if c.get("asset")
                          and p["assets"].get(c["asset"], {}).get("kind") in ("video", "image")), None)
            out.append({"name": n, "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes"),
                        "duration": round(max([clip_end(c) for c in p.get("clips", [])] + [0.0]), 2),
                        "clips": len(p.get("clips", [])), "format": p.get("format", {}).get("preset", "9:16"),
                        "thumb": first["asset"] if first else None, "current": n == self.name,
                        "recent": recent.index(n) if n in recent else 99})
        return out

    # ---------------------------------------------------------------- actions
    def open(self, name):
        if name not in self.names():
            raise OpError(f"no project named {name}")
        self.name = name
        ensure_folders(name)
        self.editor = self._load(name)
        self._touch(name)
        return self.editor

    def new(self, name, fmt=DEFAULT_FORMAT):
        name = clean_name(name)
        if (PROJECTS / name).exists():
            raise OpError(f"a project named {name} already exists")
        p = new_project(name)
        if fmt in FORMATS:
            w, h = FORMATS[fmt]
            p["format"].update(preset=fmt, w=w, h=h)
            if fmt in FORMAT_FPS:
                p["format"]["fps"] = FORMAT_FPS[fmt]
        (PROJECTS / name).mkdir(parents=True)
        (PROJECTS / name / "project.json").write_text(json.dumps(p, indent=1), encoding="utf-8")
        ensure_folders(name)
        return self.open(name)

    def save_as(self, new_name):
        """Copy the whole project (edit + its assets/docs; not exports/autosaves) under a new name and open it."""
        name = self.name
        self.duplicate(name, new_name, exports=False)
        return self.open(clean_name(new_name))

    def duplicate(self, name, new_name, exports=False):
        """Copy a project folder. Asset paths inside project.json are rewritten to the copy's own assets/ folder."""
        new_name = clean_name(new_name)
        if (PROJECTS / new_name).exists():
            raise OpError(f"a project named {new_name} already exists")
        if name == self.name:
            self.editor.save()
        skip = ["autosave", "checkpoints"] + ([] if exports else ["exports"])
        shutil.copytree(PROJECTS / name, PROJECTS / new_name, ignore=shutil.ignore_patterns(*skip))
        _retarget(PROJECTS / new_name / "project.json", name, new_name)
        ensure_folders(new_name)
        return new_name

    def rename(self, name, new_name):
        new_name = clean_name(new_name)
        if (PROJECTS / new_name).exists():
            raise OpError(f"a project named {new_name} already exists")
        ed = self.editors.pop(name, None)
        if ed:
            ed.save()
        (PROJECTS / name).rename(PROJECTS / new_name)
        _retarget(PROJECTS / new_name / "project.json", name, new_name)
        if ed:
            ed = Editor(PROJECTS / new_name / "project.json", asset_info=self.asset_info)
            self.editors[new_name] = ed
        if self.name == name:
            self.name = new_name
            self.editor = self._load(new_name)
        self._touch(self.name)
        return new_name

    def delete(self, name):
        trash = PROJECTS / "_trash"
        trash.mkdir(exist_ok=True)
        self.editors.pop(name, None)
        shutil.move(str(PROJECTS / name), str(trash / f"{name}-{datetime.now():%Y%m%d-%H%M%S}"))
        if self.name == name:
            names = self.names()
            if names:
                self.open(names[0])
            else:
                self.new("Untitled")
        return self.name

    # ---------------------------------------------------------------- checkpoints (named saves)
    def checkpoint(self, label=""):
        d = PROJECTS / self.name / "checkpoints"
        d.mkdir(exist_ok=True)
        lab = re.sub(r"[^\w\- ]+", "", label).strip()[:40]
        f = d / f"{datetime.now():%Y%m%d-%H%M%S}{('_' + lab) if lab else ''}.json"
        f.write_text(json.dumps(self.editor.p, indent=1, ensure_ascii=False), encoding="utf-8")
        return f.name

    def checkpoints(self):
        d = PROJECTS / self.name / "checkpoints"
        return [{"file": f.name, "time": f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]} {f.stem[9:11]}:{f.stem[11:13]}",
                 "label": f.stem[16:].replace("_", " ")} for f in sorted(d.glob("*.json"), reverse=True)] if d.exists() else []

    def copy_assets_from(self, other: str, subdirs=("brand",)) -> list[str]:
        """Copy folders (default: brand logos/watermarks) from another project into this one (existing files kept)."""
        copied = []
        for sd in subdirs:
            src = project_assets(other) / sd
            if not src.exists():
                continue
            for f in src.rglob("*"):
                if f.is_file() and f.name != "README.txt":
                    dst = self.assets / sd / f.relative_to(src)
                    if not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, dst)
                        copied.append(dst.name)
        return copied

    def revert(self, file):
        f = PROJECTS / self.name / "checkpoints" / Path(file).name
        if not f.exists():
            raise OpError("checkpoint not found")
        self.editor.load_snapshot(json.loads(f.read_text(encoding="utf-8")), f"Revert to {f.stem}")
