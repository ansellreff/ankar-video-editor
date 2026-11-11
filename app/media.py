"""Media probing and derivatives (proxy, filmstrip, poster, waveform) using PyAV only.

Time convention everywhere: source time 0 = the container's start time, so audio and video stay aligned
in preview (proxies) and export (originals).
"""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image

from .colors import rgb_to_yuv709, to_rgb, x264_options

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".3gp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUB_EXT = {".srt", ".ass", ".vtt"}
FONT_EXT = {".ttf", ".otf"}

PROXY_MAX = 960          # long side of preview proxies
STRIP_H = 90             # filmstrip thumbnail height
WAVE_RATE = 100          # waveform peaks per second


def kind_of(path: Path) -> str | None:
    e = path.suffix.lower()
    for k, s in (("video", VIDEO_EXT), ("audio", AUDIO_EXT), ("image", IMAGE_EXT), ("subtitle", SUB_EXT), ("font", FONT_EXT)):
        if e in s:
            return k
    return None


def _rotation(stream, frame=None) -> int:
    """Clockwise degrees needed to display upright (like ffmpeg autorotate)."""
    a = None
    if frame is not None and getattr(frame, "rotation", None) is not None:
        a = frame.rotation                    # display-matrix angle (counter-clockwise)
    if a is None:
        try:
            a = -int(stream.metadata.get("rotate", 0))
        except (TypeError, ValueError):
            a = 0
    return int(round(-a / 90.0)) % 4 * 90


