"""Style from a reference video: a file in the project, or a link (TikTok / Reels / YouTube / …).

A link is downloaded with yt-dlp in a single-file format (ffmpeg is blocked on this PC, so no merging) at ≤720p into
cache/reference/, used ONLY for analysis (never as footage) and deleted afterwards — only the numbers and a small
contact sheet are kept. If it can't be fetched (login, private, removed, region), the editor is asked for the file."""
from __future__ import annotations

import hashlib
import io
import re
import shutil
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

from ..paths import ROOT

CACHE = ROOT / "cache" / "reference"
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
MAX_SECONDS = 15 * 60


class FetchError(RuntimeError):
    pass


class _Quiet:
    """yt-dlp logger that stays silent (errors come back to the chat as a plain FetchError instead)."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def fetch(url: str) -> Path:
    if not URL_RE.match(url or ""):
        raise FetchError("that doesn't look like a video link")
    import yt_dlp
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    opts = {
        "outtmpl": str(CACHE / f"{key}.%(ext)s"), "noplaylist": True, "quiet": True, "no_warnings": True, "logger": _Quiet(),
        # one file with picture + sound (no merging: ffmpeg is not available), small resolution is enough
        "format": "best[height<=720][vcodec!=none][acodec!=none]/best[vcodec!=none][acodec!=none]/best",
        "max_filesize": 400 * 1024 * 1024, "socket_timeout": 30, "retries": 2,
        "cachedir": str(CACHE / "yt-dlp"),          # keep yt-dlp's cache inside the app folder (default: ~/.cache)
        "match_filter": lambda info, *_: "longer than 15 minutes" if (info.get("duration") or 0) > MAX_SECONDS else None,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            f = Path(ydl.prepare_filename(info))
    except Exception as e:  # noqa: BLE001 — yt-dlp raises many types; all mean "couldn't get it"
        msg = str(e).split("\n")[0][:200]
        raise FetchError(f"couldn't download that link ({msg}). It may need a login, be private, removed or "
                         f"region-locked. Please download or screen-record the video and import the file instead.") from None
    if not f.exists():
        cands = sorted(CACHE.glob(f"{key}.*"))
        if not cands:
            raise FetchError("the download produced no video file — please import the file instead")
        f = cands[0]
    return f


def _frames(path: Path, times: list[float], w=180):
    out = {}
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        for t in times:
            try:
                c.seek(int(max(0.0, t) / s.time_base), stream=s, any_frame=False, backward=True)
                for fr in c.decode(s):
                    if fr.time is not None and fr.time >= t - 0.05:
                        im = fr.to_image()
                        im.thumbnail((w, w * 2))
                        out[t] = im
                        break
            except av.error.FFmpegError:
                continue
    return out


def analyze(path: Path, label: str) -> dict:
    """Measured style of a video → {numbers…, text (markdown), sheet (JPEG bytes)}."""
    from ..beats import analyze_file
    from ..subtitles import utterances
    from ..tts.context import audio16, detect_cuts
    with av.open(str(path)) as c:
        v = c.streams.video[0] if c.streams.video else None
        if v is None:
            raise FetchError("that file has no picture")
        dur = float(c.duration / 1e6) if c.duration else float(v.duration * v.time_base)
        w, h = v.codec_context.width, v.codec_context.height
        fps = float(v.average_rate or 30)
        has_audio = bool(c.streams.audio)
    cuts = detect_cuts(str(path), fps=10.0, min_gap=0.25)
    edges = [0.0] + cuts + [dur]
    shots = np.diff(edges) if len(edges) > 1 else np.array([dur])
    thirds = []
    for a, b in ((0, dur / 3), (dur / 3, 2 * dur / 3), (2 * dur / 3, dur)):
        n = sum(1 for t in cuts if a <= t < b)
        thirds.append(round((b - a) / (n + 1), 2))
    # color (sampled frames)
    sample_t = list(np.linspace(0.5, max(0.6, dur - 0.5), 12))
    fr = _frames(path, sample_t)
    lum, con, sat, warm = [], [], [], []
    for im in fr.values():
        a = np.asarray(im.convert("RGB")).astype(np.float32) / 255.0
        y = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
        mx, mn = a.max(-1), a.min(-1)
        lum.append(y.mean()); con.append(y.std()); sat.append(((mx - mn) / (mx + 1e-6)).mean())
        warm.append((a[..., 0] - a[..., 2]).mean())
    # sound: tempo, cuts on beats, speech share
    bpm, on_beat, speech = None, None, None
    if has_audio:
        try:
            b = analyze_file(str(path))
            bpm = b.get("bpm")
            beats = np.array(b.get("beats") or [])
            if len(beats) and cuts:
                on_beat = round(float(np.mean([np.min(np.abs(beats - t)) < 0.09 for t in cuts])), 2)
            x = audio16(str(path))
            if len(x) > 16000:
                talk = sum(b - a for a, b in utterances(x, 16000, max_len=1e9)) / 16000
                speech = round(min(1.0, talk / max(1e-3, dur)), 2)
        except Exception:  # noqa: BLE001 — sound analysis is optional
            pass
    # contact sheet: 12 frames with times (for Claude to read text/caption style, framing, transitions)
    tiles = [(t, fr[t]) for t in sample_t if t in fr]
    sheet = None
    if tiles:
        tw = max(im.width for _, im in tiles)
        th = max(im.height for _, im in tiles)
        cols = 6
        rows = (len(tiles) + cols - 1) // cols
        g = Image.new("RGB", (cols * tw, rows * th), "black")
        for i, (t, im) in enumerate(tiles):
            x0, y0 = (i % cols) * tw, (i // cols) * th
            g.paste(im, (x0, y0))
            ImageDraw.Draw(g).text((x0 + 4, y0 + 3), f"{t:.1f}s", fill="yellow")
        buf = io.BytesIO()
        g.save(buf, "JPEG", quality=78)
        sheet = buf.getvalue()
    orient = "vertical" if h > w else ("square" if abs(h - w) < 8 else "landscape")
    nums = {
        "label": label, "duration_s": round(dur, 1), "format": f"{w}×{h} {orient}, {fps:.0f} fps",
        "cuts": len(cuts), "avg_shot_s": round(float(shots.mean()), 2), "median_shot_s": round(float(np.median(shots)), 2),
        "shortest_shot_s": round(float(shots.min()), 2), "longest_shot_s": round(float(shots.max()), 2),
        "avg_shot_by_third_s": thirds, "first_cut_s": round(cuts[0], 2) if cuts else None,
        "brightness": round(float(np.mean(lum)), 2) if lum else None, "contrast": round(float(np.mean(con)), 3) if con else None,
        "saturation": round(float(np.mean(sat)), 2) if sat else None, "warmth": round(float(np.mean(warm)), 3) if warm else None,
        "music_bpm": bpm, "cuts_on_beat_share": on_beat, "speech_share": speech,
    }
    md = [f"# Reference: {label}", "", "Measured by the AI Editor (analysis only — the video is not used as footage).", "",
          "| Measure | Value |", "|---|---|"]
    names = {"duration_s": "Length (s)", "format": "Format", "cuts": "Cuts", "avg_shot_s": "Average shot (s)",
             "median_shot_s": "Median shot (s)", "shortest_shot_s": "Shortest shot (s)", "longest_shot_s": "Longest shot (s)",
             "avg_shot_by_third_s": "Average shot per third (start / middle / end, s)", "first_cut_s": "First cut at (s)",
             "brightness": "Brightness (0–1)", "contrast": "Contrast", "saturation": "Saturation (0–1)",
             "warmth": "Warmth (red − blue)", "music_bpm": "Music tempo (BPM)",
             "cuts_on_beat_share": "Cuts on a beat (share)", "speech_share": "Talking (share of time)"}
    for k, n in names.items():
        md.append(f"| {n} | {nums.get(k) if nums.get(k) is not None else '—'} |")
    md += ["", "## What the AI Editor reads from it", "(written after looking at the contact sheet)", ""]
    return {"numbers": nums, "markdown": "\n".join(md), "sheet": sheet}


def cleanup(path: Path):
    """Delete a downloaded reference video (keep nothing but the analysis)."""
    try:
        if CACHE in Path(path).resolve().parents:
            Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def clear_cache():
    shutil.rmtree(CACHE, ignore_errors=True)
