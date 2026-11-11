"""ElevenLabs engine (optional, cloud). The API key comes from app.config (config/secrets.json or env) and is only ever
sent to api.elevenlabs.io in the xi-api-key header — never logged, stored in projects, or returned to the browser."""
from __future__ import annotations

import hashlib
import json
import uuid
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
# fallback triggers: no credits / bad or missing key / plan limits / rate limits
FALLBACK_CODES = {"quota_exceeded", "invalid_api_key", "missing_api_key", "payment_required", "too_many_concurrent_requests",
                  "system_busy", "voice_limit_reached", "detected_unusual_activity", "http_401", "http_402", "http_429",
                  "missing_permission", "plan_required", "can_not_use_instant_voice_cloning", "network"}
PERMISSION_HELP = ("In elevenlabs.io ▸ Developers ▸ API Keys, edit your key and allow: Text to Speech, Voices (Read + Write), "
                   "Models (Read) and User (Read).")
PLAN_HELP = "Cloning your own voice through the API needs a paid ElevenLabs plan (Starter or higher); the free plan can't do it."

# tone → voice_settings for multilingual/flash models (stability lower = more expressive; style = emotion strength)
TONE_SETTINGS = {
    "neutral": (0.50, 0.10), "cheerful": (0.35, 0.45), "excited": (0.25, 0.60), "curious": (0.40, 0.35),
    "warm": (0.50, 0.30), "calm": (0.70, 0.05), "serious": (0.75, 0.10), "dramatic": (0.30, 0.65),
}
# v3 models understand inline audio tags
V3_TAGS = {"cheerful": "[cheerfully]", "excited": "[excited]", "curious": "[curious]", "warm": "[warmly]",
           "calm": "[calmly]", "serious": "[seriously]", "dramatic": "[dramatically]"}


class ElevenLabsError(Exception):
    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code

    @property
    def should_fallback(self):
        return self.code in FALLBACK_CODES


def _req(method, path, key, body=None, ctype="application/json", timeout=180, accept="application/json"):
    """One request; a dropped connection / timeout is retried once, then reported as a 'network' error (→ fallback)."""
    import http.client
    import socket
    for attempt in (1, 2):
        try:
            return _req_once(method, path, key, body, ctype, timeout, accept)
        except (http.client.HTTPException, ConnectionError, TimeoutError, socket.timeout) as e:
            if attempt == 2:
                raise ElevenLabsError(f"The connection to ElevenLabs dropped ({type(e).__name__}) — try again.", None, "network") from None
            import time
            time.sleep(1.5)


def _req_once(method, path, key, body=None, ctype="application/json", timeout=180, accept="application/json"):
    if not key:
        raise ElevenLabsError("No ElevenLabs API key saved (AI Voice tab ▸ ElevenLabs).", 401, "missing_api_key")
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"xi-api-key": key, "Content-Type": ctype, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code, msg = f"http_{e.code}", raw[:300]
        try:
            d = json.loads(raw).get("detail")
            if isinstance(d, dict):
                code, msg = d.get("status") or code, d.get("message") or msg
            elif isinstance(d, list) and d:
                msg = d[0].get("msg", msg)
        except Exception:
            pass
        import re
        perm = re.search(r"missing the permission (\w+)", msg or "")
        if perm:
            code = "missing_permission"
            raise ElevenLabsError(f"Your ElevenLabs API key isn't allowed to do this (missing “{perm.group(1)}”). {PERMISSION_HELP}", e.code, code) from None
        if e.code == 402 or "upgrade your subscription" in (msg or "").lower() or "free users" in (msg or "").lower():
            code = "plan_required" if code.startswith("http_") else code
            raise ElevenLabsError(f"ElevenLabs plan limit: {msg} {PLAN_HELP}", e.code, code) from None
        friendly = {"quota_exceeded": "ElevenLabs credits are used up", "invalid_api_key": "The ElevenLabs API key is not valid"}.get(code)
        raise ElevenLabsError(f"{friendly} ({msg})" if friendly else f"ElevenLabs error {e.code}: {msg}", e.code, code) from None
    except urllib.error.URLError as e:
        raise ElevenLabsError(f"Can't reach ElevenLabs ({e.reason}) — check the internet connection.", None, "network") from None


