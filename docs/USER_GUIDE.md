# AnKar Video Editor — User guide

How to use the editor. For download and setup see the [README](../README.md).

## Where your files go
Every project is **one folder**: `projects/<project name>/`. A new project starts empty. To back up or archive a project, copy that one folder. Click the 📁 icon in the Project panel to open it.

| Folder (inside the project) | Put here |
|---|---|
| `import/` | **Anything.** It's sorted automatically (see below), so you can always just drop files here. |
| `assets/video/` | Footage. Make one subfolder per day or scene, e.g. `Day 1 - Kaohsiung night`. |
| `assets/photos/` | Photos and stills |
| `assets/brand/logo/` | Brand or sponsor logos: PNG with a transparent background, at least 1000 px wide |
| `assets/brand/watermark/` | Watermark: transparent PNG, usually white or light |
| `assets/audio/music/` | Background music (royalty-free or licensed) |
| `assets/audio/sfx/` | Sound effects (whoosh, pop, click…) |
| `assets/audio/voiceover/` | Voice recordings you made yourself (also usable to train an AI voice) |
| `assets/subtitles/` · `assets/licenses/` | `.srt`/`.ass` files · music and stock licences and credits |
| `docs/script/` · `docs/storyboard/` | Your script (.docx/.pdf/.md/.txt) · storyboard and shot list |
| `exports/` | Finished videos (`v01.mp4`, `v02.mp4`… each restorable), narration MP3s, still frames |

**How `import/` sorts files:** a subfolder or file name containing one of these words decides where it goes:
- `logo` or `brand` → brand/logo, and `watermark` → brand/watermark
- `music`, `bgm` or `song` → music, and `sfx` → sound effects
- `voice`, `vo` or `narration` → voiceover, and `photo` or `pic` → photos
- `script` (or any .docx/.pdf/.md/.txt file) → docs/script, and `storyboard` → docs/storyboard

Anything else goes by type: videos → video (a subfolder like `import/Day 1/` is kept), images → photos, audio → music.

**Shared by all projects** (`library/`): AI voices, fonts, LUTs, noise beds, room reverbs, keyboard sounds and the demo clips. They appear under *Shared library* at the bottom of the Project panel.

Files show up in the **Project** panel by themselves. There's no upload step. The first time a video appears, the app makes a light preview copy (about 1 to 3× the clip's length to prepare).

**Format:** new projects default to **Instagram Reels**: 1080×1920 (9:16), 30 fps, H.264 + AAC. You can change it in Inspector ▸ Sequence or the Sequence menu.

**Watermark / logo:** click an empty spot in the timeline so nothing is selected, then open Inspector ▸ **Watermark / logo**. Pick the image from `brand/` and set the corner, size, opacity and margin. It's drawn on every frame of the preview and the export, and follows your edits automatically. For Reels, keep it out of the bottom 20% of the frame, where Instagram shows captions and buttons. To reuse a logo, "Copy from another project" brings over that project's brand folder.

## Editing
- **Tool ribbon** (under the menus): **Captions · Text · Transitions · Effects · Color · Layouts · Motion · AI Voice**, then **Export** on the right. Each tab opens its tools in the panel next to the monitor.
- **Drag** clips from Project onto the timeline. **Drag** a clip to move it, and drag its edges to trim. Hold **Alt** to ripple-trim, or to move one side of linked audio/video alone.
- **Transitions, effects, looks and text**: click one in the tool panel to apply it to the selection, or drag it onto a clip. The thumbnails show your own footage with that effect.
- **Inspector** (right): position and scale (for split screen), crop, speed, color, filters, volume, fades, and text or caption style.
- **Keyboard**: Space plays. Ctrl+K splits. Del deletes (Shift+Del ripple-deletes). Ctrl+Z undoes. Ctrl+Shift+C opens Auto Captions. Ctrl+M (or Ctrl+E) exports. Help ▸ Keyboard Shortcuts shows the rest.
- **Export**: the Export tab at the right of the ribbon, or File ▸ Export. Every export is kept as a version you can play or restore.
- Every change is saved automatically to `projects/<project>/project.json`.

