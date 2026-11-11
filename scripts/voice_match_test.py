"""Measured voice-match test (ElevenLabs): which sample pipeline / model / settings sound most like the real person?

For each voice: the same two sentences are generated under several variants and scored against the person's ORIGINAL
recording with the speaker-verification encoder (app/tts/similarity.py). Every take is saved as MP3 next to a score
table in library/reports/voice_tests/<date>/ so you can listen. Temporary clones are deleted at the end. Credit cap: --cap.

Usage: .venv\\Scripts\\python.exe scripts\\voice_match_test.py [--cap 4000]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import config  # noqa: E402
from app.tts import elevenlabs as el  # noqa: E402
from app.tts import similarity as sim  # noqa: E402
from app.tts import speakers  # noqa: E402
from app.tts.manager import VOICES, TTSManager, wav_to_mp3  # noqa: E402

TEXT = "Hi everyone! After a busy week at work, we finally made it to Kaohsiung. Tomorrow we're riding our bikes to the theme park."
REC = "projects/vlog/assets/audio/voiceover"          # the original recordings (kept in the archived "vlog" project)
VOICES_TO_TEST = {
    "Karina": {"original": f"{REC}/Karina voice.m4a"},
    "Ansell": {"original": f"{REC}/Ansell Voice.mp3", "enhanced": f"{REC}/Ansell enhanced voice.mp3"},
}
STEADY = {"auto": False, "stability": 0.75, "similarity": 0.85, "style": 0.0, "speaker_boost": True}


def decode(data: bytes) -> tuple[np.ndarray, int]:
    import av
    chunks = []
    with av.open(io.BytesIO(data)) as c:
        rs = av.AudioResampler(format="flt", layout="mono", rate=48000)
        for fr in c.decode(audio=0):
            chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(fr)]
        chunks += [r.to_ndarray().reshape(-1) for r in rs.resample(None)]
    return np.concatenate(chunks).astype(np.float32), 48000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=4000)
    args = ap.parse_args()
    key = config.get_secret("elevenlabs_api_key")
    out = ROOT / "library" / "reports" / "voice_tests" / datetime.now().strftime("%Y-%m-%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)
    tts = TTSManager(notify=lambda *a: None, on_done=lambda *a: None)
    start = el.account(key)
    print(f"credits before: {start['left']:,} ({start['tier']})")
    temp_clones, rows = [], []

    def spent():
        return el.account(key)["used"] - start["used"]

    def make_clone(label, src_path, denoise=False):
        """New-pipeline sample (clean source, purity filter, −20 LUFS, MP3 192k) → temporary clone."""
        job = speakers.detect(str(ROOT / src_path), 0, 600, 0.0, tts.embed, n_speakers=1, isolate_fn=tts.isolate)
        info = {}
        x = speakers.speaker_audio(job["id"], job["speakers"][0]["id"], max_sec=150, info=info)
        tmp = out / f"_sample_{label}.wav"
        wavfile.write(tmp, 48000, (np.clip(x, -1, 1) * 32767).astype(np.int16))
        vid = el.create_clone(key, f"VlogStudio test - {label}", el._sample_pieces([tmp]), denoise)
        temp_clones.append(vid)
        print(f"  clone {label}: {info}  clean_source={job['clean_source']}  denoise={denoise}")
        tmp.unlink(missing_ok=True)
        return vid, info

    try:
        for voice, srcs in VOICES_TO_TEST.items():
            print(f"\n=== {voice}")
            refs = {k: sim.fingerprint(tts.embed, ROOT / p) for k, p in srcs.items()}
            meta = json.loads((VOICES / voice / "voice.json").read_text(encoding="utf-8"))
            base_id = (meta.get("elevenlabs") or {}).get("id")
            clean_id, _ = make_clone(f"{voice}-clean", srcs["original"])
            variants = []
            if base_id:
                variants.append(("A baseline (current clone, Steady)", base_id, "eleven_multilingual_v2", STEADY, "mp3_44100_128"))
            variants += [
                ("B clean re-clone (Steady)", clean_id, "eleven_multilingual_v2", STEADY, "mp3_44100_128"),
                ("C clean, stability 0.5", clean_id, "eleven_multilingual_v2", {**STEADY, "stability": 0.5}, "mp3_44100_128"),
                ("D clean, stab 0.5 + similarity 1.0", clean_id, "eleven_multilingual_v2", {**STEADY, "stability": 0.5, "similarity": 1.0}, "mp3_44100_128"),
                ("E clean, model eleven_v4", clean_id, "eleven_v4", {**STEADY, "stability": 0.5}, "mp3_44100_128"),
                ("F clean, model eleven_v3", clean_id, "eleven_v3", {**STEADY, "stability": 0.5}, "mp3_44100_128"),
                ("G clean, opus 48k/192", clean_id, "eleven_multilingual_v2", {**STEADY, "stability": 0.5}, "opus_48000_192"),
            ]
            if spent() < args.cap - 600:
                dn_id, _ = make_clone(f"{voice}-clean-denoise", srcs["original"], denoise=True)
                variants.append(("H clean + background-noise removal", dn_id, "eleven_multilingual_v2", {**STEADY, "stability": 0.5}, "mp3_44100_128"))
            if "enhanced" in srcs and spent() < args.cap - 600:
                en_id, _ = make_clone(f"{voice}-enhanced", srcs["enhanced"])
                variants.append(("I clone from the ENHANCED file", en_id, "eleven_multilingual_v2", {**STEADY, "stability": 0.5}, "mp3_44100_128"))
            for label, vid, model, vs, fmt in variants:
                if spent() > args.cap - 200:
                    print("  credit cap reached — stopping")
                    break
                t = time.time()
                try:
                    data = el.synthesize(key, vid, TEXT, "neutral", 0.5, 1.0, model, user=vs, fmt=fmt)
                except el.ElevenLabsError as e:
                    print(f"  {label}: FAILED {e}")
                    rows.append({"voice": voice, "variant": label, "error": str(e)})
                    continue
                y, sr = decode(data)
                slug = label.split(" ")[0]
                wav = out / f"{voice}_{slug}.wav"
                wavfile.write(wav, sr, (np.clip(y, -1, 1) * 32767).astype(np.int16))
                mp3 = wav_to_mp3(wav, out / f"{voice}_{slug} - {label[2:].replace('/', '-')}.mp3")
                f = sim.fingerprint(tts.embed, wav)
                wav.unlink(missing_ok=True)
                scores = {k: sim.match(f, r) for k, r in refs.items()}
                rows.append({"voice": voice, "variant": label, "model": model, "format": fmt, **{f"match_{k}": v for k, v in scores.items()},
                             "secs": round(time.time() - t, 1), "file": mp3.name})
                print(f"  {label:40s} " + "  ".join(f"vs {k}: {v}%" for k, v in scores.items()))
    finally:
        for vid in temp_clones:
            el.delete_clone(key, vid)
        used = spent()
        print(f"\ncredits used: {used:,}  (left {el.account(key)['left']:,}); temporary clones deleted: {len(temp_clones)}")
        (out / "results.json").write_text(json.dumps({"text": TEXT, "credits_used": used, "rows": rows}, indent=1), encoding="utf-8")
        lines = ["# Voice match test", "", f"Sentence: “{TEXT}”", "",
                 "Score = how much the take sounds like the person's ORIGINAL recording (speaker-verification encoder; same person ≈ 80–95%, different person ≈ 60–70%).", "",
                 "| Voice | Variant | Match (original) | Other | File |", "|---|---|---|---|---|"]
        for r in rows:
            other = " ".join(f"{k[6:]} {v}%" for k, v in r.items() if k.startswith("match_") and k != "match_original")
            lines.append(f"| {r['voice']} | {r['variant']} | {r.get('match_original', '—')} | {other or r.get('error', '')} | {r.get('file', '')} |")
        lines += ["", f"Credits used: {used:,}"]
        (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"report: {out / 'README.md'}")
        if tts.proc:
            tts.proc.kill()


if __name__ == "__main__":
    main()
