"""Build a clean, labelled "Feature Demo" project (9:16) through the running server, one section per feature.
Usage (server running): .venv\\Scripts\\python.exe scripts\\build_demo.py ["Project name"]   (VLOG_URL=http://localhost:8766 for the test server)"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("VLOG_URL", "http://localhost:8765")
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
NAME = ARGS[0] if ARGS else "Feature Demo"
NO_INTRO = "--no-intro" in sys.argv          # the public Demo project: only the shipped sample clips, no generated intro sound
FPS = 30000 / 1001


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path}: {e.code} {e.read().decode()[:300]}")


def q(t):
    return round(round(t * FPS) / FPS, 6)


def op(_op, _label=None, **args):
    return call("/api/op", {"op": _op, "args": args, "label": _label})["result"]


st = call("/api/state")
WAS_OPEN = st["project_name"]                       # reopened at the end so the user's editor stays where it was
assets = {a["name"]: a["id"] for a in st["assets"]}
A, B, C = (assets[f"sample_{n}.mp4"] for n in ("A_street_night", "B_bikes_morning", "C_theme_park"))

# fresh project
if any(p["name"] == NAME for p in st["projects"]):
    if st["project_name"] == NAME:
        call("/api/projects/open", {"name": "vlog"})
    call("/api/projects/delete", {"name": NAME})
call("/api/projects/new", {"name": NAME, "format": "9:16"})

LABEL = {"style": {"font": "Poppins", "weight": 600, "size": 44, "outline": 0, "box": True, "box_color": "#000000A6", "align": "left"},
         "anim": {"in": "fade", "in_dur": 0.25, "out": "fade", "out_dur": 0.25}, "x": 0.06, "y": 0.075, "preset": "caption"}
sections = []


def section(start, end, title):
    sections.append((start, end, title))
    op("add_text", track="T2", start=start + 0.15, dur=end - start - 0.3, content=title, **LABEL)
    op("add_marker", t=start, label=title)


# 1. typed intro (your v3 intro) ------------------------------------------------------------------
if not NO_INTRO:
    call("/api/generate/typed_intro", {"start": 0})
    op("add_marker", t=0, label="1 Typed intro")

# 2. clip A + cross dissolve in + Night Boost look -------------------------------------------------
t = q(0.0 if NO_INTRO else 8.0)
a1 = op("add_media", asset=A, track="V1", start=t)[0]
op("update", ids=[a1], patch={"filters": [{"type": "night_boost", "amount": 0.7}]})
op("add_transition", type="cross_dissolve", b=a1, dur=0.5)
section(t, t + 6.006, "2  Look: Night Boost + dissolve in")

# 3. inward wipe → clip B (Warm look) -------------------------------------------------------------
t = q(t + 6.006)
b1 = op("add_media", asset=B, track="V1", start=t)[0]
op("update", ids=[b1], patch={"filters": [{"type": "warm_sun", "amount": 0.8}]})
op("add_transition", type="inward_wipe", a=a1, b=b1, dur=0.8)
section(t, t + 3.0, "3  Inward wipe + Warm look")

# 4. freeze frame: 2 s hold inserted in the middle of B --------------------------------------------
fz = op("freeze_frame", t=q(t + 3.0), id=b1, dur=2.0, mode="insert")[0]
section(q(t + 3.0), q(t + 5.0), "4  Freeze frame (2 s hold)")
t = q(t + 5.0)
rest_end = q(t + 3.006)
section(t, rest_end, "   …clip continues after the hold")

# 5. clip C with a Ken Burns zoom (keyframes) -------------------------------------------------------
t = rest_end
c1 = op("add_media", asset=C, track="V1", start=t)[0]
op("apply_anim_preset", ids=[c1], name="ken_burns_in")
op("add_transition", type="push_left", track="V1", t=t, dur=0.5)
section(t, t + 5.005, "5  Keyframes: Ken Burns zoom + push")

# 6. split screen: A left (V1) + B right (V2) --------------------------------------------------------
t = q(t + 5.005)
s1 = op("add_media", asset=A, track="V1", start=t, in_=0, out=6.006)[0]
s2 = op("add_media", asset=B, track="V2", start=t, in_=0, out=6.006, link_audio=False)[0]
s1v = s1
st = call("/api/state")
W, H = st["project"]["format"]["w"], st["project"]["format"]["h"]
op("update", ids=[s1v], patch={"motion": {"fit": "fill", "x": -W / 4, "y": 0, "scale": 1}, "crop": {"l": 0.25, "r": 0.25, "t": 0, "b": 0}})
op("update", ids=[s2], patch={"motion": {"fit": "fill", "x": W / 4, "y": 0, "scale": 1}, "crop": {"l": 0.25, "r": 0.25, "t": 0, "b": 0}})
section(t, t + 6.006, "6  Split screen (V1 left, V2 right)")

# 7. slow motion 50% ------------------------------------------------------------------------------------
t = q(t + 6.006)
sm = op("add_media", asset=C, track="V1", start=t, in_=0, out=3.003)[0]
op("set_speed", ids=[sm], speed=0.5)
section(t, t + 6.006, "7  Slow motion 50%")

# 8. reverse ----------------------------------------------------------------------------------------------
t = q(t + 6.006)
rv = op("add_media", asset=A, track="V1", start=t, in_=0, out=4.004)[0]
op("set_speed", ids=[rv], speed=1.0, reverse=True)
section(t, t + 4.004, "8  Reverse (timecode counts down)")

# 9. picture-in-picture: B full + C small top-right ------------------------------------------------------
t = q(t + 4.004)
p1 = op("add_media", asset=B, track="V1", start=t, in_=0, out=5.005)[0]
p2 = op("add_media", asset=C, track="V2", start=t, in_=0, out=5.005, link_audio=False)[0]
s, m = 0.38, 0.045
op("update", ids=[p2], patch={"motion": {"fit": "fit", "scale": s, "x": W / 2 - W * s / 2 - W * m, "y": -(H / 2 - H * s / 2 - H * m)}})
op("apply_anim_preset", ids=[p2], name="pop_in")
section(t, t + 5.005, "9  Picture-in-picture (pop in)")

# 10. text styles over the PiP: lower third ---------------------------------------------------------------
pres = {p["id"]: p for p in st["presets"]["text_presets"]}
lt = pres["lower_third"]["defaults"]
op("add_text", track="T1", start=q(t + 1.0), dur=3.5, content=lt["content"], preset="lower_third", x=lt["x"], y=lt["y"], style=lt["style"], anim=lt["anim"])

def words(text, start, end):
    """Evenly timed caption words (stand-in for Whisper timing in the demo)."""
    ws = text.split()
    step = (end - start) / len(ws)
    return [{"w": w, "t0": round(i * step, 3), "t1": round((i + 1) * step, 3)} for i, w in enumerate(ws)]


# 10. v3: look preset (LUT + filters in one click), light leak flash in --------------------------------------
t = q(t + 5.005)
l1 = op("add_media", asset=A, track="V1", start=t, in_=0, out=4.004)[0]
op("apply_look", ids=[l1], look="cinematic_teal")
op("add_transition", type="light_leak_flash", track="V1", t=t, dur=0.8)
section(t, t + 4.004, "10 Look preset: Cinematic Teal (LUT)")

# 11. v3: auto-caption style — Karaoke Line (default) ---------------------------------------------------------
t = q(t + 4.004)
k1 = op("add_media", asset=B, track="V1", start=t, in_=0, out=5.005)[0]
op("apply_look", ids=[k1], look="bright_travel")
op("add_captions", captions_=[{"start": t + 0.5, "end": t + 2.6, "words": words("We are going to", 0, 2.0)},
                              {"start": t + 2.6, "end": t + 4.8, "words": words("E-DA Theme Park today!", 0, 2.1)}],
   template="karaoke_line")
section(t, t + 5.005, "11 Captions: Karaoke Line")

# 12. v3: new effects joined by the Energetic transition pack -----------------------------------------------------
t = q(t + 5.005)
fx_ids = []
for i, (asset, fx) in enumerate(((C, {"type": "vhs", "amount": 0.8}), (A, {"type": "duotone", "amount": 1, "hue": 0.72}),
                                 (B, {"type": "camera_shake", "amount": 0.6, "speed": 1}))):
    cid = op("add_media", asset=asset, track="V1", start=q(t + i * 2.5), in_=0, out=2.5, link_audio=False)[0]
    op("update", ids=[cid], patch={"filters": [fx]})
    fx_ids.append(cid)
op("apply_transition_pack", ids=fx_ids, pack="energetic")
section(t, q(t + 7.5), "12 Effects + Energetic transitions")

# 13. v3: Big Stack captions, cube rotate in ------------------------------------------------------------------------
t = q(t + 7.5)
b2 = op("add_media", asset=C, track="V1", start=t, in_=0, out=4.004, link_audio=False)[0]
op("add_transition", type="cube_rotate", a=fx_ids[-1], b=b2, dur=0.7)
op("add_captions", captions_=[{"start": t + 0.4, "end": t + 3.8, "words": words("Having fun in Taiwan!", 0, 2.8)}], template="big_stack")
op("add_transition", type="dip_black", a=b2, dur=1.0)                     # fade out at the very end
section(t, t + 4.004, "13 Captions: Big Stack + Cube Rotate")

# quieter test tones (the sample clips beep)
for tid in ("A1",):
    op("set_track", id=tid, patch={"volume_db": -14})

st = call("/api/state")
print(f"Feature Demo: {len(st['project']['clips'])} clips, {len(st['project']['transitions'])} transitions, "
      f"{len(st['project']['markers'])} markers, {max(c['start'] + (c.get('dur') or (c['out'] - c['in']) / c['speed']) for c in st['project']['clips']):.1f} s")
for s0, s1_, title in sections:
    print(f"  {s0:6.2f}–{s1_:6.2f}  {title}")
if "--stay" not in sys.argv and WAS_OPEN != NAME and any(p["name"] == WAS_OPEN for p in call("/api/projects")["projects"]):
    call("/api/projects/open", {"name": WAS_OPEN})
    print(f"(reopened '{WAS_OPEN}'; open '{NAME}' from File ▸ Open Project)")