## New in v3
- **Auto Captions** (Captions tab, or Ctrl+Shift+C). Pick a clip, the whole Dialogue track, or dialogue + narration. Choose a style and how many words per line, then click **Create captions**. Every word is timed. English is written as spoken; Indonesian and Mandarin are translated to English and shown in ( ).
- **16 caption styles**, all original: Karaoke Line (default), Karaoke Pill, Word Pop, Bounce, Big Stack, Boxed Line, Clean Classic, Bold Outline, Neon Glow, Two-Tone, Keyword Highlight, Typewriter, Minimal Lower, Comic Punch, Gradient Fill and Marker Note. The gallery previews are animated. Click a style to restyle the selected captions, or all captions when none are selected.
- **Editable captions.** Select a caption and fix the words in the Inspector. The timing is kept. Wrap a word in `*stars*` to highlight it. You can also change the font, size, colors, word effect, position and words per line, use **Style all like this**, or **★ Save as preset** to reuse a look.
- **"Needs checking" list.** Words Whisper wasn't sure about, lines that may be misheard (mumbling or noise), and speech with no words recognised are listed at the top of the Captions tab. The timeline marks them with an orange **?** or a red marker. Click ▶ to listen, fix the text, then click ✓.
- **Color tab.** 10 one-click **look presets** (Cinematic Teal, Vintage Vlog, Bright Travel, Night Market Neon, Soft Pastel, Moody Rain, Golden Sunset, Clean Natural, B&W Film, Retro VHS). They apply to the selected clips, or to every clip on V1 when nothing is selected. There are also **12 LUTs**, and you can drop your own `.cube` files into `library/luts/`. Set the LUT strength in the Inspector. **★ Save look** (Inspector ▸ Color) keeps a clip's whole grade under *My looks*.
- **15 new effects**: Glow, Light Leak, Letterbox, VHS, Old Film, Duotone, Posterize, Halftone, Color Pop, Sketch, Lens Fisheye, Mirror/Kaleidoscope, Tilt-Shift, Camera Shake and Zoom Pulse.
- **15 new transitions**: Zoom Out, Spin, Squeeze, Cube Rotate, Shake Cut, Cross Warp, Light Leak Flash, Diamond Wipe, Grid Wipe, Split Doors, Swirl, Ripple, Pixelize, Film Burn and RGB Split Dissolve. Hover a transition to see it play.
- **Transition packs** (Smooth, Energetic, Cinematic, Glitchy, Clean Cuts). **Apply** puts varied transitions from the pack on every cut: between the selected clips, or along the whole V1 track.

## New in v2
- **Position things in the monitor.** Click a video or text in the Program monitor to select it. Then drag to move it, use the corners to scale, the top knob to rotate (hold Shift for 15° steps) and the square edge handles to crop. Ctrl+arrows nudge it by 1 px. The zoom buttons (Fit / 25 / 50 / 100%) help with precise placement.
- **Projects.** File ▸ New / Open / Save As / Rename. Ctrl+S saves a named checkpoint you can revert to. Each project has its own folder with its assets and exports.
- **Time.** Ctrl+R opens Speed/Duration (slow motion, fast forward, reverse, keep voice pitch, smooth slow-mo). Shift+F inserts a 2 s freeze frame. The R tool stretches a clip's edge to change its speed so it fits.
- **Keyframes.** The ◆ next to Position, Scale, Rotation, Opacity, Crop and Volume animates that property. The Effects ▸ Motion tab has ready-made presets (Ken Burns, zoom punch, slide in, pop, fade).
- **Layouts.** Effects ▸ Layouts gives a left/right or top/bottom split screen and picture-in-picture.
- **Subtitles in English.** (Now done with Auto Captions, see v3.) English is written as spoken; Indonesian and Mandarin are translated and shown in ( ). Edit the name glossary (Captions tab) so places are spelled right.
- **Voiceover.** Use the mic button in the monitor (with a 3-2-1 countdown).
- **AI narration.** In Effects ▸ AI Voice, create a voice with the consent checkbox. Add samples by right-clicking a clip with that person talking ▸ “Use as voice sample…” (set In/Out to pick one sentence), and tag each sample with a mood. Then add Narration at the playhead, type the text, and pick a tone (Cheerful, Serious, Curious…), the emotion and the pace. Press Generate. With “Fit” on, the voice is timed to the clip's length. Generation takes about 30–60 s per line on this PC, and the result carries an inaudible AI watermark.

## Voice from Video (clone a voice from a video, then narrate your text)
Open the **AI Voice** tab in the ribbon and click **Voice from Video** (or use Audio ▸ Voice from Video). The window walks you through 4 steps:
1. **Upload video:** click (or drag your video in). It's copied into this project's `assets/video/`.
2. **Extract voices:** the AI removes music and background sound, finds each person talking (Person 1, Person 2…), and lets you listen to each one. Pick the person you want.
3. **Learn voice:** name it and tick the permission box. The AI learns that voice from up to 60 s of their speech.
4. **Narrate:** type your text, pick a tone (Cheerful, Curious, Serious…), and click **Generate narration**. Then **Download MP3**, or **Add to timeline at playhead**.

Generation takes about 20–60 s per line on this PC (or a few seconds with ElevenLabs). For the best clone, use a video where the person talks clearly for at least 10–20 seconds in total.

