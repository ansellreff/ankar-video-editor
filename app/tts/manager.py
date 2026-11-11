"""Voices + AI narration jobs (editor side). The heavy model runs in a separate process (.venv-tts, worker.py)."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
from scipy.io import wavfile
from scipy.signal import istft, resample_poly, stft

from ..paths import CACHE, GENERATED_NARRATION, ROOT, VOICES, WORK, rel
from . import base

GENERATED = GENERATED_NARRATION          # library/generated/narration (shared cache of AI narration)
# local voice engine: runtime-tts\ (portable, made by "Install local AI voice (optional).bat") or the dev .venv-tts
TTS_PY = next((p for p in (ROOT / "runtime-tts" / "python.exe", ROOT / ".venv-tts" / "Scripts" / "python.exe") if p.exists()),
              ROOT / ".venv-tts" / "Scripts" / "python.exe")
SR = 48000


# ------------------------------------------------------------------ audio helpers
def to_mono48(x: np.ndarray, sr: int) -> np.ndarray:
    if x.dtype.kind in "iu":                                   # integer PCM → [-1, 1]
        x = x.astype(np.float32) / float(np.iinfo(x.dtype).max + 1)
    else:
        x = x.astype(np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1 if x.shape[1] <= 8 else 0)
    if sr != SR:
        from math import gcd
        g = gcd(SR, sr)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def trim_silence(x: np.ndarray, thr_db=-42.0, pad=0.06) -> np.ndarray:
    hop = int(SR * 0.01)
    n = len(x) // hop
    if n < 3:
        return x
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    idx = np.where(db > max(thr_db, db.max() - 45))[0]
    if not len(idx):
        return x
    a = max(0, idx[0] * hop - int(pad * SR))
    b = min(len(x), (idx[-1] + 1) * hop + int(pad * SR))
    return x[a:b]


def speech_runs(x: np.ndarray, min_len=1.5, gap=0.35) -> list[np.ndarray]:
    """Continuous speech stretches (pauses shorter than `gap` s are kept inside a run)."""
    hop = int(SR * 0.02)
    n = len(x) // hop
    if n < 5:
        return []
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    voiced = db > max(-45.0, db.max() - 35)
    out, i = [], 0
    g = int(gap / 0.02)
    while i < n:
        if voiced[i]:
            j = i
            while j < n and (voiced[j] or voiced[j:j + g].any()):
                j += 1
            if (j - i) * 0.02 >= min_len:
                out.append(x[max(0, i * hop - hop * 3): min(len(x), j * hop + hop * 3)])
            i = j
        else:
            i += 1
    return out


def denoise(x: np.ndarray) -> np.ndarray:
    """Gentle spectral gating: estimate the noise floor per frequency, attenuate bins near it."""
    f, t, Z = stft(x, SR, nperseg=1024, noverlap=768)
    mag = np.abs(Z)
    noise = np.percentile(mag, 12, axis=1, keepdims=True)
    mask = np.clip((mag - 1.6 * noise) / (mag + 1e-9), 0.08, 1.0)
    from scipy.ndimage import uniform_filter
    mask = uniform_filter(mask, size=(3, 5))
    _, y = istft(Z * mask, SR, nperseg=1024, noverlap=768)
    return y[: len(x)].astype(np.float32)


def normalize(x: np.ndarray, lufs=-16.0) -> np.ndarray:
    if len(x) < SR * 0.4 or np.abs(x).max() < 1e-5:
        return x
    loud = pyln.Meter(SR).integrated_loudness(x.astype(np.float64))
    if np.isfinite(loud):
        x = x * 10 ** ((lufs - loud) / 20)
    pk = np.abs(x).max()
    return (x * (0.89 / pk) if pk > 0.89 else x).astype(np.float32)


def save_wav(path: Path, x: np.ndarray):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))


def wav_to_mp3(src: Path, dst: Path, bitrate=192000) -> Path:
    """MP3 (44.1 kHz stereo, 192 kbps) — plays everywhere (phones, WhatsApp, editors)."""
    import av
    sr, x = wavfile.read(src)
    y = to_mono48(x, sr)
    y = resample_poly(y, 147, 160).astype(np.float32)          # 48 kHz → 44.1 kHz
    st = np.ascontiguousarray(np.stack([y, y]))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dst), "w") as out:
        s = out.add_stream("libmp3lame", rate=44100, layout="stereo")
        s.bit_rate = bitrate
        fs = s.codec_context.frame_size or 1152
        for i in range(0, st.shape[1], fs):
            fr = av.AudioFrame.from_ndarray(np.ascontiguousarray(st[:, i:i + fs]), format="fltp", layout="stereo")
            fr.sample_rate, fr.pts = 44100, i
            for p in s.encode(fr):
                out.mux(p)
        for p in s.encode():
            out.mux(p)
    return dst


# ------------------------------------------------------------------ voices
class Voices:
    @staticmethod
    def list():
        out = []
        if not VOICES.exists():
            return out
        for d in sorted(p for p in VOICES.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            meta = {}
            if (d / "voice.json").exists():
                try:
                    meta = json.loads((d / "voice.json").read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            samples = []
            for f in sorted(d.iterdir()):
                if f.suffix.lower() not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
                    continue
                mood = f.stem.split("_")[0].lower()
                try:
                    sr, x = wavfile.read(f) if f.suffix.lower() == ".wav" else (None, None)
                    dur = round(len(x) / sr, 1) if sr else None
                except Exception:
                    dur = None
                samples.append({"file": rel(f), "name": f.name, "mood": mood if mood in base.MOODS else "neutral", "dur": dur})
            out.append({"name": d.name, "consent": bool(meta.get("consent")), "created": meta.get("created"),
                        "samples": samples, "total": round(sum(s["dur"] or 0 for s in samples), 1)})
        return out

    @staticmethod
    def create(name: str, consent: bool, note=""):
        name = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip()[:40]
        if not name:
            raise ValueError("give the voice a name")
        if not consent:
            raise ValueError("please confirm you have permission to use this person's voice")
        d = VOICES / name
        d.mkdir(parents=True, exist_ok=True)
        meta = {"consent": True, "created": datetime.now().isoformat(timespec="minutes"), "note": note}
        (d / "voice.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return name

    @staticmethod
    def add_sample(voice: str, mood: str, x: np.ndarray, clean=False) -> str:
        d = VOICES / voice
        if not (d / "voice.json").exists():
            raise ValueError(f"create the voice “{voice}” first")
        mood = mood if mood in base.MOODS else "neutral"
        x = trim_silence(x)
        if clean:
            x = denoise(x)
        x = normalize(x, -18.0)
        if len(x) < SR * 2:
            raise ValueError("the sample is shorter than 2 seconds of speech — pick a longer part")
        n = 1 + max([int(p.stem.split("_")[-1]) for p in d.glob(f"{mood}_*.wav") if p.stem.split("_")[-1].isdigit()] + [0])
        f = d / f"{mood}_{n}.wav"
        save_wav(f, x)
        return rel(f)

    @staticmethod
    def add_source(voice: str, src: dict):
        """Remember where a voice's samples came from (shown in the UI; lets 'rebuild' know the recording)."""
        f = VOICES / voice / "voice.json"
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        meta.setdefault("sources", []).append({**src, "added": datetime.now().isoformat(timespec="minutes")})
        meta["sources"] = meta["sources"][-10:]
        f.write_text(json.dumps(meta, indent=1), encoding="utf-8")

    # ---- fixing mistakes: everything removed goes to cache/trash/ (recoverable), never straight to oblivion
    @staticmethod
    def _trash(src: Path, label: str) -> Path:
        import shutil
        dst = CACHE / "trash" / f"{datetime.now():%Y%m%d_%H%M%S}_{label}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst

    @staticmethod
    def _forget_clone(d: Path):
        """Remove this voice's ElevenLabs clone (best effort) so a deleted voice doesn't live on in the account."""
        try:
            meta = json.loads((d / "voice.json").read_text(encoding="utf-8"))
            vid = (meta.get("elevenlabs") or {}).get("id")
            if vid:
                from . import elevenlabs
                from .. import config
                elevenlabs._req("DELETE", f"/voices/{vid}", config.get_secret("elevenlabs_api_key"))
        except Exception:  # noqa: BLE001 - missing key/permission: the local data is still removed
            pass

    @staticmethod
    def _clear_refs():
        for f in WORK.glob("voiceref_*.wav"):
            f.unlink(missing_ok=True)

    @staticmethod
    def delete(name: str) -> str:
        d = VOICES / name
        if not d.is_dir() or name.startswith((".", "_")):
            raise ValueError(f"no voice “{name}”")
        Voices._forget_clone(d)
        dst = Voices._trash(d, f"voice_{name}")
        Voices._clear_refs()
        return rel(dst)

    @staticmethod
    def rename(old: str, new: str) -> str:
        new = "".join(ch for ch in new if ch.isalnum() or ch in " -_").strip()[:40]
        src, dst = VOICES / old, VOICES / new
        if not src.is_dir():
            raise ValueError(f"no voice “{old}”")
        if not new:
            raise ValueError("give the voice a name")
        if dst.exists() and dst.resolve() != src.resolve():
            raise ValueError(f"a voice called “{new}” already exists — move its samples instead")
        src.rename(dst)
        return new

    @staticmethod
    def move_sample(file: str, voice: str, mood: str | None = None) -> str:
        """Move a sample to another voice (uploaded under the wrong person) and/or change its mood tag."""
        p = ROOT / file
        d = VOICES / voice
        if not p.exists() or VOICES not in p.parents:
            raise ValueError("unknown sample")
        if not (d / "voice.json").exists():
            raise ValueError(f"no voice “{voice}”")
        mood = mood if mood in base.MOODS else p.stem.split("_")[0]
        n = 1 + max([int(q.stem.split("_")[-1]) for q in d.glob(f"{mood}_*.wav") if q.stem.split("_")[-1].isdigit()] + [0])
        dst = d / f"{mood}_{n}{p.suffix}"
        p.rename(dst)
        Voices._clear_refs()
        return rel(dst)

    @staticmethod
    def delete_sample(file: str) -> str:
        p = ROOT / file
        if not p.exists() or VOICES not in p.parents:
            raise ValueError("unknown sample")
        dst = Voices._trash(p, f"sample_{p.parent.name}_{p.name}")
        Voices._clear_refs()
        return rel(dst)

    @staticmethod
    def reset_all() -> dict:
        """Start voice training from scratch: every voice (+ its ElevenLabs clone) and the speaker-extraction cache go to
        cache/trash/<time>_voices_reset/."""
        import shutil
        names = [v["name"] for v in Voices.list()]
        dst = CACHE / "trash" / f"{datetime.now():%Y%m%d_%H%M%S}_voices_reset"
        dst.mkdir(parents=True, exist_ok=True)
        for n in names:
            Voices._forget_clone(VOICES / n)
            shutil.move(str(VOICES / n), str(dst / n))
        spk = WORK / "speakers"
        if spk.exists():
            shutil.move(str(spk), str(dst / "speaker_extraction_cache"))
        Voices._clear_refs()
        from . import speakers
        speakers.JOBS.clear()
        return {"voices": names, "backup": rel(dst)}

    @staticmethod
    def reference(voice: str, mood: str) -> str | None:
        """Reference clip for the local engine (it listens to ~10 s): the longest continuous stretches of clean speech
        from this mood's samples (else neutral, else all), up to 12 s — not many short pieces glued together."""
        d = VOICES / voice
        if not d.exists():
            return None
        files = sorted(d.glob("*.wav"))
        pick = [f for f in files if f.stem.split("_")[0] == mood] or [f for f in files if f.stem.split("_")[0] == "neutral"] or files
        if not pick:
            return None
        key = hashlib.sha1(json.dumps([[str(f), f.stat().st_mtime] for f in pick] + ["v2"]).encode()).hexdigest()[:10]
        out = WORK / f"voiceref_{key}.wav"
        if not out.exists():
            runs = []
            for f in pick:
                sr, x = wavfile.read(f)
                runs += speech_runs(to_mono48(x, sr))
            runs.sort(key=len, reverse=True)
            parts, total = [], 0.0
            for r in runs:
                parts += [r, np.zeros(int(SR * 0.15), np.float32)]
                total += len(r) / SR
                if total >= 12:
                    break
            save_wav(out, normalize(np.concatenate(parts)[: SR * 12], -18.0))
        return str(out)


