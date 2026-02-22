#!/usr/bin/env bash

# Script to extract audio from media files using ffmpeg and save as .wav
# Formats handled: .mkv, .webm, .mp4, .mov, .mp3, .m4a, .flac, .wav
# Output format: .wav (suitable for WhisperX)

set -e

# Define supported input formats
EXTENSIONS=("mkv" "webm" "mp4" "mov" "mp3" "m4a" "flac" "wav")

# Loop over each file in current directory
for ext in "${EXTENSIONS[@]}"; do
  for f in *."$ext"; do
    [ -e "$f" ] || continue  # Skip if no file matches
    filename_noext="${f%.*}"
    output="${filename_noext}.wav"

    # Skip if output already exists
    if [[ -f "$output" ]]; then
      echo "✅ $output already exists, skipping."
      continue
    fi

    echo "🎧 Extracting audio from $f to $output"
    ffmpeg -i "$f" -vn -acodec pcm_s16le -ar 16000 -ac 1 "$output"
  done
done

echo "✅ Done extracting audio."