**Pace.** AI voices tend to rush some sentences and drag others. With **Steady pace** on (the default), the narration is spoken sentence by sentence and then evened out to one speed with consistent pauses. Set the **Speed** to Auto (the voice's own pace), Slow, Relaxed, Natural, Brisk or Fast, or pick an exact words-per-minute. Set **Pauses** from short to long. In the text, `[pause]` or `[pause 1.5]` adds a pause, `...` adds a short hesitation, and a new line adds a longer break. Changing speed or pauses later doesn't re-generate the voice; it's re-timed instantly. **New take** gives a fresh performance of the same text. The Inspector shows the speed you actually got (for example "≈180 words/min").

**Voice match.** After each line the app shows how much it sounds like the person: 84% or more sounds like them; a different person scores about 60–70%. If it's low, rebuild the voice (voice card ⋯ ▸ **Rebuild from a recording…**) from the **original** recording. "Enhanced" or AI-cleaned versions change the voice, and the clone copies that. Recordings that are already clean are used as they are, without vocal separation.

**Voice effects** (Inspector ▸ Voice effects on any audio clip, and in Try it): like ElevenLabs' audio effects.
- **Filter:** phone call, old radio, walkie-talkie, megaphone, lo-fi, TV speaker, vintage mic, through a wall, underwater or robot, with a strength control.
- **Noise:** a background bed (café, city street, night market, theme park, light rain, park & birds, wind, train station, room tone, keyboard typing) with a level control. Drop your own ambience files into `library/ambience/`.
- **Space:** a room, from a small room or car up to a church or stadium, with an amount control.
- **Distance:** Near, Medium or Far from the microphone.
- **Pan:** left or right.

Effects are non-destructive, sound the same in the preview and the export, and are included in narration MP3 downloads.

**Voice from the timeline vs. clip speed:** set the pace here, not with the clip's Speed on the timeline. Clip speed stretches everything evenly, so uneven rhythm stays uneven.

## Fixing narration timing
After a narration is generated, each sentence shows as its own block inside the narration clip on the timeline. None of this regenerates the voice or uses ElevenLabs credits, and Ctrl+Z undoes every step.
- **Drag a sentence** left or right to move it. **Shift+drag** moves it together with every sentence after it. Blocks snap to shot changes and the playhead.
- **Nudge:** click a sentence, then press ←/→ to move it 0.1 s, or Shift+←/→ to move it one frame.
- **Right-click a sentence** for: Play this sentence, Snap to nearest shot change, Move to next gap in the talking, Move to playhead, Speed 0.9× / 1× / 1.1×, Reset.
- **Red tint:** a sentence turns red when it talks over someone in the video. The striped band with a red top line on the Narration track marks where people talk.
- **Exact times:** Inspector ▸ **Sentence timing** lists every sentence; type a start time or pick a speed.

**Match to video** (Inspector ▸ Sentence timing, right-click the narration clip, or the AI Voice tab) places all the sentences at once:
- **Fit into:** the video clip(s) under the narration, In → Out, until the next clip, or the current length.
- **Don't talk over people in the video:** sentences go in the gaps. Talking is detected from the sound, or from the words when the clip has Auto Captions, which is more precise.
- **Start sentences on shot changes:** each sentence waits up to 1 s for the next cut.
- It shows a preview and either "Fits" or "1.8 s too long ≈ 5 words". If it doesn't fit, click **Ask Claude to shorten** and paste the request to Claude. Claude rewrites only the sentences that need it, so only those cost credits. When there's spare time, you can ask for more words the same way.

Narration created before this feature has no sentence blocks yet. Press **Regenerate** once. It reuses the saved sentences, so it normally costs no credits; only a voice setting changed since then makes ElevenLabs speak again. If "Also show as on-screen caption" is on, the caption follows the sentences word by word.

## ElevenLabs (optional)
In Effects ▸ AI Voice ▸ **Voice engine**, choose **ElevenLabs**. Add your ElevenLabs key on the **API Keys** page (menu bar ▸ API Keys; your own password protects it). **Check credits** shows how many characters you have left. Switch back to **Local** at any time (needs the optional offline voice engine), for example when your credits run out. With the fallback option ticked, a line that fails on ElevenLabs is made with the local voice automatically.

**Voice settings** (ElevenLabs only): **Auto** follows each line's tone. **Steady** gives the most consistent narrator, **Balanced** a little variation, **Expressive** more emotion but less predictability. Or set the sliders yourself:
- **Stability:** higher means steadier and more alike from line to line; lower adds emotion but each take can differ.
- **Similarity:** how closely to copy the cloned voice. Very high can also copy noise from the samples.
- **Style:** exaggeration. Keep it near 0% for steady narration.
- **Speaker boost:** stays closer to the original speaker.


Your keys are encrypted on this PC (`config/`, never uploaded anywhere) and are only changed on the API Keys page with your password. The app never shows a full key again. You can also set the `ELEVENLABS_API_KEY` / `ANTHROPIC_API_KEY` environment variables instead.

## Demo project
File ▸ Open Project ▸ **Demo** is a 1-minute tour of the features, built from the three synthetic sample clips. Each section is labelled on screen and on the ruler.

## AI Editor (built-in Claude chat)
The **AI Editor** tab is a Claude chat that edits your video with you, using your own Anthropic API key (API Keys page). It agrees the script, editing style, duration and plan with you first, and nothing in your video changes until you press **Approve**. It only does video editing.

## Notes
- `library/samples/` holds three synthetic test clips used by the demo projects.
- One keyboard-sound option (Mac keys) needs a credit line. See `library/sfx/keyboard/CREDITS.md`.
- Caption fonts in `library/fonts/` are free fonts (SIL Open Font License, and Apache 2.0 for Permanent Marker). Their license files are next to them. The built-in LUTs come from `scripts/make_luts.py` and are free to use (CC0).
