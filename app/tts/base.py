"""TTS provider interface + tone presets (shared by the local engine and ElevenLabs)."""
from __future__ import annotations

# Chatterbox guidance: exaggeration 0.5 / cfg 0.5 is the most faithful to the reference voice. Higher exaggeration adds
# energy but drifts away from the speaker (sounds less like them), so presets stay close to 0.5. Tone presets do NOT
# time-stretch the audio (stretching adds a metallic, robotic texture); pace only changes when the user moves Pace.
TONES = {
    "neutral":  {"label": "Neutral",  "exaggeration": 0.50, "cfg": 0.50, "pace": 1.0},
    "cheerful": {"label": "Cheerful", "exaggeration": 0.60, "cfg": 0.42, "pace": 1.0},
    "excited":  {"label": "Excited",  "exaggeration": 0.70, "cfg": 0.35, "pace": 1.0},
    "curious":  {"label": "Curious",  "exaggeration": 0.55, "cfg": 0.45, "pace": 1.0},
    "warm":     {"label": "Warm",     "exaggeration": 0.50, "cfg": 0.48, "pace": 1.0},
    "calm":     {"label": "Calm",     "exaggeration": 0.40, "cfg": 0.52, "pace": 1.0},
    "serious":  {"label": "Serious",  "exaggeration": 0.40, "cfg": 0.55, "pace": 1.0},
    "dramatic": {"label": "Dramatic", "exaggeration": 0.68, "cfg": 0.45, "pace": 1.0},
}
MOODS = ["neutral", "cheerful", "excited", "curious", "warm", "calm", "serious", "dramatic"]

PROVIDERS = {
    "local": {"name": "Local (Chatterbox, on this PC)", "license": "MIT · commercial use OK · output carries an inaudible AI watermark"},
    "elevenlabs": {"name": "ElevenLabs (cloud)", "license": "your API key + credits; voice samples are uploaded to ElevenLabs to make the clone"},
}


def resolve(tone: str, intensity: float | None = None, pace: float | None = None) -> dict:
    """Engine parameters for a tone; `intensity` (0–1, 0.5 = preset) nudges emotion gently; `pace` = user speed."""
    p = dict(TONES.get(tone, TONES["neutral"]))
    if intensity is not None:
        p["exaggeration"] = round(min(0.85, max(0.3, p["exaggeration"] + (float(intensity) - 0.5) * 0.3)), 3)
    p["pace"] = round(float(pace), 3) if pace is not None else 1.0
    return p
