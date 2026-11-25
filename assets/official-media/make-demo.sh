#!/bin/sh
# Synthesize the public pause-removal fixture from FFmpeg signal generators.
set -eu
out="${1:-$(dirname "$0")/../demo.mp4}"
ffmpeg -nostdin -v error -y \
  -f lavfi -i 'testsrc2=size=360x640:rate=30:duration=9' \
  -f lavfi -i "aevalsrc=0.10*sin(2*PI*440*t)*between(t\,0\,2.5)+0.10*sin(2*PI*523*t)*between(t\,4\,6)+0.10*sin(2*PI*659*t)*between(t\,7\,9):s=48000:d=9" \
  -map 0:v -map 1:a -map_metadata -1 -c:v libx264 -threads 1 -preset fast -crf 27 \
  -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$out"
