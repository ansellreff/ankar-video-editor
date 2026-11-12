# Changelog

What changed in each version of AnKar Video Editor, in plain words. Newest first.
(The app's Help ▸ What's new and the website read this file — keep the `## X.Y.Z — YYYY-MM-DD` headings and `- ` bullets.)

## 1.0.1 — 2026-11-12
- Fixed: the optional offline AI voice installer ("Install local AI voice (optional).bat") failed because PyTorch needed setuptools.
- Website: clearer sign-up (no phone app or authenticator needed) and step-by-step authenticator help on the admin page.

## 1.0.0 — 2026-11-12
- First public version: a Premiere-style video editor that runs on your own PC in your browser (http://localhost:8765).
- Timeline with video, text, music, sound-effect and narration tracks; trim, split, ripple, speed, reverse, freeze frame, keyframes.
- Monitor gizmo to move, scale, rotate and crop; split-screen and picture-in-picture layouts.
- Transitions, filters, LUTs and looks; GPU preview that matches the export.
- Auto captions (Whisper, on your PC) with 16 animated caption styles; subtitles always in English with translations in ( ).
- AI narration: your own cloned voices (ElevenLabs, or the optional offline voice engine), tones, sentence timing and "Match to video".
- AI Editor: a built-in Claude chat that edits your video with you — script, style, duration and plan are always agreed first, and nothing changes without your Approve.
- API Keys page: your own Claude / ElevenLabs keys, encrypted on your PC and protected by your own password.
- One-click setup: everything (Python, packages, models) stays inside the AnKar folder — nothing is installed on Windows.
- Update reminder: Help ▸ What's new tells you when a new version is out.
