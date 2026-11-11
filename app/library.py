"""Asset library: the OPEN project's assets/ + the shared library/ (no upload needed), sorts the project's import/,
builds derivatives (proxies, filmstrips, waveforms) in the background."""
from __future__ import annotations

import hashlib
import json
import queue
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

from . import media
from .paths import FONTS, LIBRARY, LIBRARY_HIDDEN, MEDIA_CACHE, ROOT, project_assets, project_import, rel

SKIP_NAMES = {".keep", "desktop.ini", "thumbs.db", "readme.txt"}
DOC_EXT = {".docx", ".doc", ".pdf", ".md", ".txt", ".rtf", ".odt", ".pages", ".xlsx", ".csv"}
# keyword (in an import/ subfolder name or the file name) → destination inside the project; checked in this order
ROUTES = [
    (r"storyboard|shot.?list", "docs/storyboard"),
    (r"script|naskah", "docs/script"),
    (r"watermark", "assets/brand/watermark"),
    (r"logo|brand", "assets/brand/logo"),
    (r"licen[cs]e|credit", "assets/licenses"),
    (r"\bbgm\b|music|song|lagu", "assets/audio/music"),
    (r"\bsfx\b|sound.?effect|whoosh|swoosh", "assets/audio/sfx"),
    (r"voice|narrat|\bvo\b|voiceover|rekaman", "assets/audio/voiceover"),
    (r"photo|pic|foto|img|image", "assets/photos"),
    (r"sub(title)?s?\b|caption", "assets/subtitles"),
]
BY_KIND = {"video": "assets/video", "image": "assets/photos", "audio": "assets/audio/music", "subtitle": "assets/subtitles",
           "font": None, "doc": "docs/script"}
KIND_OK = {   # which kinds may land in which destination (a keyword never sends a video into the music folder)
    "docs/storyboard": {"doc", "image", "video"}, "docs/script": {"doc"}, "assets/brand/watermark": {"image", "video"},
    "assets/brand/logo": {"image", "video"}, "assets/licenses": {"doc"}, "assets/audio/music": {"audio"},
    "assets/audio/sfx": {"audio"}, "assets/audio/voiceover": {"audio", "video"}, "assets/photos": {"image"},
    "assets/subtitles": {"subtitle"},
}


def route(path_in_import: Path, kind: str) -> str | None:
    """Destination (relative to the project folder) for a file dropped into import/ — keyword first, then type."""
    words = " ".join(list(path_in_import.parts[:-1]) + [path_in_import.stem]).lower().replace("_", " ").replace("-", " ")
    for pat, dest in ROUTES:
        if re.search(pat, words) and kind in KIND_OK.get(dest, set()):
            return dest
    return BY_KIND.get(kind)


def kind_of(p: Path) -> str | None:
    k = media.kind_of(p)
    if k is None and p.suffix.lower() in DOC_EXT:
        return "doc"
    return k


def asset_id(relpath: str) -> str:
    return hashlib.sha1(relpath.lower().encode()).hexdigest()[:10]


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    i = 2
    while True:
        cand = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not cand.exists():
            return cand
        i += 1


