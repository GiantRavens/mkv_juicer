#!/usr/bin/env bash
# movie_renamer.sh — normalize movie filenames to "Title (Year).ext"
# Strips codec/resolution noise, applies title case with small-word exceptions.
# Run from a directory containing video/subtitle files.
# Add --dry-run to preview without renaming.

set -euo pipefail

shopt -s nullglob

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "🔍 Dry-run mode — no files will be renamed."
fi

for file in *.{mp4,mkv,avi,srt}; do
  [ -e "$file" ] || continue

  filename=$(basename -- "$file")
  ext="${filename##*.}"
  name="${filename%.*}"

  # Step 1: Normalize — replace punctuation/separators with spaces
  clean=$(echo "$name" | sed -E 's/[\[\]\(\)\._\-]/ /g' | tr -s ' ')

  # Step 2: Strip codec/source/quality noise words
  clean=$(echo "$clean" \
    | sed -E 's/\b(480|720|1080|2160)[pP]\b//g' \
    | sed -E 's/\b4K\b//Ig' \
    | sed -E 's/\b(x264|x265|HEVC|AVC|H\.264|H\.265|WEBRip|WEB-DL|BluRay|BRRip|DVDRip|AAC|AC3|DD5\.1|5\.1|10bit|HDR|SDR|Tigole|YTS|YIFY|RARBG|NTb|AMZN|DSNP)\b//Ig')

  # Step 3: Collapse spaces
  clean=$(echo "$clean" | tr -s ' ' | sed -E 's/^[[:space:]]+|[[:space:]]+$//')

  # Step 4: Extract year
  year=$(echo "$clean" | grep -oE '\b(19[0-9]{2}|20[0-2][0-9])\b' | head -n 1)
  if [ -z "$year" ]; then
    echo "⚠️  Skipping '$file' — no year found"
    continue
  fi

  # Step 5: Title is everything before the year
  title=$(echo "$clean" | sed -E "s/[[:space:]]*\b${year}\b.*//")
  title=$(echo "$title" | sed -E 's/[[:punct:]]//g' | tr -s ' ' | sed -E 's/^[[:space:]]+|[[:space:]]+$//')

  # Step 6: Title case with small-word exceptions
  lower_words="a an and as at but by for if in nor of on or so the to up yet"
  title_cased=$(echo "$title" | awk -v lw="$lower_words" '{
    split(lw, lowers, " ")
    for (i = 1; i <= NF; ++i) {
      word = tolower($i)
      cap = toupper(substr(word,1,1)) substr(word,2)
      for (j in lowers) if (word == lowers[j] && i > 1) cap = word
      $i = cap
    }
    print
  }')

  newname="${title_cased} (${year}).${ext}"

  if [[ "$filename" == "$newname" ]]; then
    echo "✅ Already clean: $filename"
    continue
  fi

  echo "✏️  $filename → $newname"
  if [ "$DRY_RUN" = false ]; then
    mv -n "$file" "$newname"
  fi
done
