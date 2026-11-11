"""AI Editor: approval-first workflow, docs sandbox, style rounds, the tool loop — with a FAKE Claude client (no API
cost, no network). python -m pytest tests/test_assistant_workflow.py"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace as NS

import pytest

from app.assistant import settings as cfg
from app.assistant import style as style_mod
from app.assistant.client import TurnLoop, tool_result
from app.assistant.prompt import REFUSAL, REFUSAL_APP, SYSTEM
from app.assistant.tools import ALLOWED_OPS, ToolError, Tools, api_tools
from app.assistant.workflow import DocError, Proposals, Workflow


# ---------------------------------------------------------------- docs sandbox + "your edits win"
def test_docs_sandbox_rejects_paths_outside_docs(tmp_path):
    wf = Workflow(tmp_path)
    for bad in ["../evil.md", "docs/../../evil.md", "C:/Windows/x.md", "docs/chat/x.md", "script/x.py", "", "docs/"]:
        with pytest.raises(DocError):
            wf.write_doc(bad, "x")
    r = wf.write_doc("docs/script/script_v1.md", "# v1")
    assert r["path"] == "docs/script/script_v1.md" and (tmp_path / "docs" / "script" / "script_v1.md").exists()


def test_user_edited_doc_is_never_overwritten(tmp_path):
    wf = Workflow(tmp_path)
    wf.write_doc("script/script_v1.md", "line one\nline two\n")
    wf.write_doc("script/script_v1.md", "line one\nline two (AI update)\n")          # AI may update its own file
    f = tmp_path / "docs" / "script" / "script_v1.md"
    f.write_text("line one\nline two — edited by the editor\n", encoding="utf-8")   # the editor edits it
    assert wf.edited_by_user("script/script_v1.md")
    r = wf.read_doc("script/script_v1.md")
    assert r["edited_by_you"] and "edited by the editor" in r["your_changes"]
    with pytest.raises(DocError):
        wf.write_doc("script/script_v1.md", "AI overwrite")
    assert "edited by the editor" in f.read_text(encoding="utf-8")
    (tmp_path / "docs" / "script" / "brief.md").write_text("my idea", encoding="utf-8")  # written by the editor
    with pytest.raises(DocError):
        wf.write_doc("script/brief.md", "AI rewrite of the brief")


# ---------------------------------------------------------------- stages and gates
def test_stage_gates_and_needs_update(tmp_path):
    wf = Workflow(tmp_path)
    assert wf.gate("build_from_plan") and wf.gate("make_narration") and wf.gate("style_test")
    wf.approve("brief")
    wf.approve("script")
    assert wf.gate("make_narration")                       # style not approved yet
    wf.approve("style")
    assert wf.gate("make_narration") is None and wf.gate("style_test") is None
    assert wf.gate("build_from_plan")                      # plan missing
    wf.approve("plan")
    assert wf.gate("build_from_plan") is None
    wf.approve("script")                                   # script approved again → later stages need a look
    assert "plan" in wf.data["needs_update"] and wf.gate("build_from_plan")
    assert Workflow(tmp_path).data["approved"].keys() >= {"brief", "script", "style", "plan"}   # persisted


# ---------------------------------------------------------------- proposals block until the editor answers
def test_proposals_wait_for_approve_and_stop():
    P = Proposals()
    stop = threading.Event()
    p = P.create("proposal", {})
    got = {}
    th = threading.Thread(target=lambda: got.setdefault("r", P.wait(p["id"], stop)))
    th.start()
    time.sleep(0.2)
    assert th.is_alive() and not got                       # still waiting: nothing runs without an answer
    P.resolve(p["id"], "approve")
    th.join(2)
    assert got["r"]["status"] == "approved"
    with pytest.raises(ValueError):
        P.resolve(p["id"], "approve")                      # can't answer twice
    q = P.create("proposal", {})
    stop.set()
    assert P.wait(q["id"], stop)["status"] == "stopped"


# ---------------------------------------------------------------- the edit tool only runs after Approve
class FakeHttp:
    def __init__(self):
        self.batches, self.posts = [], []
        self.base = "http://test"

    def state(self):
        return {"project_name": "P", "project": {"clips": [], "tracks": [], "transitions": [], "markers": []},
                "assets": [], "history": {}}

    def post(self, path, body=None, **kw):
        self.posts.append((path, body))
        return {"file": "ck.json"}

    def batch(self, ops, label):
        self.batches.append((ops, label))
        return {"result": [["c1"]], "project": self.state()["project"]}


def fake_ctx(tmp_path, decision):
    wf = Workflow(tmp_path)
    ctx = NS(project="P", pdir=tmp_path, wf=wf, style=style_mod.StyleSheet(tmp_path, wf), http=FakeHttp(),
             stop=threading.Event(), activities=[], proposals=[])
    ctx.activity = lambda text, link=None: ctx.activities.append(text)
    ctx.show_image = lambda data, caption="": None

    def propose(kind, title, summary="", details=None, cost=None, length=None, actions=()):
        ctx.proposals.append({"kind": kind, "title": title})
        return {"status": decision, "value": "shorter please" if decision == "change" else None}
    ctx.propose = propose
    return ctx


@pytest.mark.parametrize("decision", ["declined", "change", "stopped"])
def test_edit_not_applied_without_approve(tmp_path, decision):
    ctx = fake_ctx(tmp_path, decision)
    r = Tools(ctx).edit({"summary": "add a title", "ops": [{"op": "add_text", "args": {"start": 1, "content": "Hi"}}]})
    assert ctx.proposals and not ctx.http.batches and not ctx.http.posts      # no change, not even a checkpoint
    assert ("Nothing was changed" in r["text"]) or ("wants changes" in r["text"])


def test_edit_applied_after_approve_as_one_undo_step(tmp_path):
    ctx = fake_ctx(tmp_path, "approved")
    Tools(ctx).edit({"summary": "add a title", "ops": [{"op": "add_text", "args": {"start": 1, "content": "Hi"}},
                                                        {"op": "add_marker", "args": {"t": 2}}]})
    assert len(ctx.http.batches) == 1
    ops, label = ctx.http.batches[0]
    assert label.startswith("AI: ") and len(ops) == 2
    assert any(p == "/api/projects/checkpoint" for p, _ in ctx.http.posts)     # checkpoint before the change


def test_edit_rejects_ops_outside_the_allow_list(tmp_path):
    ctx = fake_ctx(tmp_path, "approved")
    for op in ("set_settings", "set_format", "set_brand", "paste", "remove_track"):
        assert op not in ALLOWED_OPS
        with pytest.raises(ToolError):
            Tools(ctx).edit({"summary": "x", "ops": [{"op": op, "args": {}}]})
    assert not ctx.proposals and not ctx.http.batches


def test_gated_tools_refuse_before_approvals(tmp_path):
    ctx = fake_ctx(tmp_path, "approved")
    for name in ("build_from_plan", "style_test", "make_narration"):
        with pytest.raises(ToolError) as e:
            getattr(Tools(ctx), name)({"plan": {"items": []}, "script": "docs/script/x.md"})
        assert "approve" in str(e.value).lower()
    assert not ctx.proposals


# ---------------------------------------------------------------- style rounds, style.md, My styles
def test_style_round_records_who_decided_and_md_edits_win(tmp_path):
    wf = Workflow(tmp_path)
    sh = style_mod.StyleSheet(tmp_path, wf)
    recs = {"duration": {"value": "2:00 ± 0:15", "reason": "Reels sweet spot"},
            "platform": {"value": "Reels 9:16", "reason": "", "from_brief": True},
            "purpose": {"value": "tourism entry", "reason": "brief"}}
    sh.set_round("goal", {"duration": "1:30 ± 0:10", "platform": "Reels 9:16", "purpose": "tourism entry"}, recs)
    v = sh.data["values"]
    assert v["duration"]["decided_by"] == "you" and v["purpose"]["decided_by"] == "AI suggestion accepted"
    assert v["platform"]["decided_by"] == "from your brief"
    assert sh.duration_target() == "1:30 ± 0:10"
    md = tmp_path / "docs" / "edit" / "style.md"
    text = md.read_text(encoding="utf-8")
    assert "| Duration per version (always asked) | 1:30 ± 0:10 |" in text
    md.write_text(text.replace("1:30 ± 0:10", "1:45 max 2:00"), encoding="utf-8")   # the editor edits style.md
    assert "duration" in sh.sync_from_md() and sh.duration_target() == "1:45 max 2:00"


def test_style_round_tool_requires_every_choice_prefilled_with_reason(tmp_path):
    ctx = fake_ctx(tmp_path, "approved")
    ctx.ask = lambda kind, payload: {"values": {f["id"]: "x" for f in payload["round"]["fields"]}}
    with pytest.raises(ToolError):
        Tools(ctx).ask_style_round({"round": "goal", "recommendations": {"duration": {"value": "2:00", "reason": "r"}}})
    spec = style_mod.round_spec("goal")
    recs = {f["id"]: {"value": "v", "reason": "because"} for f in spec["fields"]}
    r = Tools(ctx).ask_style_round({"round": "goal", "recommendations": recs})
    assert "answered" in r["text"] and "goal" in ctx.style.data["rounds_done"]


def test_my_styles_saved_and_offered_first(tmp_path, monkeypatch):
    monkeypatch.setattr(style_mod, "STYLES_DIR", tmp_path / "styles")
    wf = Workflow(tmp_path)
    sh = style_mod.StyleSheet(tmp_path, wf)
    sh.set_round("look_sound", {"pacing": "slow", "look": "warm"}, {})
    style_mod.save_preset("My calm style", sh)
    ps = style_mod.list_presets()
    assert ps[0]["name"] == "My calm style" and ps[0]["mine"] and ps[0]["values"]["pacing"] == "slow"
    assert any(p["name"] == "Fast viral travel vlog" for p in ps)


# ---------------------------------------------------------------- the tool loop with a fake Claude client
class Block(NS):
    def model_dump(self, **kw):
        return {k: v for k, v in vars(self).items()}


class FakeStream:
    def __init__(self, msg, events):
        self.msg, self.events = msg, events

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **kw):
        self.calls.append(kw)
        msg = self.script.pop(0)
        events = [NS(type="text", text=b.text) for b in msg.content if b.type == "text"]
        return FakeStream(msg, events)


def usage(i=10, o=5):
    return Block(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=100)


def test_turn_loop_runs_tools_and_passes_content_back():
    m1 = NS(content=[Block(type="text", text="Looking."), Block(type="tool_use", id="tu1", name="project_overview", input={})],
            stop_reason="tool_use", usage=usage(), model="claude-opus-5-5")
    m2 = NS(content=[Block(type="text", text="Done.")], stop_reason="end_turn", usage=usage(), model="claude-opus-5-5")
    client = FakeClient([m1, m2])
    ran, out, costs = [], [], []
    loop = TurnLoop(client, model="claude-opus-5-5", effort="medium", max_tokens=64000, system=SYSTEM, tools=api_tools(),
                    execute=lambda n, a: ran.append(n) or {"text": "overview", "images": [b"\xff\xd8jpeg"]},
                    emit=lambda k, d: out.append((k, d)), stop=threading.Event(),
                    on_usage=lambda u, m: costs.append(cfg.cost(u, m)))
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    loop.run(msgs)
    assert ran == ["project_overview"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    tr = msgs[2]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "tu1" and tr["content"][1]["type"] == "image"
    kw = client.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"] == {"effort": "medium"} and "thinking" not in kw          # Opus 5.5: adaptive by default
    assert ("text", {"text": "Done."}) in out and len(costs) == 2


def test_turn_loop_respects_stop_and_budget():
    client = FakeClient([])
    out = []
    stop = threading.Event()
    stop.set()
    TurnLoop(client, model="claude-opus-5-5", effort="medium", max_tokens=1000, system="s", tools=[], execute=None,
             emit=lambda k, d: out.append(k), stop=stop, on_usage=None).run([])
    assert out == ["stopped"] and not client.calls
    out.clear()
    TurnLoop(client, model="claude-opus-5-5", effort="medium", max_tokens=1000, system="s", tools=[], execute=None,
             emit=lambda k, d: out.append(k), stop=threading.Event(), on_usage=None,
             budget_ok=lambda: "budget reached").run([])
    assert out == ["error"] and not client.calls


def test_tool_result_marks_errors():
    r = tool_result("x", {"text": "bad", "error": True})
    assert r["is_error"] and r["content"][0]["text"] == "bad"


# ---------------------------------------------------------------- prices, prompt, script parser, builder defaults
def test_cost_math():
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert cfg.cost(u, "claude-opus-5-5") == pytest.approx(4 + 20 + 5 + 0.2)
    assert cfg.cost(u, "claude-sonnet-5-5") == pytest.approx(2 + 10 + 2.5 + 0.2)


def test_system_prompt_has_the_scope_limit_and_approval_rule():
    assert REFUSAL in SYSTEM and REFUSAL_APP in SYSTEM
    for must in ("ONLY help with editing the video", "without the editor's Approve", "duration of each version is ALWAYS asked",
                 "[ ] = scene summary", "never assume a style"):
        assert must in SYSTEM


def test_script_parser_reads_the_script_format():
    from app.assistant.narration import parse_script
    text = """## INTRO