def capabilities(key) -> dict:
    """What this key/plan can do (no credits spent): credits (User read), voices (Voices read), models (Models read)."""
    out = {"credits": None, "voices": None, "models": [], "problems": []}
    try:
        out["credits"] = account(key)
        if (out["credits"].get("tier") or "").lower() == "free":
            out["problems"].append(PLAN_HELP)
    except ElevenLabsError as e:
        out["problems"].append(str(e))
    try:
        out["voices"] = len(json.loads(_req("GET", "/voices", key)).get("voices", []))
    except ElevenLabsError as e:
        out["problems"].append(str(e))
    try:
        out["models"] = models(key)
    except ElevenLabsError:
        out["models"] = [{"id": "eleven_multilingual_v2", "name": "Eleven Multilingual v2 (best likeness)"},
                         {"id": "eleven_v3", "name": "Eleven v3 (most expressive)"},
                         {"id": "eleven_flash_v2_5", "name": "Eleven Flash v2.5 (fast, cheaper)"}]
    out["problems"] = list(dict.fromkeys(out["problems"]))     # de-duplicate
    out["ready"] = not out["problems"]
    return out


def account(key) -> dict:
    """Remaining credits: {tier, used, limit, left, resets}."""
    u = json.loads(_req("GET", "/user", key))
    s = u.get("subscription", {})
    used, limit = s.get("character_count", 0), s.get("character_limit", 0)
    return {"tier": s.get("tier"), "used": used, "limit": limit, "left": max(0, limit - used),
            "resets": s.get("next_character_count_reset_unix"), "voice_slots": s.get("voice_limit")}


def models(key) -> list[dict]:
    ms = json.loads(_req("GET", "/models", key))
    return [{"id": m["model_id"], "name": m.get("name", m["model_id"])} for m in ms if m.get("can_do_text_to_speech")]


def default_voice(key) -> str:
    vs = json.loads(_req("GET", "/voices", key)).get("voices", [])
    pre = [v for v in vs if v.get("category") == "premade"] or vs
    if not pre:
        raise ElevenLabsError("No voices available on this ElevenLabs account.")
    return pre[0]["voice_id"]


CLONE_PIPELINE = "v2-mp3"          # bump to re-create every clone with a new sample pipeline


