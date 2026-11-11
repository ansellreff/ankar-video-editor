# AnKar Video Editor

A Premiere-style video editor that runs **on your own PC, in your browser** — with auto captions, AI narration in your
own cloned voice, and a built-in Claude chat that edits the video with you (it never changes anything without your
**Approve**). Made for vertical travel vlogs (Reels / TikTok / Shorts), works for any format.

- **Private:** your footage, projects and API keys never leave your PC. The editor runs at `http://localhost:8765`, only for you.
- **Contained:** one folder. Setup puts its own portable Python, packages and models inside that folder — nothing is
  installed on Windows, no admin rights. To uninstall, delete the folder.
- **Free & open source** (MIT). The AI features use your own Claude / ElevenLabs keys (you pay them directly, per use).

## Download and set up (Windows 10 / 11, 64-bit)

1. **Download** the latest zip from the website: **https://ankar-video-editor.vercel.app** (free account — it only
   remembers your username and which version you downloaded, so it can remind you of updates).
   You can also get it from this repo's [Releases](../../releases).
2. **Unzip** it anywhere you like (for example `Documents\AnKar Video Editor`). Avoid OneDrive-synced folders for big video projects.
3. Double-click **`Setup AnKar Video Editor.bat`** — once. It downloads (about 0.8 GB, every file checked by SHA-256):
   - the official portable Python 3.12 from python.org → `runtime\`
   - the exact Python packages from `requirements-lock.txt` → `runtime\Lib\site-packages`
   - the Whisper subtitle model from Hugging Face → `models\`
   and then runs a self-test.
4. Double-click **`Start AnKar Video Editor.bat`** whenever you want to edit. Your browser opens the editor. Keep the
   black window open while editing; close it to stop.
5. First time: menu bar ▸ **API Keys** → create your password, then add your Claude and/or ElevenLabs key (optional —
   the editor itself works without any key).

**Update:** Help ▸ What's new shows when a new version is out. Download the new zip, close the editor, and drag the zip
onto **`Update AnKar Video Editor.bat`** (or double-click it — it finds the newest zip in Downloads). It replaces the
program files and runs Setup again. Your projects, voices, keys and settings are kept (they are never in the zip).

**Optional — offline AI voice:** `Install local AI voice (optional).bat` adds the Chatterbox voice engine (about 4 GB,
CPU). Without it, AI narration uses ElevenLabs.

### What you need
- Windows 10 (1803 or newer) or Windows 11, 64-bit; 8 GB RAM (16 GB recommended); about 3 GB free disk + your footage.
- A graphics chip with OpenGL 3.3 (almost every PC from the last 10 years) for preview and export.
- Microsoft Edge or Chrome.
- Internet only for Setup, the AI features and the update check.

### What the AI costs (your own API keys)
- **Claude (AI Editor):** billed per use by Anthropic. The AI Editor shows the running cost of each chat and stops at
  the budget you set (Edit ▸ AI Editor Settings). Key: https://console.anthropic.com
- **ElevenLabs (AI voice):** narration uses your ElevenLabs credits (a 5-minute vlog is a few thousand characters).
  Key: https://elevenlabs.io/app/settings/api-keys
- Auto captions, editing and export run on your PC and are free.

## Privacy
- The editor talks to the internet only for: Setup downloads, your own AI calls (Anthropic / ElevenLabs, with your
  keys), reference links you paste into the AI Editor, and one anonymous update check a day (`/api/latest` on the
  website — nothing about you or your projects is sent; turn it off with `ANKAR_UPDATE_CHECK=0`).
- API keys are encrypted on your PC (AES-256-GCM; the key file is protected by Windows DPAPI) and need your password
  to add, change or remove. They are never shown again, never written into projects, chats, exports or logs.
- The website stores only: your username, a one-way hash of your password, your email **if** you add one (only for
  "forgot password", encrypted), and the latest version you downloaded + its date. No footage, no projects, no keys,
  no IP addresses, no tracking. You can delete your account at any time.

## User guide
See **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** (projects and folders, editing, captions, AI voice, narration timing,
ElevenLabs, AI Editor). Keyboard shortcuts: Help ▸ Keyboard Shortcuts in the app. A **Demo** project opens on first start.

## For developers
```bat
rem from source, in this folder (Python 3.12):
python -m venv .venv
.venv\Scripts\python -m pip install --require-hashes --only-binary=:all: -r requirements-lock.txt
.venv\Scripts\python -m app.server            &rem → http://localhost:8765
.venv\Scripts\python -m pytest tests          &rem unit tests
git config core.hooksPath .githooks           &rem pre-commit: blocks API keys and private files
```
- Architecture: FastAPI server (`app/`) + a no-build Preact UI (`web/`); every edit is an undoable op in `app/project.py`.
  Preview (WebGL) and export (moderngl) share the same GLSL shaders in `effects/`.
- `website/` is the landing page + accounts (Vercel, Python functions, Neon Postgres). See `website/README.md`.
- Releases: put the notes in `CHANGELOG.md`, then `python -m scripts.release X.Y.Z` (tests + leak check + version bump
  + tag). Pushing the tag makes GitHub Actions build the zip and the Release.
- Never commit secrets: `python -m scripts.check_secrets` (also run by the pre-commit hook) stops API keys and private
  files (`config/`, your own `projects/`, voices, …).

## License
MIT — see [LICENSE](LICENSE). Fonts, sounds and models have their own (free) licences — see [CREDITS.md](CREDITS.md).
