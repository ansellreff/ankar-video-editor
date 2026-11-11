"""Workflow state of one project: stages, gates, review documents and approval proposals.

Stages (the stepper in the chat): brief → script → style → style_test → plan → narration → build → review → export.
State: projects/<name>/docs/chat/workflow.json. Review documents live in the project's docs/ only (paths are checked);
a document the user edited is never overwritten (we keep the text we last wrote and compare)."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

STAGES = [("brief", "Brief"), ("script", "Script"), ("style", "Style & duration"), ("style_test", "Style test"),
          ("plan", "Edit plan"), ("narration", "Narration"), ("build", "Build"), ("review", "Review rounds"),
          ("export", "Cover & export")]
STAGE_IDS = [s for s, _ in STAGES]
# a tool needs these stages approved first (server-side gate; the prompt also says so)
GATES = {"style_test": ["script", "style"], "make_narration": ["script", "style"],
         "build_from_plan": ["script", "style", "plan"]}
# approving a stage marks later stages that depend on it as "needs update"
DEPENDS = {"script": ["style_test", "plan", "narration", "build"], "style": ["style_test", "plan", "narration", "build"],
           "plan": ["build"], "narration": ["build"]}


class DocError(ValueError):
    pass


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Workflow:
    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir)
        self.docs = self.dir / "docs"
        self.file = self.docs / "chat" / "workflow.json"
        self._lock = threading.RLock()
        self.data = self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("stage", "brief")
        d.setdefault("approved", {})
        d.setdefault("needs_update", [])
        d.setdefault("docs", {})
        return d

    def save(self):
        with self._lock:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.file)

    def public(self) -> dict:
        d = self.data
        return {"stage": d["stage"], "stages": [{"id": s, "label": l, "approved": s in d["approved"],
                                                 "needs_update": s in d["needs_update"], "current": s == d["stage"]}
                                                for s, l in STAGES]}

    # ------------------------------------------------------------ stages
    def approve(self, stage: str, note: str = "", files=None):
        if stage not in STAGE_IDS:
            raise ValueError(f"unknown stage {stage}")
        with self._lock:
            d = self.data
            d["approved"][stage] = {"at": time.strftime("%Y-%m-%d %H:%M"), "note": note, "files": files or []}
            if stage in d["needs_update"]:
                d["needs_update"].remove(stage)
            for later in DEPENDS.get(stage, []):          # re-approving an earlier stage → later ones need a look
                if later in d["approved"] and later not in d["needs_update"]:
                    d["needs_update"].append(later)
            i = STAGE_IDS.index(stage)
            if STAGE_IDS.index(d["stage"]) <= i:
                d["stage"] = STAGE_IDS[min(i + 1, len(STAGE_IDS) - 1)]
            self.save()

    def go_to(self, stage: str):
        if stage not in STAGE_IDS:
            raise ValueError(f"unknown stage {stage}")
        with self._lock:
            self.data["stage"] = stage
            self.save()

    def gate(self, tool: str) -> str | None:
        """None if the tool may run, else a plain reason."""
        need = [s for s in GATES.get(tool, []) if s not in self.data["approved"] or s in self.data["needs_update"]]
        if not need:
            return None
        names = dict(STAGES)
        return ("Not yet: first approve " + ", ".join(names[s] for s in need) +
                ". (Workflow rule: nothing is built before the script, the editing style and the edit plan are approved.)")

    # ------------------------------------------------------------ review documents (docs/ only)
    def doc_path(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").strip().lstrip("/")
        if rel.startswith("docs/"):
            rel = rel[5:]
        if not rel or rel.startswith("chat/") or not rel.lower().endswith((".md", ".txt")):
            raise DocError("only .md / .txt files inside the project's docs/ folder (not docs/chat/) can be used")
        p = (self.docs / rel).resolve()
        if not str(p).startswith(str(self.docs.resolve()) + os.sep):
            raise DocError("that path is outside the project's docs/ folder")
        return p

    def list_docs(self) -> list[dict]:
        out = []
        if self.docs.exists():
            for p in sorted(self.docs.rglob("*")):
                if p.is_file() and p.suffix.lower() in (".md", ".txt") and "chat" not in p.relative_to(self.docs).parts:
                    r = p.relative_to(self.docs).as_posix()
                    out.append({"path": f"docs/{r}", "size": p.stat().st_size, "edited_by_you": self.edited_by_user(r)})
        return out

    def edited_by_user(self, rel: str) -> bool:
        p = self.doc_path(rel)
        info = self.data["docs"].get(p.relative_to(self.docs).as_posix())
        if not info or not p.exists():
            return False
        return _sha(p.read_text(encoding="utf-8")) != info["sha"]

    def read_doc(self, rel: str) -> dict:
        p = self.doc_path(rel)
        if not p.exists():
            raise DocError(f"{rel} does not exist")
        text = p.read_text(encoding="utf-8")
        key = p.relative_to(self.docs).as_posix()
        info = self.data["docs"].get(key)
        res = {"path": f"docs/{key}", "text": text, "written_by": "ai" if info else "you"}
        if info and _sha(text) != info["sha"]:
            diff = list(difflib.unified_diff(info["text"].splitlines(), text.splitlines(), "my version", "your version",
                                             lineterm="", n=1))
            res["edited_by_you"] = True
            res["your_changes"] = "\n".join(diff[:160]) + ("\n… (more changes)" if len(diff) > 160 else "")
        return res

    def write_doc(self, rel: str, text: str) -> dict:
        """Create or update a review document. A file the user wrote or edited is never overwritten."""
        p = self.doc_path(rel)
        key = p.relative_to(self.docs).as_posix()
        info = self.data["docs"].get(key)
        if p.exists():
            cur = p.read_text(encoding="utf-8")
            if not info:
                raise DocError(f"{key} was written by the user — never overwrite it; write a new file "
                               f"(e.g. a new version number) instead")
            if _sha(cur) != info["sha"]:
                raise DocError(f"the user edited {key} — read it (their version is the source of truth) and write "
                               f"a NEW version file instead of overwriting")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        with self._lock:
            self.data["docs"][key] = {"sha": _sha(text), "text": text, "at": time.strftime("%Y-%m-%d %H:%M")}
            self.save()
        return {"path": f"docs/{key}", "chars": len(text)}


class Proposals:
    """Changes waiting for the user's decision. A tool that changes the video creates one and WAITS; it runs only
    when the user presses Approve (resolve(id, "approve")). Declined / stopped / expired → never runs."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self._cv = threading.Condition()

    def create(self, kind: str, payload: dict) -> dict:
        p = {"id": uuid.uuid4().hex[:10], "kind": kind, "status": "pending", "created": time.time(), **payload}
        with self._cv:
            self.items[p["id"]] = p
        return p

    def resolve(self, pid: str, action: str, value=None) -> dict:
        with self._cv:
            p = self.items.get(pid)
            if not p:
                raise KeyError("unknown or expired request")
            if p["status"] != "pending":
                raise ValueError(f"already {p['status']}")
            p["status"] = {"approve": "approved", "decline": "declined", "change": "change",
                           "answer": "answered"}.get(action, action)
            p["value"] = value
            self._cv.notify_all()
            return p

    def wait(self, pid: str, stop: threading.Event, timeout: float | None = None) -> dict:
        end = None if timeout is None else time.time() + timeout
        with self._cv:
            while True:
                p = self.items[pid]
                if p["status"] != "pending":
                    return p
                if stop.is_set():
                    p["status"] = "stopped"
                    return p
                if end is not None and time.time() > end:
                    p["status"] = "expired"
                    return p
                self._cv.wait(timeout=0.5)

    def cancel_all(self):
        with self._cv:
            for p in self.items.values():
                if p["status"] == "pending":
                    p["status"] = "stopped"
            self._cv.notify_all()

    def pending(self) -> list[dict]:
        return [p for p in self.items.values() if p["status"] == "pending"]