def create_clone(key, name: str, pieces: list[tuple[str, bytes]], denoise=False) -> str:
    """Instant Voice Clone from (filename, mp3 bytes) pieces → voice_id."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\nCreated by AnKar Video Editor from consented samples\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="remove_background_noise"\r\n\r\n{"true" if denoise else "false"}\r\n'.encode()]
    for fname, data in pieces:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{fname}"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()
                     + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    r = json.loads(_req("POST", "/voices/add", key, b"".join(parts), ctype=f"multipart/form-data; boundary={boundary}", timeout=300))
    return r["voice_id"]


def delete_clone(key, voice_id: str):
    try:
        _req("DELETE", f"/voices/{voice_id}", key)
    except ElevenLabsError:
        pass


def ensure_voice(key, voice_dir: Path, files: list[Path], denoise=False) -> str:
    """Instant Voice Clone from our samples; re-created when the samples / pipeline change. ID stored in voice.json."""
    meta_f = voice_dir / "voice.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    h = hashlib.sha1(json.dumps(sorted([f.name, f.stat().st_size] for f in files) + [CLONE_PIPELINE, bool(denoise)]).encode()).hexdigest()[:12]
    el = meta.get("elevenlabs") or {}
    if el.get("id") and el.get("hash") == h:
        return el["id"]
    if el.get("id"):                                        # samples changed → replace the old clone
        delete_clone(key, el["id"])
    vid = create_clone(key, f"VlogStudio - {voice_dir.name}", _sample_pieces(files), denoise)
    meta["elevenlabs"] = {"id": vid, "hash": h}
    meta_f.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return vid


def mp3_bytes(x, sr, bitrate=192000) -> bytes:
    """Mono float/int16 audio → MP3 bytes (ElevenLabs recommends MP3 ≥192 kbps for cloning; WAV can cause problems)."""
    import io
    import av
    import numpy as np
    y = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
    buf = io.BytesIO()
    out = av.open(buf, "w", format="mp3")
    s = out.add_stream("libmp3lame", rate=sr, layout="mono")
    s.bit_rate = bitrate
    fs = 1152
    for i in range(0, len(y), fs):
        fr = av.AudioFrame.from_ndarray(np.ascontiguousarray(y[i:i + fs]).reshape(1, -1), format="flt", layout="mono")
        fr.sample_rate, fr.pts = sr, i
        for p in s.encode(fr):
            out.mux(p)
    for p in s.encode():
        out.mux(p)
    out.close()
    return buf.getvalue()


def _sample_pieces(files, piece=45.0, total_max=180.0):
    """Split samples into ≤45 s MP3 (192 kbps) pieces, cut at quiet moments (ElevenLabs likes several medium-length clips)."""
    import numpy as np
    from scipy.io import wavfile
    out, total = [], 0.0
    for f in files:
        sr, x = wavfile.read(f)
        if x.ndim > 1:
            x = x.mean(axis=1).astype(x.dtype)
        n, i, k = int(piece * sr), 0, 0
        while i < len(x):
            j = min(len(x), i + n)
            if j < len(x):                                  # cut in the quietest 50 ms of the last 5 s
                hop = sr // 20
                look = x[max(i, j - 5 * sr):j].astype(np.float32)
                m = len(look) // hop
                if m > 2:
                    e = (look[: m * hop].reshape(m, hop) ** 2).mean(axis=1)
                    j = max(i, j - 5 * sr) + int(np.argmin(e)) * hop + hop // 2
            seg = x[i:j]
            i = j
            if len(seg) < 2 * sr:
                continue
            out.append((f"{f.stem}_{k}.mp3", mp3_bytes(seg, sr)))
            k += 1
            total += len(seg) / sr
            if total >= total_max or len(out) >= 24:
                return out
    return out


def voice_settings(tone="neutral", intensity=0.5, pace=1.0, model="eleven_multilingual_v2", user=None) -> dict:
    """The voice_settings ElevenLabs gets. user = config el_voice: {auto, stability, similarity, style, speaker_boost};
    auto → derived from the tone; otherwise the user's values (Stability: higher = steadier, more consistent delivery;
    Similarity: how closely to stick to the cloned voice; Style: exaggeration — adds emotion but also variation)."""
    stab, style = TONE_SETTINGS.get(tone, TONE_SETTINGS["neutral"])
    style = min(1.0, style * (0.5 + float(intensity)))
    u = user or {"auto": True}
    if "v3" in model:                                       # v3: emotion via inline tags; stability is 0 / 0.5 / 1 only
        s = 0.5 if u.get("auto", True) else min((0.0, 0.5, 1.0), key=lambda v: abs(v - u["stability"]))
        return {"stability": s, "similarity_boost": 0.8 if u.get("auto", True) else u["similarity"],
                "use_speaker_boost": True if u.get("auto", True) else u["speaker_boost"]}
    speed = round(min(1.2, max(0.7, float(pace))), 2)
    if u.get("auto", True):                                  # high similarity = sounds most like the cloned person
        return {"stability": max(0.35, stab), "similarity_boost": 0.9, "style": round(style, 2), "use_speaker_boost": True, "speed": speed}
    return {"stability": u["stability"], "similarity_boost": u["similarity"], "style": u["style"],
            "use_speaker_boost": u["speaker_boost"], "speed": speed}


def synthesize(key, voice_id, text, tone="neutral", intensity=0.5, pace=1.0, model="eleven_multilingual_v2", user=None,
               fmt="mp3_44100_128") -> bytes:
    """Encoded audio bytes (default MP3 44.1 kHz 128 kbps — every plan; opus_48000_192 also works on Starter)."""
    if "v3" in model:
        tag = V3_TAGS.get(tone)
        text = f"{tag} {text}" if tag else text
    settings = voice_settings(tone, intensity, pace, model, user)
    body = {"text": text, "model_id": model, "voice_settings": settings}
    return _req("POST", f"/text-to-speech/{voice_id}?output_format={fmt}", key, body,
                accept="audio/mpeg" if fmt.startswith("mp3") else "*/*", timeout=300)
