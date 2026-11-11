"""Local TTS worker (runs in .venv-tts). JSON lines on stdin → JSON lines on stdout.
{"id": 1, "cmd": "synth", "text": "...", "ref": "path/to/sample.wav" | null, "exaggeration": 0.5, "cfg": 0.5, "out": "x.wav"}
→ {"id": 1, "ok": true, "dur": 3.2, "secs": 9.1}   (model is loaded once, on the first request)"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "tts" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TORCH_HOME", str(ROOT / "models" / "tts" / "torch"))     # Demucs weights stay in the project
_out = sys.stdout
sys.stdout = sys.stderr            # libraries print progress; keep stdout clean for the protocol


def reply(obj):
    _out.write(json.dumps(obj) + "\n")
    _out.flush()


model = None
encoder = None
separator = None


def load_encoder():
    """Chatterbox's speaker encoder alone (5 MB) — voice fingerprints for telling speakers apart."""
    global encoder
    if encoder is None:
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from chatterbox.models.voice_encoder import VoiceEncoder
        enc = VoiceEncoder()
        enc.load_state_dict(load_file(hf_hub_download("ResembleAI/chatterbox", "ve.safetensors")))
        encoder = enc.eval()
    return encoder


def load():
    global model
    if model is None:
        import torch
        from chatterbox.tts import ChatterboxTTS
        torch.set_num_threads(max(2, (os.cpu_count() or 4) - 1))
        model = ChatterboxTTS.from_pretrained(device="cpu")
    return model


def main():
    reply({"ready": True})
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        rid = req.get("id")
        try:
            if req["cmd"] == "ping":
                reply({"id": rid, "ok": True})
                continue
            if req["cmd"] == "load":
                t = time.time(); load()
                reply({"id": rid, "ok": True, "secs": round(time.time() - t, 1)})
                continue
            if req["cmd"] == "isolate":
                # keep only the human voices: Demucs (htdemucs) splits vocals from music / background
                import numpy as np
                import soundfile as sf
                import torch
                import torchaudio.functional as AF
                from demucs.apply import apply_model
                from demucs.pretrained import get_model
                global separator
                if separator is None:
                    separator = get_model("htdemucs").eval()
                m = separator
                x, sr = sf.read(req["in"], dtype="float32", always_2d=True)
                wav = torch.from_numpy(np.ascontiguousarray(x.T))
                if wav.shape[0] == 1:
                    wav = wav.repeat(2, 1)
                if sr != m.samplerate:
                    wav = AF.resample(wav, sr, m.samplerate)
                t = time.time()
                ref = wav.mean(0)
                mu, sd = ref.mean(), ref.std() + 1e-8
                with torch.inference_mode():
                    src = apply_model(m, ((wav - mu) / sd)[None], device="cpu", split=True, overlap=0.25, progress=False)[0]
                vocals = (src[m.sources.index("vocals")] * sd + mu).mean(0).numpy()
                sf.write(req["out"], vocals, m.samplerate, subtype="FLOAT")
                reply({"id": rid, "ok": True, "secs": round(time.time() - t, 1), "sr": m.samplerate})
                continue
            if req["cmd"] == "embed":
                import numpy as np
                import soundfile as sf
                enc = load_encoder()
                x, sr = sf.read(req["wav"], dtype="float32", always_2d=False)
                if x.ndim > 1:
                    x = x.mean(axis=1)
                wavs = []
                for s, e in req["segments"]:
                    w = x[int(s * sr):int(e * sr)]
                    if len(w) < int(1.7 * sr):                      # the encoder needs ~1.6 s: loop short windows
                        w = np.tile(w, int(np.ceil(1.7 * sr / max(len(w), 1))))[: int(1.7 * sr)]
                    wavs.append(w)
                t = time.time()
                emb = enc.embeds_from_wavs(wavs, sr, trim_top_db=None, batch_size=64)
                reply({"id": rid, "ok": True, "embeds": [[round(float(v), 5) for v in row] for row in emb], "secs": round(time.time() - t, 1)})
                continue
            if req["cmd"] == "synth":
                import torchaudio as ta
                m = load()
                t = time.time()
                kw = {"exaggeration": float(req.get("exaggeration", 0.5)), "cfg_weight": float(req.get("cfg", 0.5))}
                if req.get("ref"):
                    kw["audio_prompt_path"] = req["ref"]
                wav = m.generate(req["text"], **kw)
                ta.save(req["out"], wav, m.sr)
                reply({"id": rid, "ok": True, "dur": round(wav.shape[-1] / m.sr, 3), "secs": round(time.time() - t, 1), "sr": m.sr})
                continue
            reply({"id": rid, "ok": False, "error": f"unknown cmd {req['cmd']}"})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            reply({"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
