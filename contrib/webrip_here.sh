#!/bin/bash

# Loop over video files
for file in *.mp4 *.mkv *.mov *.webm; do
  # Skip if no matching files found
  [ -e "$file" ] || continue
  
  # Extract filename without extension and extension
  filename=$(basename "$file")
  name="${filename%.*}"
  ext="${filename##*.}"
  
  echo "Processing $filename..."

  # Output filename with appended info
  output="${name}_720p_1500k.${ext}"

  ffmpeg -i "$file" -vf "scale=1280:-2" -c:v libx264 -preset slow -crf 23 -c:a aac -b:a 128k "$output"
  
  echo "Done with $filename -> $output"
done

echo "All files processed."
