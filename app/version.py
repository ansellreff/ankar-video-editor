"""The app's version (one place) + the website used for update reminders.

Bump with `python -m scripts.release X.Y.Z` (it also checks CHANGELOG.md has notes for that version)."""
import os

VERSION = "1.0.0"
NAME = "AnKar Video Editor"
# The landing page on Vercel. The app only ever reads <SITE>/api/latest (no account, no personal data is sent).
SITE = os.environ.get("ANKAR_SITE", "https://ankar-video-editor.vercel.app").rstrip("/")


def parse(v: str) -> tuple[int, int, int]:
    """'1.2.3' (or 'v1.2.3') → (1, 2, 3). Raises ValueError on anything else."""
    parts = str(v).strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(p.isdigit() and len(p) <= 4 for p in parts):
        raise ValueError(f"not a version: {v!r}")
    return tuple(int(p) for p in parts)


def newer(a: str, b: str) -> bool:
    """True when version a is newer than version b."""
    return parse(a) > parse(b)
