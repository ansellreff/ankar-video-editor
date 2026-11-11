"""The streaming tool loop with the Claude API (manual loop, so an approval card can pause the turn).

Model claude-opus-5-5 (or claude-sonnet-5-5), adaptive thinking (Opus 5.5 always thinks; effort controls depth),
automatic prompt caching (stable system prompt + tool list), server-side refusal fallbacks ("default") and server-side
compaction for long chats. Assistant content (incl. thinking / compaction / fallback blocks) is passed back unchanged."""
from __future__ import annotations

import base64
import threading

FALLBACK_BETA = "server-side-fallback-2026-07-01"
COMPACT_BETA = "compact-2026-01-12"
MAX_STEPS = 80


def tool_result(tool_use_id: str, out: dict) -> dict:
    content = []
    if out.get("text"):
        content.append({"type": "text", "text": out["text"]})
    for img in out.get("images") or []:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.standard_b64encode(img).decode("ascii")}})
    if not content:
        content = [{"type": "text", "text": "ok"}]
    r = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if out.get("error"):
        r["is_error"] = True
    return r


def dump(block) -> dict:
    """SDK content block → dict for the next request (unchanged; aliases like `from` kept)."""
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", by_alias=True, exclude_none=True)


class TurnLoop:
    def __init__(self, client, *, model, effort, max_tokens, system, tools, execute, emit, stop: threading.Event,
                 on_usage, budget_ok=lambda: None):
        self.client, self.model, self.effort, self.max_tokens = client, model, effort, max_tokens
        self.system, self.tools, self.execute, self.emit, self.stop = system, tools, execute, emit, stop
        self.on_usage, self.budget_ok = on_usage, budget_ok

    def request(self, messages):
        return self.client.beta.messages.stream(
            model=self.model, max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system}],
            tools=self.tools, messages=messages,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA, COMPACT_BETA], fallbacks="default",
            context_management={"edits": [{"type": "compact_20260112"}]},
        )

    def run(self, messages: list):
        """Run one user turn to the end. Appends the assistant / tool-result turns to `messages` (in place)."""
        import anthropic
        json_retries = 0
        for _ in range(MAX_STEPS):
            if self.stop.is_set():
                self.emit("stopped", {})
                return
            why = self.budget_ok()
            if why:
                self.emit("error", {"text": why})
                return
            msg, stopped = None, False
            try:
                with self.request(messages) as stream:
                    for ev in stream:
                        if self.stop.is_set():
                            stopped = True
                            break
                        t = getattr(ev, "type", None)
                        if t == "text":
                            self.emit("text", {"text": ev.text})
                        elif t == "content_block_start" and getattr(ev.content_block, "type", "") == "tool_use":
                            self.emit("tool_start", {"name": ev.content_block.name})
                    if not stopped:
                        msg = stream.get_final_message()
                json_retries = 0
            except ValueError:
                json_retries += 1            # a tool input the SDK couldn't parse at all: re-issue the turn (bounded)
                if json_retries > 2:
                    self.emit("error", {"text": "Claude's reply couldn't be read three times in a row. Please try again."})
                    return
                continue
            except anthropic.AuthenticationError:
                self.emit("error", {"text": "The Anthropic API key was rejected. Check it in Edit ▸ AI Editor Settings."})
                return
            except anthropic.PermissionDeniedError:
                self.emit("error", {"text": "This API key isn't allowed to use that model. Pick another model in the settings."})
                return
            except anthropic.RateLimitError:
                self.emit("error", {"text": "The API is rate-limited right now. Wait a minute and send again."})
                return
            except anthropic.APIStatusError as e:
                self.emit("error", {"text": f"The Claude API returned an error ({e.status_code}): {getattr(e, 'message', e)}"})
                return
            except anthropic.APIConnectionError:
                self.emit("error", {"text": "Couldn't reach the Claude API (no internet?)."})
                return
            if stopped or msg is None:
                self.emit("stopped", {})
                return
            self.on_usage(msg.usage.model_dump() if hasattr(msg.usage, "model_dump") else dict(msg.usage),
                          getattr(msg, "model", self.model))
            messages.append({"role": "assistant", "content": [dump(b) for b in msg.content]})
            if msg.stop_reason == "pause_turn":
                continue
            uses = [b for b in msg.content if getattr(b, "type", None) == "tool_use"]
            if msg.stop_reason == "refusal":
                self.emit("refusal", {"text": "Claude declined this request."})
                if not uses:
                    return
            if not uses:
                if msg.stop_reason == "max_tokens":
                    self.emit("error", {"text": "The reply hit the length limit and was cut off."})
                return
            results = []
            for b in uses:
                if msg.stop_reason in ("max_tokens", "refusal"):
                    out = {"text": "This tool call was cut off and NOT run. Send a shorter input.", "error": True}
                else:
                    out = self.execute(b.name, b.input if isinstance(b.input, dict) else {})
                results.append(tool_result(b.id, out))
            messages.append({"role": "user", "content": results})
        self.emit("error", {"text": "Stopped after many steps in one turn — please continue with a new message."})