## SCENE 1: Off work [L P1]
$Ansell$ {cheerful} Hi, it's me, Ansell! It's Friday... and the week is done!   [L P1]
$Karina & Ansell$ {excited} E-DA Theme Park!   [L]   ⚠ check
$Karina$ Two days, two parks.   *(same as before)*
"""
    sc = parse_script(text)
    assert len(sc) == 1 and sc[0]["title"].startswith("SCENE 1")
    l1, l2, l3 = sc[0]["lines"]
    assert l1["speakers"] == ["Ansell"] and l1["tone"] == "cheerful" and l1["versions"] == ["L", "P1"]
    assert l1["text"].endswith("the week is done!")
    assert l2["speakers"] == ["Karina", "Ansell"] and l2["text"] == "E-DA Theme Park!" and l2["versions"] == ["L"]
    assert l3["text"] == "Two days, two parks." and l3["tone"] == "cheerful"


def test_reference_analysis_on_a_local_clip_and_bad_links():
    from pathlib import Path
    from app.assistant import reference as ref
    clips = sorted(Path("library/samples").glob("*.mp4"))
    if not clips:
        pytest.skip("no sample clips")
    r = ref.analyze(clips[0], clips[0].name)
    n = r["numbers"]
    assert n["duration_s"] > 0 and n["cuts"] >= 0 and n["avg_shot_s"] > 0 and r["sheet"][:2] == b"\xff\xd8"
    assert "| Cuts |" in r["markdown"]
    with pytest.raises(ref.FetchError):
        ref.fetch("not a link")


def test_plan_json_maps_onto_the_builder():
    from app.assistant.planbuild import estimate, to_edl
    edl = to_edl({"items": [{"type": "music", "file": "song.mp3", "at": 0},
                            {"type": "typed", "line1": "Friday", "line2": "5 PM", "length": 3},
                            {"type": "logos"},
                            {"type": "beat", "shots": [{"clip": "Scene 1_1", "from": 0.5, "mode": "native"}], "lines": ["s01_01"],
                             "transition": "whip_pan", "texts": [{"content": "HI", "at": 0.2, "dur": 2}]},
                            {"type": "fade_out", "dur": 0.5}]})
    names = [type(x).__name__ for x in edl]
    assert names == ["Music", "Typed", "Mark", "Beat", "FadeOut"]
    assert edl[3].shots[0].clip == "Scene 1_1" and edl[3].trans == "whip_pan" and edl[3].lines == ["s01_01"]
    est = estimate(edl, {"s01_01": [{"dur": 4.0}]}, 1.5)
    assert est == pytest.approx(3 + 0.25 + 4.0 + 0.45 + 1.5)
    with pytest.raises(ValueError):
        to_edl({"items": [{"type": "explode"}]})


def test_builder_without_opts_keeps_the_taiwan_defaults():
    from scripts.having_fun import builder as B
    b = B.Builder("Having Fun in Taiwan - Ansell", {"look": "clean_natural", "caption": "karaoke_pill"}, [], "x", "x")
    assert b.footage_db == B.FOOTAGE_DB and b.breathe_default == B.BREATHE and b.colors == B.COLORS and b.edit == B.EDIT
    if (B.EDIT / "narration.json").exists():
        assert set(json.loads((B.EDIT / "narration.json").read_text(encoding="utf-8"))) <= set(b.narr)
