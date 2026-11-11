"""AI Editor: the built-in Claude chat that edits the open project's video (and nothing else).

Pieces: settings (model, key status, prices) · workflow (stages, gates, proposals, review docs) · style (creative
choices, rounds, presets, style.md) · prompt (the system prompt = the guideline) · tools (what Claude may do) ·
client (the streaming tool loop) · runner (chat sessions, approvals, SSE to the browser) · reference (style from a
reference video file or link).

Two rules are enforced in code, not only in the prompt:
1. nothing that changes the video or spends credits runs before the user presses Approve (workflow.Proposals);
2. only editing tools exist — no shell, code, general web or file access outside the project's docs/.
"""
