"""One-time migration to self-contained projects (2026-11-06).

Before: one shared assets/ + import/ + exports/<project>/.
After:  projects/<name>/{assets, import, docs, exports}  +  library/ (shared: voices, fonts, luts, ambience, ir, sfx,
        samples, generated, reports).
Everything is KEPT: the user's footage, voice recordings and old subtitles go into the existing "vlog" project; demo
clips become library/samples; exports move into each project's exports/. Every project.json (+ autosave/, checkpoints/,
export snapshots) gets its paths and path-derived asset ids rewritten; media-cache folders are renamed so proxies are
reused. JSON files are backed up to cache/trash/<time>_migration/ and every move is logged there (moves.json).

python scripts/migrate_projects.py            dry run (prints the plan)
python scripts/migrate_projects.py --apply    do it (stop the editor first)
python scripts/migrate_projects.py --apply --new "Having Fun in Taiwan"   …and create + open a fresh empty project
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.library import asset_id  # noqa: E402

OLD = ROOT / "assets"
ARCHIVE = "vlog"                      # existing project that receives the user's earlier media
# old prefix → new prefix (most specific first)
PREFIXES = [
    ("assets/video/_samples/", "library/samples/"),
    ("assets/audio/voiceover/generated/", "library/generated/narration/"),
    ("assets/audio/sfx/generated/", "library/generated/sfx/"),
    ("assets/audio/sfx/keyboard/", "library/sfx/keyboard/"),
    ("assets/audio/ambience/", "library/ambience/"),
    ("assets/audio/ir/", "library/ir/"),
    ("assets/voices/", "library/voices/"),
    ("assets/fonts/", "library/fonts/"),
    ("assets/luts/", "library/luts/"),
    ("assets/video/", f"projects/{ARCHIVE}/assets/video/"),
    ("assets/audio/voiceover/", f"projects/{ARCHIVE}/assets/audio/voiceover/"),
    ("assets/audio/music/", f"projects/{ARCHIVE}/assets/audio/music/"),
    ("assets/audio/sfx/", f"projects/{ARCHIVE}/assets/audio/sfx/"),
    ("assets/images/", f"projects/{ARCHIVE}/assets/photos/"),
    ("assets/subtitles/", f"projects/{ARCHIVE}/assets/subtitles/"),
]


def new_path(old: str) -> str | None:
    for a, b in PREFIXES:
        if old.startswith(a):
            return b + old[len(a):]
    return None


def rewrite(o, n=None):
    """Replace old asset paths in every string of a JSON value. Returns (value, count)."""
    n = n if n is not None else [0]
    if isinstance(o, dict):
        return {k: rewrite(v, n)[0] for k, v in o.items()}, n[0]
    if isinstance(o, list):
        return [rewrite(v, n)[0] for v in o], n[0]
    if isinstance(o, str):
        p = new_path(o)
        if p:
            n[0] += 1
            return p, n[0]
    return o, n[0]


def remap_project(p: dict) -> tuple[dict, int, dict]:
    """Paths + path-derived asset ids. Returns (project, changes, {old_id: new_id})."""
    p, n = rewrite(p)
    remap = {}
    for aid, a in list((p.get("assets") or {}).items()):
        nid = asset_id(a.get("path", ""))
        if nid != aid:
            remap[aid] = nid
    if remap:
        p["assets"] = {remap.get(k, k): v for k, v in p["assets"].items()}
        for c in p.get("clips", []):
            if c.get("asset") in remap:
                c["asset"] = remap[c["asset"]]
            if (c.get("meta") or {}).get("asset") in remap:
                c["meta"]["asset"] = remap[c["meta"]["asset"]]
    return p, n, remap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--new", default=None, help="create and open this fresh empty project afterwards")
    args = ap.parse_args()
    dry = not args.apply
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "cache" / "trash" / f"{stamp}_migration"
    moves, id_map = [], {}

    def move(src: Path, dst: Path):
        if not src.exists():
            return
        moves.append([str(src.relative_to(ROOT)), str(dst.relative_to(ROOT))])
        if dry:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and src.is_dir():                       # merge folders
            for f in src.rglob("*"):
                if f.is_file():
                    t = dst / f.relative_to(src)
                    t.parent.mkdir(parents=True, exist_ok=True)
                    if not t.exists():
                        shutil.move(str(f), str(t))
            shutil.rmtree(src, ignore_errors=True)
        elif not dst.exists():
            shutil.move(str(src), str(dst))

    # ---- 1. which files move where (to remap media-cache ids)
    if OLD.exists():
        for f in OLD.rglob("*"):
            if f.is_file():
                r = f.relative_to(ROOT).as_posix()
                np_ = new_path(r)
                if np_:
                    id_map[asset_id(r)] = asset_id(np_)
    # ---- 2. rewrite JSON (projects, autosaves, checkpoints, export snapshots, library metadata)
    jsons = []
    projects = ROOT / "projects"
    for pd in sorted(d for d in projects.iterdir() if d.is_dir() and not d.name.startswith(".")) if projects.exists() else []:
        jsons += [f for f in pd.rglob("*.json")]
    exports = ROOT / "exports"
    if exports.exists():
        jsons += list(exports.rglob("*.project.json"))
    for meta in ("audio/ambience/ambience.json", "audio/ir/spaces.json"):
        if (OLD / meta).exists():
            jsons.append(OLD / meta)
    if (OLD / "voices").exists():
        jsons += list((OLD / "voices").rglob("voice.json"))
    total = 0
    for f in jsons:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        is_project = isinstance(data, dict) and "clips" in data and "assets" in data
        new, n, remap = remap_project(data) if is_project else (*rewrite(data), {})
        if n or remap:
            total += n
            print(f"  rewrite {f.relative_to(ROOT)}: {n} path(s){f', {len(remap)} asset id(s)' if remap else ''}")
            if not dry:
                b = backup / "json" / f.relative_to(ROOT)
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, b)
                f.write_text(json.dumps(new, indent=1, ensure_ascii=False), encoding="utf-8")
    # ---- 3. move files: shared → library/, the rest → the archive project
    for a, b in PREFIXES:
        move(ROOT / a.rstrip("/"), ROOT / b.rstrip("/"))
    imp = ROOT / "import"
    if imp.exists():
        for f in imp.iterdir():
            if f.name != ".keep":
                move(f, ROOT / "projects" / ARCHIVE / "import" / f.name)
    # exports → projects/<name>/exports (non-project folders: intro tests → vlog, voice tests → library/reports)
    if exports.exists():
        for d in sorted(exports.iterdir()):
            if not d.is_dir():
                continue
            if (projects / d.name / "project.json").exists():
                move(d, projects / d.name / "exports")
            elif d.name == "voice_tests":
                move(d, ROOT / "library" / "reports" / "voice_tests")
            else:
                move(d, projects / ARCHIVE / "exports" / d.name)
    # ---- 4. media cache: keep proxies/thumbnails under the new ids
    mc = ROOT / "cache" / "media"
    renamed = 0
    for old_id, new_id in id_map.items():
        if old_id != new_id and (mc / old_id).exists() and not (mc / new_id).exists():
            renamed += 1
            if not dry:
                (mc / old_id).rename(mc / new_id)
    print(f"\n{'DRY RUN — nothing changed. ' if dry else ''}{len(moves)} folder/file moves, {total} paths rewritten, {renamed} cache folders renamed")
    for s, d in moves:
        print(f"  move {s}  →  {d}")
    if dry:
        return
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "moves.json").write_text(json.dumps({"moves": moves, "ids": id_map}, indent=1), encoding="utf-8")
    # leftovers of the old layout (only empty folders / .keep files are removed)
    for top in (OLD, imp, exports):
        if top.exists():
            for f in sorted(top.rglob("*"), key=lambda x: -len(x.parts)):
                if f.is_file() and f.name in (".keep", "desktop.ini", "Thumbs.db"):
                    f.unlink()
                elif f.is_dir():
                    try:
                        f.rmdir()
                    except OSError:
                        pass
            try:
                top.rmdir()
                print(f"removed empty {top.name}/")
            except OSError:
                print(f"kept {top.name}/ (not empty): {[x.name for x in top.iterdir()]}")
    # ---- 5. standard folders for every project, then the fresh project
    from app.projects import ensure_folders
    for pd in sorted(d for d in projects.iterdir() if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "project.json").exists()):
        ensure_folders(pd.name)
    if args.new:
        from app.project import new_project
        name = args.new
        if not (projects / name).exists():
            (projects / name).mkdir(parents=True)
            (projects / name / "project.json").write_text(json.dumps(new_project(name), indent=1), encoding="utf-8")
        ensure_folders(name)
        rec_f = projects / ".recent.json"
        try:
            rec = json.loads(rec_f.read_text(encoding="utf-8"))
        except Exception:
            rec = {"recent": []}
        rec["recent"] = [name] + [n for n in rec.get("recent", []) if n != name]
        rec["last"] = name
        rec_f.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        print(f"created and selected the fresh project “{name}”")
    print(f"backup + move log: {backup.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
