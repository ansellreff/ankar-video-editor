"""Match narration to the video: place each sentence in a time range so it doesn't talk over people speaking in the
footage and (optionally) starts on a shot change. Pure function — the server feeds it the context (context.py).

Greedy, in sentence order. Each sentence starts at the earliest free moment after the previous one (+ its natural
pause), where free = not overlapping speech (padded). With shot changes on, a cut up to SNAP s later that is also free
is preferred. If the result runs past the range end, it retries with shorter pauses and slightly faster speech
(≤ 1.12×, the limit before stretching is audible); if it still doesn't fit it reports how much is too long.
"""
from __future__ import annotations

PAD = 0.15              # keep this far away from someone talking in the video
SNAP = 1.0              # wait at most this long for a shot change
CUT_LEAD = 0.05         # start just after the cut
TRIES = [(1.0, 1.0), (1.0, 0.7), (1.06, 0.7), (1.06, 0.45), (1.12, 0.45), (1.12, 0.25)]


def _free(t: float, d: float, busy: list[tuple[float, float]]) -> float:
    """Earliest start >= t where [start, start+d] overlaps no busy interval (busy sorted by start)."""
    moved = True
    while moved:
        moved = False
        for a, b in busy:
            if a < t + d and b > t:
                t, moved = b, True
    return t


def _run(durs, gaps, r0, busy, cuts, speed, gscale):
    starts, t = [], r0
    for i, d0 in enumerate(durs):
        d = d0 / speed
        earliest = t if i == 0 else t + gaps[i - 1] * gscale
        s = _free(earliest, d, busy)
        if cuts:
            for c in cuts:
                c2 = c + CUT_LEAD
                if c2 < s - 1e-6:
                    continue
                if c2 > s + SNAP:
                    break
                if _free(c2, d, busy) == c2:
                    s = c2
                    break
        starts.append(s)
        t = s + d
    return starts, t


def place(segs: list[dict], r0: float, r1: float, speech=(), cuts=(), avoid=True, snap=True, wpm=None) -> dict:
    """segs: [{text, a, b}] (natural sentence spans in the generated file). Returns
    {starts (timeline s), speed, end, fits, over, words, spare, add_words, collisions}."""
    if not segs:
        return {"starts": [], "speed": 1.0, "end": r0, "fits": True, "over": 0.0, "words": 0, "spare": r1 - r0, "add_words": 0}
    durs = [max(0.05, s["b"] - s["a"]) for s in segs]
    gaps = [max(0.0, segs[i + 1]["a"] - segs[i]["b"]) for i in range(len(segs) - 1)]
    busy = sorted((a - PAD, b + PAD) for a, b in speech) if avoid else []
    cut_list = sorted(c for c in cuts if r0 - 1e-6 <= c < r1) if snap else []
    best = None
    for sp, gs in TRIES:
        for cl in ([cut_list, []] if cut_list else [[]]):        # with snapping first, then without (it adds waiting)
            starts, end = _run(durs, gaps, r0, busy, cl, sp, gs)
            cand = (end, sp, gs, starts)
            if best is None or end < best[0] - 1e-6:
                best = cand
            if end <= r1 + 0.02:
                best = cand
                break
        else:
            continue
        break
    end, sp, gs, starts = best
    rate = (wpm or 170) / 60.0
    over = max(0.0, end - r1)
    spare = max(0.0, r1 - end)
    collisions = sum(1 for s, d in zip(starts, durs) for a, b in speech if a < s + d / sp and b > s)
    return {"starts": [round(s, 3) for s in starts], "speed": sp, "gap_scale": gs, "end": round(end, 3),
            "fits": over <= 0.02, "over": round(over, 2), "words": int(round(over * rate + 0.49)) if over > 0.02 else 0,
            "spare": round(spare, 2), "add_words": int(spare * rate * 0.8) if spare > 1.5 else 0, "collisions": collisions}


def snap_target(t: float, cuts) -> float | None:
    """Nearest shot change for a sentence that would start at t (used by the 'Snap to nearest shot change' action)."""
    cs = [c + CUT_LEAD for c in cuts]
    return min(cs, key=lambda c: abs(c - t)) if cs else None


def next_gap(t: float, d: float, speech) -> float:
    """First start >= t where a sentence of length d doesn't talk over anyone ('Move to next gap in the talking')."""
    busy = sorted((a - PAD, b + PAD) for a, b in speech)
    return _free(t, d, busy)
