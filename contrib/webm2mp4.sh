#!/bin/bash

for file in *.webm; do
  base="${file%.webm}"
  echo "Converting: $file → ${base}.mp4"

  ffmpeg -i "$file" \
    -c:v libx264 -preset slow -crf 18 \
    -c:a aac -b:a 192k \
    "${base}.mp4"
done