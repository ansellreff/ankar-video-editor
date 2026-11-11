# AnKar Video Editor — website (Vercel)

Landing page, accounts and downloads. Static pages in `public/` (built from `pages/` by `python -m website.build`)
+ one Python function `api/index.py` (FastAPI, code in `api/_lib/`) + a Neon Postgres database.

The site stores only: username, password hash (scrypt), optional email (AES-256-GCM, only for "forgot password"),
latest downloaded version + date, sessions (hashed), rate-limit counters (by username, never IP). See `public/privacy.html`.

## Deploy (free: Vercel Hobby + Neon free)
1. **Import:** vercel.com → *Add New… → Project* → import the GitHub repo → **Root Directory: `website`**,
   Framework Preset **Other** → Deploy. Pick the free name, e.g. `ankar-video-editor.vercel.app`.
2. **Database:** Project → *Storage* → *Create Database* → **Neon** (free) → connect it to this project
   (this adds `DATABASE_URL` automatically). The tables are created on the first request.
3. **Environment variables** (Project → Settings → Environment Variables, all environments):
   | Name | Value |
   |---|---|
   | `DATA_KEY` | 64 hex characters: `python -c "import secrets; print(secrets.token_hex(32))"` — encrypts emails and the admin authenticator secret. **Never change it later** (saved emails couldn't be read). |
   | `ADMIN_USERNAME` | the username of YOUR account (sign up first, then set this) |
   | `SMTP_USER`, `SMTP_PASS` | optional, for "forgot password": a Gmail address + a Gmail **app password** (Google Account → Security → 2-Step Verification → App passwords) |
   | `SITE_URL` | optional, e.g. `https://ankar-video-editor.vercel.app` (used in emails / the app's download link) |
4. **Redeploy** (Deployments → ⋯ → Redeploy) so the variables apply.
5. Sign in → **Account → Admin** → set up the authenticator app (QR code) → the dashboard.

The repo name for download links comes from `api/_lib/releases.json` (`"repo": "owner/name"`) or env `GITHUB_REPO`.
Versions + notes come from the repo's `CHANGELOG.md` via `python -m scripts.release` (it rewrites `releases.json`).
The app's update reminder reads `https://<site>/api/latest` (set in `app/version.py` → `SITE`).

## Local testing (no Node, no database server)
```bat
.venv\Scripts\python -m website.build        &rem pages/ → public/
.venv\Scripts\python -m website.dev          &rem http://localhost:3000 (SQLite in website/local.db, codes printed)
.venv\Scripts\python -m pytest tests/test_website.py
```