class Library:
    def __init__(self, notify=None, project=None):
        self.notify = notify or (lambda kind, data: None)
        self.assets: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.jobs: queue.Queue = queue.Queue()
        self.pending: set[str] = set()
        self.project = project
        threading.Thread(target=self._worker, daemon=True, name="media-worker").start()

    def set_project(self, name: str):
        """Switch the library to another project's assets/ (the shared library/ stays)."""
        self.project = name
        return self.scan()

    @property
    def assets_dir(self) -> Path | None:
        return project_assets(self.project) if self.project else None

    @property
    def import_dir(self) -> Path | None:
        return project_import(self.project) if self.project else None

    def roots(self):
        """(folder to scan, label prefix for the Project panel, scope)."""
        out = []
        if self.assets_dir:
            out.append((self.assets_dir, "", "project"))
        out.append((LIBRARY, "library/", "library"))
        return out

    # ---------------------------------------------------------------- import/ drop zone (per project)
    def sort_import(self) -> list[dict]:
        moved = []
        imp = self.import_dir
        if not imp or not imp.exists():
            return moved
        proj = imp.parent
        for p in sorted(imp.rglob("*")):
            if not p.is_file() or p.name.lower() in SKIP_NAMES or p.name.startswith("."):
                continue
            k = kind_of(p)
            if k is None or _busy(p):
                continue
            inner = p.relative_to(imp)
            dest_dir = route(inner, k)
            if k == "font":                                   # fonts are shared: they go to the library
                dest = _unique(FONTS / p.name)
            elif dest_dir is None:
                continue
            else:
                sub = Path(*inner.parts[:-1]) if (dest_dir == "assets/video" and len(inner.parts) > 1) else Path()
                dest = _unique(proj / dest_dir / sub / p.name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            src_rel = rel(p)
            shutil.move(str(p), str(dest))
            moved.append({"from": src_rel, "to": rel(dest), "kind": k})
        for d in sorted((x for x in imp.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
            try:
                d.rmdir()                                     # tidy empty subfolders left in import/
            except OSError:
                pass
        if moved:
            short = [m["to"].split("/", 2)[-1] for m in moved]
            self.notify("toast", {"text": f"Sorted {len(moved)} file{'s' if len(moved) > 1 else ''} from import/",
                                  "detail": short})
        return moved

    # ---------------------------------------------------------------- scan
    def scan(self) -> dict[str, dict]:
        found, todo = {}, []
        files = []
        for root, prefix, scope in self.roots():
            if not root.exists():
                continue
            for p in sorted(root.rglob("*")):
                if not p.is_file() or p.name.lower() in SKIP_NAMES or p.name.startswith("."):
                    continue
                sub = p.relative_to(root)
                if scope == "library" and sub.parts and sub.parts[0] in LIBRARY_HIDDEN:
                    continue                                  # internal: reverbs, voice-training samples, fonts, LUTs
                files.append((p, sub, prefix, scope))
        for p, sub, prefix, scope in files:
            k = media.kind_of(p)
            if k is None or k == "font":
                continue
            r = rel(p)
            aid = asset_id(r)
            st = p.stat()
            folder = (prefix + sub.parent.as_posix()).rstrip("/") if sub.parent.as_posix() != "." else prefix.rstrip("/")
            entry = {"id": aid, "path": r, "name": p.name, "folder": folder, "kind": k, "scope": scope,
                     "size": st.st_size, "mtime": int(st.st_mtime)}
            with self.lock:
                old = self.assets.get(aid)
            if old and old["size"] == entry["size"] and old["mtime"] == entry["mtime"] and old.get("status") in ("queued", "processing"):
                found[aid] = old                      # already in the pipeline
                continue
            cached = self._cached(aid, entry)
            if cached:
                entry.update(cached)
            elif k in ("video", "audio", "image"):
                entry["status"] = "queued"
                todo.append(aid)
            else:
                entry["status"] = "ready"
            found[aid] = entry
        with self.lock:
            self.assets = found
        for aid in todo:                              # only after the entries are visible to the worker
            self._enqueue(aid)
        self.notify("assets", None)
        return found

    def register(self, path: Path) -> dict:
        """Add one file right now (probe synchronously) — used for generated assets."""
        r = rel(path)
        aid = asset_id(r)
        st = path.stat()
        folder, scope = "", "library"
        for root, prefix, sc in self.roots():
            try:
                sub = path.resolve().relative_to(root.resolve())
                folder, scope = (prefix + sub.parent.as_posix()).rstrip("/") if sub.parent.as_posix() != "." else prefix.rstrip("/"), sc
                break
            except ValueError:
                continue
        entry = {"id": aid, "path": r, "name": path.name, "folder": folder, "kind": media.kind_of(path), "scope": scope,
                 "size": st.st_size, "mtime": int(st.st_mtime)}
        cached = self._cached(aid, entry)
        if cached:
            entry.update(cached)
        else:
            entry.update(meta=media.probe(path), status="queued")
            self._enqueue(aid)
        with self.lock:
            self.assets[aid] = entry
        self.notify("asset", dict(entry))
        return entry

    def get(self, aid):
        with self.lock:
            return self.assets.get(aid)

    def list(self):
        with self.lock:
            return list(self.assets.values())

    # ---------------------------------------------------------------- cache
    @staticmethod
    def cache_dir(aid) -> Path:
        return MEDIA_CACHE / aid

    def _cached(self, aid, entry):
        f = self.cache_dir(aid) / "info.json"
        if not f.exists():
            return None
        try:
            info = json.loads(f.read_text())
        except Exception:
            return None
        if info.get("size") != entry["size"] or info.get("mtime") != entry["mtime"]:
            return None
        return {"meta": info["meta"], "derived": info.get("derived", {}), "status": info.get("status", "ready"),
                "error": info.get("error")}

    def _enqueue(self, aid):
        if aid not in self.pending:
            self.pending.add(aid)
            self.jobs.put(aid)

    def _worker(self):
        while True:
            aid = self.jobs.get()
            self.pending.discard(aid)
            entry = self.get(aid)
            if not entry:
                continue
            p = ROOT / entry["path"]
            if not p.exists():
                continue
            if _busy(p):                      # still being copied in: retry shortly
                time.sleep(1.0)
                self._enqueue(aid)
                continue
            d = self.cache_dir(aid)
            status, err, meta, derived = "ready", None, {}, {}
            try:
                self._set(aid, status="processing", progress=0.0)
                meta = media.probe(p)
                last = [0.0]

                def prog(x):
                    if x - last[0] >= 0.05:
                        last[0] = x
                        self._set(aid, progress=round(x, 2))
                derived = media.process(p, d, meta, progress=prog)
            except Exception as e:  # noqa: BLE001 - surface any decode problem in the UI
                status, err = "error", f"{type(e).__name__}: {e}"
                traceback.print_exc()
            d.mkdir(parents=True, exist_ok=True)
            (d / "info.json").write_text(json.dumps({"size": entry["size"], "mtime": entry["mtime"], "meta": meta,
                                                     "derived": derived, "status": status, "error": err}))
            self._set(aid, status=status, meta=meta, derived=derived, error=err, progress=None)

    def _set(self, aid, **kw):
        with self.lock:
            e = self.assets.get(aid)
            if e is None:
                return
            e.update({k: v for k, v in kw.items()})
            snap = dict(e)
        self.notify("asset", snap)


def _busy(p: Path) -> bool:
    """True while a file is still being written (size changing or locked)."""
    try:
        s1 = p.stat().st_size
        time.sleep(0.15)
        if p.stat().st_size != s1:
            return True
        with open(p, "rb"):
            pass
        return False
    except PermissionError:
        return True
    except OSError:
        return True
