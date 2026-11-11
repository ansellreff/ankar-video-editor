"""TTS spike: load Chatterbox on CPU, synthesize one line (default voice), then clone from that output; report speed.
Run with: .venv-tts\\Scripts\\python.exe -m app.tts.spike_chatterbox"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "tts" / "hf"))   # keep downloads inside the project
OUT = ROOT / "cache" / "work" / "tts_spike"
OUT.mkdir(parents=True, exist_ok=True)

t = time.time()
import torch  # noqa: E402
import torchaudio as ta  # noqa: E402
print(f"torch {torch.__version__} loaded in {time.time() - t:.1f}s, threads={torch.get_num_threads()}", flush=True)
from chatterbox.tts import ChatterboxTTS  # noqa: E402

t = time.time()
model = ChatterboxTTS.from_pretrained(device="cpu")
print(f"model loaded in {time.time() - t:.1f}s (sr={model.sr})", flush=True)

line = "After a challenging week as engineers in Taiwan, we are finally heading to E-DA Theme Park!"
for name, kw in [("default", {}), ("cheerful", {"exaggeration": 0.8, "cfg_weight": 0.35})]:
    t = time.time()
    wav = model.generate(line, **kw)
    dt = time.time() - t
    dur = wav.shape[-1] / model.sr
    ta.save(str(OUT / f"{name}.wav"), wav, model.sr)
    print(f"{name}: {dur:.1f}s of speech in {dt:.1f}s  → {dt / dur:.2f}x real time", flush=True)

t = time.time()
wav = model.generate("This is a cloned voice test, speaking calmly and clearly.", audio_prompt_path=str(OUT / "default.wav"),
                     exaggeration=0.4, cfg_weight=0.5)
dt = time.time() - t
ta.save(str(OUT / "clone.wav"), wav, model.sr)
print(f"clone: {wav.shape[-1] / model.sr:.1f}s in {dt:.1f}s → {dt / (wav.shape[-1] / model.sr):.2f}x real time", flush=True)
print("SPIKE OK", flush=True)
sys.exit(0)
