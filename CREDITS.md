# Credits and licences

AnKar Video Editor's own code is MIT (see LICENSE). It includes or downloads these works, each under its own free licence.

## Included in the download
| What | Where | Author | Licence |
|---|---|---|---|
| Poppins, Anton, Archivo Black, Bangers, Bebas Neue, Courier Prime | `library/fonts/` | their designers (see the `OFL-*.txt` files) | SIL Open Font License 1.1 |
| Permanent Marker | `library/fonts/` | Font Diner | Apache 2.0 (`LICENSE-PermanentMarker.txt`) |
| Keyboard Soundpack #1 | `library/sfx/keyboard/unicae/`, `library/ambience/keyboard.mp3` | Unicae Games | CC0 1.0 |
| typing soundeffect | `library/sfx/keyboard/laptop/` | johndekale | CC0 1.0 |
| Single Key Press Sounds | `library/sfx/keyboard/eklee/` | eklee (recording), qubodup (extraction) | **CC BY 3.0 — credit needed** when you use them in a video, e.g. "Keyboard sounds: eklee & qubodup, CC BY 3.0" |
| Preact + htm | `web/vendor/preact-htm.js` | Jason Miller and contributors | MIT |
| LUTs, room reverbs (IRs), room tone, sample clips | `library/luts/`, `library/ir/`, `library/ambience/room_tone.mp3`, `library/samples/` | made by this project's scripts (`scripts/make_*.py`) | CC0 1.0 |

## Downloaded by Setup
| What | From | Licence |
|---|---|---|
| Python 3.12 (embeddable) | python.org | PSF License |
| pip | PyPI | MIT |
| Python packages in `requirements-lock.txt` (FastAPI, Uvicorn, NumPy, SciPy, Pillow, PyAV (bundles FFmpeg; its build includes GPL parts such as x264), moderngl, pyloudnorm, audiotsm, pywhispercpp/whisper.cpp, cryptography, anthropic, yt-dlp, …) | PyPI | each package's own licence (MIT / BSD / Apache 2.0 / LGPL / GPL / Unlicense) — downloaded from PyPI on your PC, not redistributed by AnKar |
| Whisper medium model, ggml q5_0 (`models/ggml-medium-q5_0.bin`) | huggingface.co/ggerganov/whisper.cpp | MIT (OpenAI Whisper weights, ggml conversion by Georgi Gerganov) |

## Optional (Install local AI voice)
| What | Licence |
|---|---|
| Chatterbox TTS (Resemble AI) | MIT |
| Demucs htdemucs (voice isolation, Meta) | MIT |
| PyTorch (CPU) | BSD-3-Clause |

## Not included
Noise beds generated with ElevenLabs Sound Effects stay out of the public download (their licence depends on the
ElevenLabs plan). Generate your own with `scripts/make_ambience.py` and your key, or drop any audio file into
`library/ambience/`.
