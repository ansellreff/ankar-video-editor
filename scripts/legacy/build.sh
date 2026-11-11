#!/usr/bin/env bash
# Rebuilds the sample vlog edit (v3) from the raw footage.
# Needs: ffmpeg (with libass), python3 + numpy + scipy, Poppins font in ./fonts
set -euo pipefail
cd "$(dirname "$0")"

CLIP1=footage/20261102_180431_639_1.mp4   # night meet-up (27 s)
CLIP2=footage/20261102_180928_674_1.mp4   # next morning on bikes (16 s)
FD=fonts
W=output/work; mkdir -p "$W"
ENC="-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -r 30000/1001 -c:a aac -b:a 192k -ar 48000 -ac 2"

# 1. Intro: 8 s black, typed date/time synced to Red Switch keyboard sound (variant 2)
python3 scripts/keys.py 2 "$W/intro.wav" "$W/intro.ass"
ffmpeg -v error -y -f lavfi -i "color=black:s=1080x1920:r=30000/1001:d=8" -i "$W/intro.wav" \
  -vf "ass=$W/intro.ass:fontsdir=$FD" $ENC -shortest "$W/intro.mp4"

# 2. Clips with burned-in subtitles + narration captions
ffmpeg -v error -y -i "$CLIP1" -vf "scale=1080:1920,setsar=1,ass=subtitles/clip1.ass:fontsdir=$FD" $ENC "$W/clip1.mp4"
ffmpeg -v error -y -i "$CLIP2" -vf "scale=1080:1920,setsar=1,ass=subtitles/clip2.ass:fontsdir=$FD,fade=t=out:st=15.05:d=1" \
  -af "afade=t=out:st=15.05:d=1" $ENC "$W/clip2.mp4"

# 3. Assemble: fade from intro, then sharp inward wipe (edges -> center) into clip 2
#    xfade offsets: 7.6 = intro(8) - 0.4 ; 33.36 = 8 + 26.56 - 0.4 - 0.8
ffmpeg -v error -y -i "$W/intro.mp4" -i "$W/clip1.mp4" -i "$W/clip2.mp4" -filter_complex "\
[0:v][1:v]xfade=transition=fade:duration=0.4:offset=7.6[v01];\
[v01][2:v]xfade=transition=custom:duration=0.8:offset=33.36:expr='if(gt(abs(X-W/2),P*W/2),B,A)',format=yuv420p[v];\
[0:a][1:a]acrossfade=d=0.4[a01];[a01][2:a]acrossfade=d=0.8[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 192k -movflags +faststart \
  output/Vlog_Sample_Edit_v3.mp4
echo "Done: output/Vlog_Sample_Edit_v3.mp4"