def upright(arr: np.ndarray, rot: int) -> np.ndarray:
    return np.ascontiguousarray(np.rot90(arr, k=-(rot // 90))) if rot else arr


def _even(x):
    return max(2, int(round(x / 2)) * 2)


def probe(path: Path) -> dict:
    kind = kind_of(path)
    meta = {"kind": kind}
    if kind == "image":
        with Image.open(path) as im:
            meta.update(w=im.width, h=im.height, dur=None, has_video=True, has_audio=False)
        return meta
    if kind not in ("video", "audio"):
        return meta
    with av.open(str(path)) as c:
        start = (c.start_time or 0) / 1e6
        dur = (c.duration or 0) / 1e6
        meta.update(has_video=bool(c.streams.video) and kind == "video", has_audio=bool(c.streams.audio), start=start)
        if meta["has_video"]:
            s = c.streams.video[0]
            fr = s.average_rate or s.guessed_rate or Fraction(30000, 1001)
            first = next(c.decode(video=0), None)
            rot = _rotation(s, first)
            w, h = (s.codec_context.width, s.codec_context.height)
            if rot in (90, 270):
                w, h = h, w
            meta.update(w=w, h=h, fps=float(fr), fps_frac=f"{fr.numerator}/{fr.denominator}", rotation=rot,
                        vcodec=s.codec_context.name)
            if not dur and s.duration:
                dur = float(s.duration * s.time_base)
        if meta["has_audio"]:
            a = c.streams.audio[0]
            meta.update(sr=a.sample_rate, channels=a.codec_context.channels if hasattr(a.codec_context, "channels") else 2,
                        acodec=a.codec_context.name)
            if not dur and a.duration:
                dur = float(a.duration * a.time_base)
        meta["dur"] = round(dur, 4)
    return meta


def reversed_proxy(proxy: Path, out: Path, t0: float, t1: float, fps_frac="30000/1001"):
    """Preview copy of proxy[t0:t1] playing backwards (video + audio). Decodes 1 s chunks from the end → low memory."""
    fps = Fraction(fps_frac)
    tmp = out.with_suffix(".part.mp4")
    src = av.open(str(proxy))
    vin = src.streams.video[0]
    W, H = vin.codec_context.width, vin.codec_context.height
    o = av.open(str(tmp), "w", options={"movflags": "+faststart"})
    vs = o.add_stream("libx264", rate=fps, options=x264_options(crf="26", preset="veryfast", tune="fastdecode"))
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    vs.codec_context.gop_size = 15
    has_a = bool(src.streams.audio)
    as_ = o.add_stream("aac", rate=48000, layout="stereo") if has_a else None
    pts = 0
    end = t1
    while end > t0 + 1e-3:
        start = max(t0, end - 1.0)
        src.seek(int(max(0.0, start - 0.5) / vin.time_base), stream=vin, backward=True)
        frames = []
        for f in src.decode(vin):
            ft = float(f.time or 0)
            if ft >= end - 1e-4:
                break
            if ft >= start - 1e-4:
                frames.append(to_rgb(f))
        for arr in reversed(frames):
            vf = rgb_to_yuv709(arr)
            vf.pts = pts
            pts += 1
            for p in vs.encode(vf):
                o.mux(p)
        end = start
    for p in vs.encode():
        o.mux(p)
    if has_a:
        src.seek(int(max(0.0, t0 - 0.5) * 1e6))
        rs = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
        chunks, a_t0 = [], None
        for f in src.decode(src.streams.audio[0]):
            if a_t0 is None:
                a_t0 = float(f.time or 0)
            for r in rs.resample(f):
                chunks.append(r.to_ndarray())
        if chunks:
            x = np.concatenate(chunks, axis=1)
            a, b = int(max(0.0, t0 - a_t0) * 48000), int(max(0.0, t1 - a_t0) * 48000)
            x = np.ascontiguousarray(x[:, a:b][:, ::-1])
            for s in range(0, x.shape[1], 1024):
                af = av.AudioFrame.from_ndarray(np.ascontiguousarray(x[:, s:s + 1024]), format="fltp", layout="stereo")
                af.sample_rate, af.pts = 48000, s
                for p in as_.encode(af):
                    o.mux(p)
            for p in as_.encode():
                o.mux(p)
    o.close()
    src.close()
    tmp.replace(out)
    return out


def process(path: Path, out_dir: Path, meta: dict, progress=None) -> dict:
    """One pass: proxy.mp4 (video), strip.jpg + poster.jpg (video/image), wave.json (audio). Returns info."""
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = meta["kind"]
    info = {}
    if kind == "image":
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((480, 480))
            im.save(out_dir / "poster.jpg", quality=82)
        info["poster"] = True
        return info

    dur = meta.get("dur") or 0.0
    start = meta.get("start", 0.0)
    has_v, has_a = meta.get("has_video"), meta.get("has_audio")

    # waveform accumulators
    win = 48000 // WAVE_RATE
    peaks, carry = [], np.zeros(0, np.float32)

    # filmstrip
    strip_iv = max(1.0, dur / 150.0) if dur else 1.0
    thumbs, next_thumb = [], 0.0
    poster_t, poster = (dur * 0.33 if dur else 0.0), None

    src = av.open(str(path))
    vin = src.streams.video[0] if has_v else None
    ain = src.streams.audio[0] if has_a else None
    if vin is not None:
        vin.thread_type = "AUTO"
    out = vs = as_ = None
    if has_v:
        rot = meta.get("rotation", 0)
        w, h = meta["w"], meta["h"]
        sc = PROXY_MAX / max(w, h)
        pw, ph = _even(w * sc), _even(h * sc)
        tw = max(2, int(round(STRIP_H * w / h)))
        fps = Fraction(meta.get("fps_frac", "30000/1001"))
        out = av.open(str(out_dir / "proxy.mp4"), "w", options={"movflags": "+faststart"})
        vs = out.add_stream("libx264", rate=fps, options=x264_options(crf="27", preset="veryfast", tune="fastdecode"))
        vs.width, vs.height, vs.pix_fmt = pw, ph, "yuv420p"
        vs.codec_context.gop_size = 15                     # frequent keyframes = snappy scrubbing
        if has_a:
            as_ = out.add_stream("aac", rate=48000, layout="stereo")
            as_.bit_rate = 128000
        last_pts = -1
    rs = av.AudioResampler(format="fltp", layout="stereo", rate=48000) if has_a else None
    a_samples = 0

    streams = [s for s in (vin, ain) if s is not None]
    for packet in src.demux(*streams):
        for frame in packet.decode():
            if packet.stream.type == "video":
                t = float(frame.time or 0) - start
                rw, rh = (ph, pw) if rot in (90, 270) else (pw, ph)   # scale in stored orientation, then rotate
                arr = upright(to_rgb(frame, rw, rh), rot)
                pts = int(round(t * fps))
                if pts > last_pts:
                    vf = rgb_to_yuv709(arr)
                    vf.pts = pts
                    for p in vs.encode(vf):
                        out.mux(p)
                    last_pts = pts
                if t >= next_thumb:
                    im = Image.fromarray(arr)
                    thumbs.append(im.resize((tw, STRIP_H), Image.BILINEAR))
                    next_thumb += strip_iv
                if poster is None and t >= poster_t:
                    poster = Image.fromarray(arr)
                if progress and dur:
                    progress(min(0.99, t / dur))
            else:
                for rf in rs.resample(frame):
                    x = rf.to_ndarray()
                    if as_ is not None:
                        rf.pts = a_samples
                        for p in as_.encode(rf):
                            out.mux(p)
                    a_samples += x.shape[1]
                    mono = np.abs(x).max(axis=0)
                    carry = np.concatenate([carry, mono])
                    n = len(carry) // win
                    if n:
                        peaks.extend(carry[:n * win].reshape(n, win).max(axis=1).tolist())
                        carry = carry[n * win:]
                    if progress and dur and not has_v:
                        progress(min(0.99, a_samples / 48000 / dur))
    if rs is not None:
        for rf in rs.resample(None):
            if as_ is not None:
                rf.pts = a_samples
                for p in as_.encode(rf):
                    out.mux(p)
            a_samples += rf.samples
    if out is not None:
        for p in vs.encode():
            out.mux(p)
        if as_ is not None:
            for p in as_.encode():
                out.mux(p)
        out.close()
        info["proxy"] = True
    src.close()

    if thumbs:
        sheet = Image.new("RGB", (thumbs[0].width * len(thumbs), STRIP_H))
        for i, im in enumerate(thumbs):
            sheet.paste(im, (i * thumbs[0].width, 0))
        sheet.save(out_dir / "strip.jpg", quality=70)
        info["strip"] = {"interval": strip_iv, "count": len(thumbs), "tw": thumbs[0].width, "th": STRIP_H}
    if poster is not None or thumbs:
        p = poster or thumbs[0]
        p = p.copy(); p.thumbnail((480, 480))
        p.save(out_dir / "poster.jpg", quality=82)
        info["poster"] = True
    if has_a:
        if len(carry):
            peaks.append(float(carry.max()))
        q = np.clip(np.sqrt(np.array(peaks, np.float32)) * 255, 0, 255).astype(np.uint8)   # sqrt = visible quiet parts
        (out_dir / "wave.json").write_text(json.dumps({"rate": WAVE_RATE, "peaks": q.tolist()}))
        info["wave"] = True
    return info
