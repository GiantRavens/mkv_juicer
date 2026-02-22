#!/usr/bin/env bash
# wmv2mp4.sh — convert WMV files to MP4 using ffmpeg
# Run from a directory containing .wmv files.
# Requires: ffmpeg

set -euo pipefail

shopt -s nullglob

for FILENAME in *.wmv; do
  OUTPUT="${FILENAME%.wmv}.mp4"
  echo "🎬 Converting: $FILENAME → $OUTPUT"
  ffmpeg -i "$FILENAME" -crf 18 -movflags +faststart -pix_fmt yuv420p "$OUTPUT"
  echo "✅ Done: $OUTPUT"
done
