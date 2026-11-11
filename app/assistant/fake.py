"""A scripted stand-in for the Claude API, used ONLY by the UI test on the test server (env VLOG_AI_FAKE=1): it never
calls the network. Turn: "Looking…" → tool edit(add_marker) → (the editor approves/declines in the UI) → "Done."."""
from __future__ import annotations

from types import SimpleNamespace as NS


class _B(NS):
    def model_dump(self, **kw):
        return dict(vars(self))


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([NS(type="text", text=b.text) for b in self.msg.content if b.type == "text"])

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self):
        self.beta = NS(messages=NS(stream=self.stream))

    def stream(self, **kw):
        msgs = kw["messages"]
        u = _B(input_tokens=120, output_tokens=40, cache_creation_input_tokens=0, cache_read_input_tokens=0)
        last = msgs[-1]["content"][0] if msgs and msgs[-1]["role"] == "user" else {}
        if last.get("type") == "tool_result":
            txt = last["content"][0]["text"] if last.get("content") else ""
            return _Stream(NS(content=[_B(type="text", text=f"Done. ({txt[:60]})")], stop_reason="end_turn", usage=u,
                              model="claude-opus-5-5"))
        return _Stream(NS(content=[_B(type="text", text="I'll add a marker at 1 s — please approve."),
                                   _B(type="tool_use", id="tu_fake", name="edit",
                                      input={"summary": "Add a marker at 1 s", "ops": [{"op": "add_marker", "args": {"t": 1.0, "label": "AI test"}}]})],
                          stop_reason="tool_use", usage=u, model="claude-opus-5-5"))


def make():
    return FakeClient()
