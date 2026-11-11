"""AI Editor sessions: chats per project, one running turn at a time, approval cards / questions that wait for the
editor, live updates to the browser (SSE "assistant"), usage and cost.

Chats: projects/<name>/docs/chat/<id>.json {id, title, created, model, messages (API format), display (UI items),
usage}. Project totals: docs/chat/usage.json. Images shown in the chat: docs/chat/img/<sha>.jpg."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
import uuid
from pathlib import Path

from ..paths import PROJECTS, rel
from . import settings as cfg
from .client import TurnLoop
from .http import Http
from .prompt import SYSTEM
from .style import StyleSheet
from .tools import TOOL_KINDS, ToolError, Tools, api_tools
from .workflow import Proposals, Workflow


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


class Chat:
    def __init__(self, project: str, cid: str | None = None):
        self.project = project
        self.dir = PROJECTS / project / "docs" / "chat"
        if cid and (self.dir / f"{cid}.json").exists():
            d = json.loads((self.dir / f"{cid}.json").read_text(encoding="utf-8"))
            for it in d.get("display", []):          # cards left open by an earlier session can't be answered any more
                if it.get("status") == "pending":
                    it["status"] = "expired"
        else:
            d = {"id": cid or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4], "title": "New chat",
                 "created": _now(), "messages": [], "display": [], "usage": {"input": 0, "output": 0, "cache_write": 0,
                                                                            "cache_read": 0, "cost": 0.0}}
        self.d = d
        self.lock = threading.RLock()

    @property
    def id(self):
        return self.d["id"]

    def save(self):
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            f = self.dir / f"{self.id}.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, f)

    def public(self):
        return {k: self.d[k] for k in ("id", "title", "created", "display", "usage")}


class Ctx:
    """What the tools see: the project, workflow, style sheet, server API, and ways to ask the editor."""

    def __init__(self, svc: "Assistant", chat: Chat, project: str, stop: threading.Event):
        self.svc, self.chat, self.project, self.stop = svc, chat, project, stop
        self.pdir = PROJECTS / project
        self.wf = Workflow(self.pdir)
        self.style = StyleSheet(self.pdir, self.wf)
        self.http = Http(svc.base)

    # --- chat output
    def activity(self, text, link=None):
        self.svc.add_item(self.chat, {"kind": "activity", "text": text, **({"link": link} if link else {})})

    def show_image(self, data: bytes, caption=""):
        url = self.svc.save_image(self.project, data)
        self.svc.add_item(self.chat, {"kind": "image", "url": url, "caption": caption})

    # --- approvals and questions (block until the editor answers or Stop)
    def propose(self, kind, title, summary="", details=None, cost=None, length=None, actions=("approve", "decline", "change")):
        p = self.svc.proposals.create("proposal", {"chat": self.chat.id, "pkind": kind})
        item = self.svc.add_item(self.chat, {"kind": "proposal", "pid": p["id"], "pkind": kind, "title": title,
                                             "summary": summary, "details": list(details or [])[:40], "cost": cost,
                                             "length": length, "actions": list(actions), "status": "pending"})
        res = self.svc.proposals.wait(p["id"], self.stop)
        self.svc.update_item(self.chat, item["i"], {"status": res["status"], "note": res.get("value")})
        return res

    def ask(self, kind, payload):
        p = self.svc.proposals.create(kind, {"chat": self.chat.id})
        item = self.svc.add_item(self.chat, {"kind": kind, "pid": p["id"], **payload, "status": "pending"})
        res = self.svc.proposals.wait(p["id"], self.stop)
        self.svc.update_item(self.chat, item["i"], {"status": res["status"], "answer": res.get("value")})
        if res["status"] != "answered":
            return f"(no answer: {res['status']})"
        return res.get("value")


class Assistant:
    def __init__(self, emit, base_url: str, client_factory=None):
        self.emit_raw, self.base = emit, base_url
        self.client_factory = client_factory or self._anthropic
        self.proposals = Proposals()
        self.lock = threading.RLock()
        self.running: dict | None = None             # {chat, project, thread, stop}
        self.chats: dict[tuple, Chat] = {}

    @staticmethod
    def _anthropic():
        import anthropic
        key = cfg.api_key()
        if not key:
            raise RuntimeError("no key")
        return anthropic.Anthropic(api_key=key, max_retries=2, timeout=900)

    # ------------------------------------------------------------ chats
    def get_chat(self, project: str, cid: str | None) -> Chat:
        with self.lock:
            if cid and (project, cid) in self.chats:
                return self.chats[(project, cid)]
            c = Chat(project, cid)
            self.chats[(project, c.id)] = c
            return c

    def list_chats(self, project: str) -> list[dict]:
        d = PROJECTS / project / "docs" / "chat"
        out = []
        if d.exists():
            for f in sorted(d.glob("*.json"), key=lambda p: -p.stat().st_mtime):
                if f.name in ("workflow.json", "usage.json"):
                    continue
                try:
                    j = json.loads(f.read_text(encoding="utf-8"))
                    out.append({"id": j["id"], "title": j.get("title"), "created": j.get("created"),
                                "cost": round(j.get("usage", {}).get("cost", 0), 4)})
                except (OSError, ValueError, KeyError):
                    continue
        return out

    def project_usage(self, project: str) -> dict:
        f = PROJECTS / project / "docs" / "chat" / "usage.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"cost": 0.0, "input": 0, "output": 0, "cache_write": 0, "cache_read": 0}

    def _add_project_usage(self, project, u, cost):
        tot = self.project_usage(project)
        for k, src in (("input", "input_tokens"), ("output", "output_tokens"), ("cache_write", "cache_creation_input_tokens"),
                       ("cache_read", "cache_read_input_tokens")):
            tot[k] = tot.get(k, 0) + int(u.get(src) or 0)
        tot["cost"] = round(tot.get("cost", 0.0) + cost, 6)
        f = PROJECTS / project / "docs" / "chat" / "usage.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(tot), encoding="utf-8")
        return tot

    # ------------------------------------------------------------ chat items → browser
    def emit(self, chat: Chat, op: str, **data):
        self.emit_raw("assistant", {"project": chat.project, "chat": chat.id, "op": op, **data})

    def add_item(self, chat: Chat, item: dict) -> dict:
        from ..keystore import redact
        item = {k: (redact(v) if isinstance(v, str) else v) for k, v in item.items()}   # never store / show a key
        with chat.lock:
            item = {"i": len(chat.d["display"]), "t": _now(), **item}
            chat.d["display"].append(item)
            chat.save()
        self.emit(chat, "item", item=item)
        return item

    def update_item(self, chat: Chat, i: int, patch: dict):
        with chat.lock:
            chat.d["display"][i].update(patch)
            chat.save()
        self.emit(chat, "update", i=i, patch=patch)

    def save_image(self, project: str, data: bytes) -> str:
        d = PROJECTS / project / "docs" / "chat" / "img"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{hashlib.sha1(data).hexdigest()[:16]}.jpg"
        if not f.exists():
            f.write_bytes(data)
        return f"/files/{rel(f)}"

    # ------------------------------------------------------------ turns
    def status(self):
        r = self.running
        return {"busy": bool(r), "chat": r and r["chat"].id, "project": r and r["project"],
                "pending": [p["id"] for p in self.proposals.pending()]}

    def send(self, project: str, cid: str | None, text: str, attach: dict | None = None) -> dict:
        if not cfg.api_key() and self.client_factory == self._anthropic:
            raise ValueError("Add your Anthropic API key first (Edit ▸ AI Editor Settings).")
        with self.lock:
            if self.running:
                raise ValueError("The AI Editor is still working on the last message — wait or press Stop.")
            chat = self.get_chat(project, cid)
            stop = threading.Event()
            self.running = {"chat": chat, "project": project, "stop": stop}
        body = text.strip()
        if attach and attach.get("text"):
            body += f"\n\n[Attached file: {attach.get('name', 'file')}]\n```\n{attach['text'][:120000]}\n```"
        self.add_item(chat, {"kind": "user", "text": text.strip(), **({"attach": attach.get("name")} if attach else {})})
        if chat.d["title"] == "New chat" and text.strip():
            chat.d["title"] = text.strip()[:60]
        th = threading.Thread(target=self._turn, args=(chat, project, body, stop), daemon=True)
        self.running["thread"] = th
        self.emit(chat, "busy", busy=True)
        th.start()
        return {"chat": chat.id}

    def stop(self):
        r = self.running
        if r:
            r["stop"].set()
        self.proposals.cancel_all()

    def resolve(self, pid: str, action: str, value=None):
        return self.proposals.resolve(pid, action, value)

    def _turn(self, chat: Chat, project: str, body: str, stop: threading.Event):
        ctx = Ctx(self, chat, project, stop)
        tools = Tools(ctx)
        s = cfg.get()
        turn = {"cost": 0.0, "in": 0, "out": 0}
        text_item = {"i": None}

        def emit(kind, data):
            if kind == "text":
                if text_item["i"] is None:
                    text_item["i"] = self.add_item(chat, {"kind": "text", "text": ""})["i"]
                with chat.lock:
                    chat.d["display"][text_item["i"]]["text"] += data["text"]
                self.emit(chat, "delta", i=text_item["i"], text=data["text"])
            elif kind == "tool_start":
                text_item["i"] = None                      # text after a tool call starts a new bubble
                chat.save()
            elif kind in ("error", "refusal"):
                self.add_item(chat, {"kind": "error", "text": data["text"]})
            elif kind == "stopped":
                self.add_item(chat, {"kind": "activity", "text": "⏹ Stopped."})

        def execute(name, args):
            text_item["i"] = None
            fn = getattr(tools, name, None)
            if name not in TOOL_KINDS or fn is None:
                return {"text": f"Unknown tool {name}.", "error": True}
            from ..keystore import redact
            try:
                out = fn(args or {})
            except ToolError as e:
                out = {"text": str(e), "error": True}
            except Exception as e:  # noqa: BLE001 — report any tool failure to Claude in plain words
                traceback.print_exc()
                out = {"text": f"The tool failed: {type(e).__name__}: {e}", "error": True}
            out["text"] = redact(out.get("text") or "")                  # a key never goes to Claude either
            return out

        def on_usage(u, model):
            c = cfg.cost(u, model if model in cfg.MODELS else s["model"])
            turn["cost"] += c
            turn["in"] += int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
            turn["out"] += int(u.get("output_tokens") or 0)
            with chat.lock:
                cu = chat.d["usage"]
                cu["input"] += int(u.get("input_tokens") or 0)
                cu["output"] += int(u.get("output_tokens") or 0)
                cu["cache_write"] += int(u.get("cache_creation_input_tokens") or 0)
                cu["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
                cu["cost"] = round(cu["cost"] + c, 6)
            self._add_project_usage(project, u, c)

        def budget_ok():
            b = s.get("budget_usd")
            if not b:
                return None
            spent = self.project_usage(project).get("cost", 0.0)
            if spent >= b:
                return f"This project reached its AI budget (${spent:.2f} of ${b:.2f}). Raise it in Edit ▸ AI Editor Settings to continue."
            return None

        try:
            wf = ctx.wf.public()
            tgt = ctx.style.duration_target()
            pre = f"[Project: {project} · workflow stage: {wf['stage']}" + (f" · target duration: {tgt}" if tgt else "") + "]\n"
            chat.d["messages"].append({"role": "user", "content": [{"type": "text", "text": pre + body}]})
            client = self.client_factory()
            loop = TurnLoop(client, model=s["model"], effort=s["effort"], max_tokens=int(s["max_tokens"]), system=SYSTEM,
                            tools=api_tools(), execute=execute, emit=emit, stop=stop, on_usage=on_usage, budget_ok=budget_ok)
            loop.run(chat.d["messages"])
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.add_item(chat, {"kind": "error", "text": f"Something went wrong: {e}"})
        finally:
            chat.save()
            tot = self.project_usage(project)
            if turn["in"] or turn["out"]:
                self.add_item(chat, {"kind": "usage", "cost": round(turn["cost"], 4), "tokens_in": turn["in"],
                                     "tokens_out": turn["out"], "project_cost": round(tot.get("cost", 0.0), 4)})
            with self.lock:
                self.running = None
            self.emit(chat, "busy", busy=False)
            self.emit(chat, "workflow", workflow=Workflow(PROJECTS / project).public())
