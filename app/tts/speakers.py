"""Who speaks when (speaker diarization) — voice fingerprints from Chatterbox's encoder + clustering.

detect(): speech → 1.6 s windows → fingerprints (worker) → agglomerative clustering (cosine) → smoothed speaker turns.
voice_from_speaker(): joins one speaker's clean turns into a voice sample.
"""
from __future__ import annotations

import uuid

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.io import wavfile
from scipy.signal import resample_poly

from ..paths import WORK, rel
from ..render.audio import decode_range
from ..subtitles import utterances

COLORS = ["#4f8cff", "#f5a524", "#3ccf91", "#e0457b", "#9b5de5", "#22c1d6"]
JOBS: dict[str, dict] = {}


def _windows(chunks, sr=16000, win=1.6, hop=0.8):
    out = []
    for a, b in chunks:
        s, e = a / sr, b / sr
        if e - s <= win:
            out.append((s, e))
            continue
        t = s
        while t + win <= e + 1e-6:
            out.append((t, t + win))
            t += hop
        if out[-1][1] < e - 0.3:
            out.append((e - win, e))
    return out


def detect(path, t0, t1, start_offset, embed_fn, n_speakers=None, progress=None, isolate_fn=None):
    """Returns a job dict: {id, speakers:[{id, color, seconds, turns:[[s,e]], previews:[file]}], turns:[[s,e,spk]], dur}.
    Times are relative to t0 (the start of the analysed range). isolate_fn(in_wav, out_wav) removes music/background first."""
    jid = uuid.uuid4().hex[:8]
    d = WORK / "speakers" / jid
    d.mkdir(parents=True, exist_ok=True)
    prog = progress or (lambda v, stage=None: None)
    prog(0.02, "Reading the video's audio")
    x = decode_range(path, t0, t1, start_offset).mean(axis=0).astype(np.float32)
    x_orig = x
    isolated = False
    clean = is_clean(x)
    if isolate_fn and clean:
        prog(0.05, "Recording is already clean — keeping the original sound (no separation needed)")
    if isolate_fn and not clean:
        # voice separation in 30 s chunks (2 s overlap, crossfaded) → real progress and bounded memory
        from math import gcd
        CH, OV = 30 * 48000, 2 * 48000
        starts = list(range(0, max(1, len(x) - OV), CH - OV)) or [0]
        out = np.zeros_like(x)
        weight = np.zeros_like(x)
        for k, a in enumerate(starts):
            prog(0.05 + 0.65 * k / len(starts), f"Removing music & background sound ({k + 1}/{len(starts)})")
            seg = x[a:a + CH]
            raw, voc = d / f"mix_{k}.wav", d / f"voc_{k}.wav"
            wavfile.write(raw, 48000, seg)
            isolate_fn(str(raw), str(voc))
            sr, v = wavfile.read(voc)
            v = v.astype(np.float32)
            if sr != 48000:
                g = gcd(48000, sr)
                v = resample_poly(v, 48000 // g, sr // g).astype(np.float32)
            v = v[:len(seg)]
            w = np.ones(len(v), np.float32)
            ramp = min(OV, len(v) // 2)
            if a > 0:
                w[:ramp] = np.linspace(0, 1, ramp)
            if a + CH < len(x):
                w[-ramp:] = np.minimum(w[-ramp:], np.linspace(1, 0, ramp))
            out[a:a + len(v)] += v * w
            weight[a:a + len(v)] += w
            raw.unlink(missing_ok=True)
            voc.unlink(missing_ok=True)
        x = out / np.maximum(weight, 1e-6)
        isolated = True
    prog(0.72, "Recognising the different voices")
    wavfile.write(d / "audio48k.wav", 48000, x)              # voice-only if isolated
    if isolated:
        wavfile.write(d / "mix48k.wav", 48000, x_orig)       # original sound: used where the background is quiet
    x16 = resample_poly(x, 1, 3).astype(np.float32)
    wav16 = d / "audio16k.wav"
    wavfile.write(wav16, 16000, x16)
    chunks = utterances(x16, max_len=12.0)
    wins = _windows(chunks)
    if len(wins) < 2:
        raise ValueError("not enough speech found in that part of the video")
    prog(0.78, f"Recognising the different voices ({len(wins)} moments of speech)")
    emb = np.array(embed_fn(str(wav16), wins), dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
    prog(0.92, "Grouping speech by person")
    Z = linkage(emb, method="average", metric="cosine")
    if n_speakers:
        labels = fcluster(Z, t=int(n_speakers), criterion="maxclust")
    else:
        labels = fcluster(Z, t=0.32, criterion="distance")      # same-speaker windows sit well inside 0.32
    labels = np.asarray(labels) - 1
    # tiny clusters (<4% of windows) are usually noise/overlap → merge into the nearest real speaker
    counts = np.bincount(labels)
    big = [k for k in range(len(counts)) if counts[k] >= max(2, 0.04 * len(labels))] or [int(np.argmax(counts))]
    cent = {k: emb[labels == k].mean(axis=0) for k in big}
    for i, l in enumerate(labels):
        if l not in cent:
            labels[i] = max(cent, key=lambda k: float(emb[i] @ cent[k]))
    # smooth single-window flips inside an utterance
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] != labels[i] and wins[i - 1][1] >= wins[i][0] and wins[i][1] >= wins[i + 1][0]:
            labels[i] = labels[i - 1]
    # order speakers by talk time and give them stable names
    talk = {k: 0.0 for k in set(labels.tolist())}
    for (s, e), l in zip(wins, labels):
        talk[l] += e - s
    order = sorted(talk, key=lambda k: -talk[k])
    name = {k: f"S{i + 1}" for i, k in enumerate(order)}
    # turns: merge consecutive windows of the same speaker (each second assigned to the window centred nearest)
    turns = []
    for (s, e), l in zip(wins, labels):
        spk = name[l]
        if turns and turns[-1][2] == spk and s <= turns[-1][1] + 0.35:
            turns[-1][1] = max(turns[-1][1], e)
        else:
            if turns and s < turns[-1][1]:                      # overlap between different speakers: split the middle
                mid = (s + turns[-1][1]) / 2
                turns[-1][1], s = mid, mid
            turns.append([s, e, spk])
    speakers = []
    for i, k in enumerate(order):
        spk = name[k]
        mine = [t for t in turns if t[2] == spk]
        previews = []
        for j, (s, e, _) in enumerate(sorted(mine, key=lambda t: -(t[1] - t[0]))[:3]):   # 3 longest turns
            seg = x16[int(s * 16000):int(min(e, s + 6) * 16000)]
            f = d / f"{spk}_{j}.wav"
            wavfile.write(f, 16000, seg)
            previews.append(rel(f))
        speakers.append({"id": spk, "color": COLORS[i % len(COLORS)], "seconds": round(sum(e - s for s, e, _ in mine), 1),
                         "turns": [[round(s, 2), round(e, 2)] for s, e, _ in mine], "previews": previews})
    # per-window data for clean sample extraction (purity filter + per-window background level)
    bg = []
    for s, e in wins:
        a, b = int(s * 48000), int(e * 48000)
        o = x_orig[a:b]
        r = (o - x[a:b]) if isolated else np.zeros(1, np.float32)
        bg.append(20 * np.log10((np.sqrt((r ** 2).mean()) + 1e-9) / (np.sqrt((o ** 2).mean()) + 1e-9)) if isolated else -60.0)
    np.savez(d / "windows.npz", wins=np.array(wins, np.float32), labels=np.array([name[l] for l in labels]), emb=emb,
             bg=np.array(bg, np.float32))
    job = {"id": jid, "speakers": speakers, "turns": [[round(s, 2), round(e, 2), k] for s, e, k in turns],
           "dur": round(len(x16) / 16000, 2), "isolated": isolated, "clean_source": clean,
           "src": {"audio48": str(d / "audio48k.wav"), "mix48": str(d / "mix48k.wav") if isolated else None,
                   "windows": str(d / "windows.npz"), "path": str(path), "t0": t0, "t1": t1}}
    JOBS[jid] = job
    prog(1.0, "Done")
    return job


def is_clean(x: np.ndarray, sr=48000) -> bool:
    """True when a recording has little background (quiet floor between words, no music bed) — vocal separation would
    only add artifacts there. Speech level (loud frames) vs the noise floor (quiet frames) in 30 ms frames."""
    hop = int(sr * 0.03)
    n = len(x) // hop
    if n < 20:
        return False
    db = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    db = db[db > -120]                                         # ignore digital silence (padding, gated gaps)
    if len(db) < 20:
        return False
    floor, speech = np.percentile(db, 10), np.percentile(db, 90)
    # calibrated on the user's phone recordings: floor ≈ −55 dBFS, speech ≈ −28 → clean; music beds lift the floor
    return bool(floor < -48 and speech - floor > 22)


PURE_OWN, PURE_MARGIN, GUARD = 0.70, 0.12, 0.30


def speaker_audio(job_id: str, speaker: str, max_sec=150.0, edge=0.12, source="auto", info=None) -> np.ndarray:
    """One speaker's clean speech as 48 kHz mono (up to max_sec), built for voice cloning:
    - purity filter: only 1.6 s windows that clearly belong to this speaker (close to their fingerprint, far from the
      others) and not within 0.3 s of another speaker's speech (no overlaps / misassigned bits);
    - per segment: the ORIGINAL sound where the background is quiet, separated vocals only where needed
      (source="auto"; or force "original" / "vocals");
    - each segment levelled to −20 LUFS so the clone hears a consistent voice; best (purest) segments first.
    `info` (dict) receives what was used."""
    import pyloudnorm as pyln
    job = JOBS.get(job_id)
    if not job:
        raise ValueError("speaker detection expired — run Find speakers again")
    _, voc = wavfile.read(job["src"]["audio48"])
    voc = voc.astype(np.float32)
    mix = None
    if job["src"].get("mix48"):
        _, mix = wavfile.read(job["src"]["mix48"])
        mix = mix.astype(np.float32)
    W = np.load(job["src"]["windows"]) if job["src"].get("windows") else None
    spk = next(s for s in job["speakers"] if s["id"] == speaker)
    segs = []                                                  # (start, end, purity, bg_db)
    dropped = 0
    if W is not None:
        wins, labels, emb, bgs = W["wins"], W["labels"], W["emb"], W["bg"]
        cents = {k: emb[labels == k].mean(axis=0) for k in set(labels.tolist())}
        cents = {k: v / (np.linalg.norm(v) + 1e-9) for k, v in cents.items()}
        others = [(s, e) for (s, e), l in zip(wins, labels) if l != speaker]
        keep = []
        for (s, e), l, v, b in zip(wins, labels, emb, bgs):
            if l != speaker:
                continue
            own = float(v @ cents[speaker])
            oth = max([float(v @ c) for k, c in cents.items() if k != speaker] or [0.0])
            near_other = any(os_ - GUARD < e and s < oe + GUARD for os_, oe in others)
            if own < PURE_OWN or (len(cents) > 1 and own - oth < PURE_MARGIN) or near_other:
                dropped += 1
                continue
            keep.append((float(s), float(e), own, float(b)))
        for s, e, own, b in sorted(keep):                      # merge touching windows into segments
            if segs and s <= segs[-1][1] + 0.2:
                p = segs[-1]
                segs[-1] = (p[0], max(p[1], e), (p[2] + own) / 2, max(p[3], b))
            else:
                segs.append((s, e, own, b))
    else:                                                      # older jobs: turns as they are
        segs = [(s, e, 0.8, -60.0) for s, e in spk["turns"]]
    segs = [(s + edge, e - edge, p, b) for s, e, p, b in segs if e - s - 2 * edge >= 1.0]
    if not segs:
        raise ValueError("no clean stretch of this speaker's voice (≥1 s, not overlapping others) — try a longer recording")
    meter = pyln.Meter(48000)
    order = sorted(segs, key=lambda t: -(t[2] * min(1.0, (t[1] - t[0]) / 4.0)))     # purest + reasonably long first
    chosen, total, used = [], 0.0, {"original": 0.0, "vocals": 0.0}
    for s, e, p, b in order:
        use_orig = mix is not None and (source == "original" or (source == "auto" and b < -16.0))
        src = mix if use_orig else voc
        if mix is None:
            used_key = "original" if not job.get("isolated") else "vocals"
        else:
            used_key = "original" if use_orig else "vocals"
        y = src[int(s * 48000):int(e * 48000)].astype(np.float64)
        try:
            lv = meter.integrated_loudness(y) if len(y) > 48000 * 0.5 else -70
            if lv > -60:
                y = pyln.normalize.loudness(y, lv, -20.0)
        except Exception:  # noqa: BLE001
            pass
        peak = np.abs(y).max() if len(y) else 0
        if peak > 0.97:
            y *= 0.97 / peak
        chosen.append((s, y.astype(np.float32)))
        used[used_key] += e - s
        total += e - s
        if total >= max_sec:
            break
    chosen.sort(key=lambda t: t[0])                            # back in speaking order
    gap = np.zeros(int(0.25 * 48000), np.float32)
    out = np.concatenate([np.concatenate([y, gap]) for _, y in chosen])
    if info is not None:
        info.update(segments=len(chosen), seconds=round(total, 1), dropped_windows=dropped,
                    source=("original" if used["vocals"] == 0 else "vocals" if used["original"] == 0 else "mixed"))
    return out