# ------------------------------------------------------------------ jobs
class TTSManager:
    def __init__(self, notify, on_done):
        self.notify, self.on_done = notify, on_done
        self.q: queue.Queue = queue.Queue()
        self.proc = None
        self.lock = threading.Lock()
        self.rid = 0
        self.jobs: dict[str, dict] = {}
        self.engine = "idle"
        threading.Thread(target=self._run, daemon=True, name="tts").start()

    @staticmethod
    def installed() -> bool:
        return TTS_PY.exists()

    def status(self):
        from .. import config
        return {"installed": self.installed(), "engine": self.engine, "jobs": self.jobs, "tones": base.TONES,
                "moods": base.MOODS, "providers": base.PROVIDERS, "config": config.public_tts_config()}

    # -------------------------------------------------------------- worker process
    def _ensure(self):
        if self.proc and self.proc.poll() is None:
            return
        env = {**os.environ, "HF_HOME": str(ROOT / "models" / "tts" / "hf"), "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "PYTHONUNBUFFERED": "1"}
        log = open(WORK / "tts_worker.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen([str(TTS_PY), "-m", "app.tts.worker"], cwd=str(ROOT), env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        first = json.loads(self.proc.stdout.readline() or "{}")
        if not first.get("ready"):
            raise RuntimeError("the voice engine did not start (see cache/work/tts_worker.log)")

    def _call(self, **req):
        with self.lock:
            self._ensure()
            self.rid += 1
            req["id"] = self.rid
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("the voice engine stopped (see cache/work/tts_worker.log)")
                r = json.loads(line)
                if r.get("id") == self.rid:
                    if not r.get("ok"):
                        raise RuntimeError(r.get("error", "voice engine error"))
                    return r

    def isolate(self, wav_in: str, wav_out: str) -> dict:
        """Vocals only (music/background removed) via Demucs in the local engine process."""
        if not self.installed():
            raise RuntimeError("voice isolation needs the local engine (.venv-tts)")
        return self._call(cmd="isolate", **{"in": wav_in, "out": wav_out})

    def embed(self, wav: str, segments) -> list:
        """Voice fingerprints for time windows of a wav (speaker detection). Runs in the local engine process."""
        if not self.installed():
            raise RuntimeError("speaker detection needs the local engine (.venv-tts)")
        return self._call(cmd="embed", wav=wav, segments=[[float(s), float(e)] for s, e in segments])["embeds"]

    # -------------------------------------------------------------- queue
    def submit(self, clip: dict):
        cid = clip["id"]
        self.jobs[cid] = {"clip": cid, "state": "queued", "t": time.time()}
        self.notify("tts", self.jobs[cid])
        self.q.put(json.loads(json.dumps(clip)))

    def _stage(self, cid, stage, estimate=None):
        """Progress for the UI: what is happening now + expected seconds for this stage."""
        j = self.jobs.get(cid) or {"clip": cid}
        j.update(state="running", stage=stage, stage_t=time.time(), estimate=estimate)
        self.jobs[cid] = j
        self.notify("tts", j)

    def _run(self):
        while True:
            clip = self.q.get()
            cid = clip["id"]
            try:
                self.jobs[cid] = {"clip": cid, "state": "running", "t": time.time()}
                self._stage(cid, "Starting", 2)
                if self.engine != "ready":
                    self.engine = "loading"
                    self.notify("tts_engine", {"engine": "loading"})
                res = self.generate(clip)
                self.engine = "ready"
                self.jobs[cid] = {"clip": cid, "state": "done", **res}
                self.notify("tts", self.jobs[cid])
                self.on_done(cid, res)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.jobs[cid] = {"clip": cid, "state": "error", "error": str(e)}
                self.notify("tts", self.jobs[cid])
                self.notify("toast", {"text": f"Narration failed: {e}", "kind": "error"})

    # -------------------------------------------------------------- engines
    def _synth_local(self, text, ref, p, key):
        if not self.installed():
            raise RuntimeError("the local voice engine isn't installed (double-click 'Install local AI voice (optional).bat', or use ElevenLabs)")
        raw = WORK / f"tts_raw_{key}.wav"
        r = self._call(cmd="synth", text=text, ref=ref, exaggeration=p["exaggeration"], cfg=p["cfg"], out=str(raw))
        sr, x = wavfile.read(raw)
        raw.unlink(missing_ok=True)
        return to_mono48(x, sr), r.get("secs")

    def _synth_eleven(self, text, voice, tts, cfg):
        import io
        import av
        from .. import config
        from . import elevenlabs as el
        key = config.get_secret("elevenlabs_api_key")
        if voice:
            files = sorted((VOICES / voice).glob("*.wav"))
            if not files:
                raise el.ElevenLabsError(f"voice “{voice}” has no samples yet")
            voice_id = el.ensure_voice(key, VOICES / voice, files, denoise=bool(cfg.get("el_clone_denoise")))
        else:
            voice_id = getattr(self, "_el_default", None) or el.default_voice(key)
            self._el_default = voice_id
        t = time.time()
        mp3 = el.synthesize(key, voice_id, text, tts.get("tone", "neutral"), tts.get("intensity", 0.5), tts.get("pace", 1.0),
                            cfg.get("el_model") or "eleven_multilingual_v2", user=cfg.get("el_voice"),
                            fmt=cfg.get("el_format") or "mp3_44100_128")
        chunks = []
        with av.open(io.BytesIO(mp3)) as c:
            rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
            for fr in c.decode(audio=0):
                chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(fr)]
            chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(None)]
        return np.concatenate(chunks).astype(np.float32), round(time.time() - t, 1)

    def _generate_dialogue(self, clip, tts, cfg, voice, text):
        """Natural-conversation line (Eleven v4 Text to Dialogue): performed in one go — no sentence splitting or time
        stretching — with the Emotion slider (tts.intensity) scaling the delivery cue, and the previous line of the
        conversation (tts.ctx_prev) as context. Returns real word times for the captions."""
        from .. import config
        from . import dialogue
        from . import elevenlabs as el
        key = config.get_secret("elevenlabs_api_key")
        files = sorted((VOICES / voice).glob("*.wav"))
        if not files:
            raise el.ElevenLabsError(f"voice “{voice}” has no samples yet")
        vid = el.ensure_voice(key, VOICES / voice, files, denoise=bool(cfg.get("el_clone_denoise")))
        emo = float(tts.get("intensity") if tts.get("intensity") is not None else 0.2)
        t0 = time.time()
        self._stage(clip["id"], "ElevenLabs v4 is performing the line", 5 + len(text) / 30)
        r = dialogue.generate(key, [{"voice_id": vid, "text": dialogue.tag(text, tts.get("tone"), emo), "display": text}],
                              model=tts.get("model") or "eleven_v4", stability=dialogue.stability_for(emo),
                              seed=7 + int(tts.get("take") or 0), previous_text=tts.get("ctx_prev"))
        ln = r["lines"][0] if r["lines"] else {"start": 0.0, "end": len(r["audio"]) / r["sr"], "words": []}
        y = dialogue.cut(r["audio"], r["sr"], ln["start"], ln["end"])
        origin = max(0.0, ln["start"] - 0.06)
        words = [{"w": w["w"], "t0": round(w["t0"] - origin, 3), "t1": round(w["t1"] - origin, 3)} for w in ln["words"]]
        out = GENERATED / f"dlg_{r['key']}_0.wav"
        save_wav(out, normalize(y))
        dur = round(len(y) / SR, 3)
        a = words[0]["t0"] if words else 0.06
        b = words[-1]["t1"] if words else dur - 0.18
        segs = [{"text": text, "a": round(a, 4), "b": round(b, 4)}]
        (out.with_suffix(".json")).write_text(json.dumps({"segs": segs, "words": words, "mode": "dialogue"}), encoding="utf-8")
        return {"file": rel(out), "engine": "elevenlabs", "segs": segs, "words": words, "dur": dur,
                "secs": round(time.time() - t0, 1), "fitted": True}

    # Each voice's natural speaking rate (learned from its generations) → ElevenLabs is asked for roughly the right
    # `speed` up front, so the final time-stretch only fine-tunes (big stretches sound processed).
    RATES_FILE = WORK / "voice_rates.json"

    def _rate_key(self, engine, voice, cfg):
        return json.dumps([engine, voice, cfg.get("el_model"), cfg.get("el_voice")], sort_keys=True)

    def _voice_rate(self, key):
        try:
            return json.loads(self.RATES_FILE.read_text(encoding="utf-8")).get(key)
        except Exception:
            return None

    def _learn_rate(self, key, wpm):
        try:
            d = json.loads(self.RATES_FILE.read_text(encoding="utf-8")) if self.RATES_FILE.exists() else {}
        except Exception:
            d = {}
        old = d.get(key)
        d[key] = round(wpm if not old else old * 0.5 + wpm * 0.5)
        self.RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.RATES_FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")

    def _piece(self, text, voice, ref, p, tts, cfg, engine, take, cid, label, est, speed=1.0):
        """One sentence of narration (cached per sentence + take). Returns (audio, engine actually used)."""
        from . import pronounce
        text = pronounce.apply(text)                     # Taiwanese names respelled for the voice (captions keep the real text)
        model = cfg.get("el_model") if engine == "elevenlabs" else "chatterbox"
        elv = cfg.get("el_voice") if engine == "elevenlabs" else None      # changing ElevenLabs settings = new take
        speed = speed if engine == "elevenlabs" else 1.0
        k = hashlib.sha1(json.dumps([text, voice, ref and Path(ref).name, p["exaggeration"], p["cfg"], engine, model, take, elv,
                                     tts.get("tone"), tts.get("intensity")] + ([speed] if speed != 1.0 else [])).encode()).hexdigest()[:14]
        f = WORK / "tts_pieces" / f"{k}.wav"
        if f.exists():
            sr, x = wavfile.read(f)
            return x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0), engine
        f.parent.mkdir(parents=True, exist_ok=True)
        used = engine
        if engine == "elevenlabs":
            from .elevenlabs import ElevenLabsError
            try:
                self._stage(cid, f"ElevenLabs is speaking {label}", est)
                y, _ = self._synth_eleven(text, voice, {**tts, "pace": speed}, cfg)
            except ElevenLabsError as e:
                if not (cfg.get("fallback", True) and e.should_fallback and self.installed()):
                    raise
                if not getattr(self, "_warned", False):
                    self.notify("toast", {"text": f"{e} — made with the local voice instead.", "kind": "error"})
                    self._warned = True
                return self._piece(text, voice, ref, p, tts, cfg, "local", take, cid, label, est)
        else:
            self._stage(cid, ("Loading the voice model, then speaking " if self.engine != "ready" else "The AI voice is speaking ") + label, est)
            y, _ = self._synth_local(text, ref, p, k)
        save_wav(f, y)
        return y, used

    def _match(self, voice, out: Path):
        """Voice match % of a generated file vs the voice's samples (cached in <file>.match.json)."""
        if not voice or not self.installed():
            return None
        side = out.with_suffix(".match.json")
        try:
            d = json.loads(side.read_text(encoding="utf-8"))
            if d.get("mtime") == out.stat().st_mtime and d.get("voice") == voice:
                return d["match"]
        except Exception:
            pass
        try:
            from . import similarity
            ref = similarity.voice_fingerprint(self.embed, VOICES / voice)
            if ref is None:
                return None
            m = similarity.match(ref, similarity.fingerprint(self.embed, out))
            side.write_text(json.dumps({"mtime": out.stat().st_mtime, "voice": voice, "match": m}), encoding="utf-8")
            return m
        except Exception:  # noqa: BLE001 - a missing score must never fail the narration
            traceback.print_exc()
            return None

    def generate(self, clip: dict) -> dict:
        info = self._generate(clip)
        voice = (clip.get("tts") or {}).get("voice")
        if voice:
            self._stage(clip["id"], "Checking how much it sounds like the voice", 3)
            info["match"] = self._match(voice, ROOT / info["file"])
        return info

    def _generate(self, clip: dict) -> dict:
        from .. import config
        from . import pacing
        tts = clip.get("tts") or {}
        text = (tts.get("text") or "").strip()
        if not text:
            raise ValueError("type the narration text first")
        cfg = config.tts_settings()
        engine = cfg["engine"]
        p = base.resolve(tts.get("tone", "neutral"), tts.get("intensity"), tts.get("pace"))
        voice = tts.get("voice")
        ref = Voices.reference(voice, tts.get("tone", "neutral")) if voice else None
        target = float(clip.get("dur", 0)) if tts.get("fit", True) else None
        steady = tts.get("steady", True)
        rkey = self._rate_key(engine, voice, cfg)
        hint = 1.0                                                  # ElevenLabs speed, from the voice's known pace
        want = pacing.RATES.get(tts.get("rate"), tts.get("rate")) if tts.get("rate") else None
        known = self._voice_rate(rkey)
        if steady and engine == "elevenlabs" and want and known:
            hint = round(min(1.1, max(0.9, float(want) / known)) * 20) / 20         # ±10% only: lower ElevenLabs speeds sound unnatural
        pace_opts = [tts.get("rate"), round(float(tts.get("pause") or 1.0), 2), int(tts.get("take") or 0), steady, "pace5", hint]

        from . import pronounce
        said = pronounce.apply(text)

        def cache_key(eng):
            model = cfg.get("el_model") if eng == "elevenlabs" else "chatterbox"
            elv = cfg.get("el_voice") if eng == "elevenlabs" else None
            parts = [text, voice, ref and Path(ref).name, p, target, eng, model, pace_opts, elv] + ([said] if said != text else [])
            return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:12]

        if tts.get("mode") == "dialogue" and engine == "elevenlabs" and voice:
            return self._generate_dialogue(clip, tts, cfg, voice, text)
        if steady:
            key = cache_key(engine)
            out = GENERATED / f"tts_{key}.wav"
            info = {"file": rel(out), "params": p, "engine": engine}
            if not out.exists():
                pieces = pacing.split_text(text)
                if not pieces:
                    raise ValueError("type the narration text first")
                audio, used_all, t0 = [], set(), time.time()
                self._warned = False
                for i, pc in enumerate(pieces):
                    est = pacing.words(pc["text"]) / 2.6 * (1 if engine == "elevenlabs" else 7) + (25 if self.engine != "ready" and i == 0 else 2)
                    y, used = self._piece(pc["text"], voice, ref, p, tts, cfg, engine, int(tts.get("take") or 0), clip["id"],
                                          f"(sentence {i + 1} of {len(pieces)})" if len(pieces) > 1 else "", est, speed=hint)
                    self.engine = "ready" if used == "local" else self.engine
                    audio.append(y)
                    used_all.add(used)
                self._stage(clip["id"], "Evening out the pace and pauses", 2)
                y, pinfo = pacing.assemble(pieces, audio, rate=tts.get("rate"), pause_scale=tts.get("pause") or 1.0,
                                           target=target, pace=tts.get("pace") or 1.0)
                used = "local" if "local" in used_all else engine
                if used == engine and pinfo.get("voice_wpm"):         # remember how fast this voice talks at speed 1.0
                    self._learn_rate(rkey, pinfo["voice_wpm"] / hint)
                pinfo["el_speed"] = hint
                if used != engine:
                    key = cache_key(used)
                    out = GENERATED / f"tts_{key}.wav"
                    info.update(file=rel(out), engine=used)
                info["secs"] = round(time.time() - t0, 1)
                save_wav(out, normalize(y))
                (out.with_suffix(".json")).write_text(json.dumps(pinfo), encoding="utf-8")
            meta = out.with_suffix(".json")
            pinfo = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            sr, x = wavfile.read(out)
            info["dur"] = round(len(x) / sr, 3)
            info["wpm"] = pinfo.get("wpm")
            info["pieces"] = pinfo.get("pieces")
            info["limited"] = bool(pinfo.get("limited"))
            info["segs"] = pinfo.get("segs")
            if target:
                info["fitted"] = bool(pinfo.get("fitted"))
                if not info["fitted"]:
                    info["natural"] = info["dur"]
            return info
        # ---- classic: the whole line in one go (rhythm is up to the voice model)

        key = cache_key(engine)
        out = GENERATED / f"tts_{key}.wav"
        info = {"file": rel(out), "params": p, "engine": engine}
        cid = clip["id"]
        words = max(1, len(text.split()))
        local_est = words / 2.6 * 7 + (25 if self.engine != "ready" else 3)     # CPU ≈ 7× real time + model load
        if not out.exists():
            used = engine
            if engine == "elevenlabs":
                from .elevenlabs import ElevenLabsError
                try:
                    self._stage(cid, "ElevenLabs is speaking (first use of a voice also uploads it)", 6 + words / 8)
                    y, info["secs"] = self._synth_eleven(said, voice, tts, cfg)
                except ElevenLabsError as e:
                    if not (cfg.get("fallback", True) and e.should_fallback and self.installed()):
                        raise
                    self.notify("toast", {"text": f"{e} — made with the local voice instead.", "kind": "error"})
                    used = "local"
                    self._stage(cid, "ElevenLabs unavailable — the local engine is speaking", local_est)
                    y, info["secs"] = self._synth_local(said, ref, p, key)
            else:
                self._stage(cid, "Loading the voice model, then speaking" if self.engine != "ready" else "The AI voice is speaking", local_est)
                y, info["secs"] = self._synth_local(said, ref, p, key)
            self._stage(cid, "Finishing (cleaning up and saving)", 2)
            if used != engine:                                  # don't cache a fallback under the ElevenLabs key
                key = cache_key(used)
                out = GENERATED / f"tts_{key}.wav"
                info.update(file=rel(out), engine=used)
            y = trim_silence(y)
            from ..render.audio import stretch
            if used == "local" and abs(p["pace"] - 1) > 0.01:  # pace (ElevenLabs applies speed itself)
                y = stretch(np.stack([y, y]), p["pace"], int(len(y) / p["pace"]), True)[0]
            natural = len(y) / SR
            if target:
                ratio = natural / max(target, 0.1)
                if 0.92 <= ratio <= 1.09:                       # small fits only — bigger stretches sound robotic
                    y = stretch(np.stack([y, y]), ratio, int(round(target * SR)), True)[0]
                    info["fitted"] = True
                else:
                    info["fitted"] = False
                    info["natural"] = round(natural, 3)
            save_wav(out, normalize(y))
        sr, x = wavfile.read(out)
        info["dur"] = round(len(x) / sr, 3)
        if target and "fitted" not in info:                    # cached file: work out whether it matched the clip
            info["fitted"] = abs(info["dur"] - target) < 0.05
            if not info["fitted"]:
                info["natural"] = info["dur"]
        return info
