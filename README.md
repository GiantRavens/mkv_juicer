# MKV Juicer

Extract components from MKV files. By default it performs a pure demux (lossless 1:1 copies with native extensions). Optionally, generate editor-friendly derivatives with `--make-editable`.

## Features

- Pure demux (default): video, audio, subtitles, attachments, chapters, and tags
- Optional `--make-editable` derivatives:
  - Video rewraps to editor containers (e.g., H.264/HEVC -> MP4, ProRes -> MOV)
  - Audio reference in selectable format: AAC (default), WAV, or FLAC
  - Subtitles normalized to SRT (text) and OCR of PGS/SUP to SRT + TXT
- Writes a manifest.yaml summarizing outputs and container metadata

## Requirements

- Always required (must be on PATH)
  - mkvmerge, mkvextract (MKVToolNix)
  - exiftool
- Additionally required for `--make-editable`
  - ffmpeg, ffprobe
  - Subtitle Edit CLI (seconv), exposed as `SubtitleEdit.CLI` (used to OCR PGS/SUP to SRT)
- Python packages
  - PyYAML

Install Python deps:

```bash
pip install pyyaml
```

Install system tools via your package manager (names vary by distro):

```bash
# Examples (adjust to your OS)
sudo apt-get install mkvtoolnix exiftool ffmpeg
```

### Subtitle Edit CLI quickstart (Linux/macOS)

```bash
# Install .NET SDK user-local
curl -fsSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
chmod +x dotnet-install.sh
./dotnet-install.sh --channel 8.0
export PATH="$PATH:$HOME/.dotnet:$HOME/.dotnet/tools"

# Build Subtitle Edit CLI from source (example path)
git clone https://github.com/SubtitleEdit/subtitleedit-cli
cd subtitleedit-cli
dotnet publish -c Release -r linux-x64 -p:PublishSingleFile=true -o "$HOME/.local/bin/subtitleedit-cli"
ln -sf "$HOME/.local/bin/subtitleedit-cli/seconv" "$HOME/.dotnet/tools/SubtitleEdit.CLI"
```

Verify:

```bash
SubtitleEdit.CLI --help | head -n 10
```

## Usage

```bash
python mkv_juicer.py <PATH> [options]
```

- `<PATH>` can be a single .mkv file or a directory (recursively scans for .mkv).
- Outputs are written to a per-file folder named after the MKV stem.

### Batch SUP conversion (optional standalone tool)

Use `convert_sup.py` if you want to OCR extracted `.sup` files in bulk:

```bash
# Glob multiple .sup files
python convert_sup.py /path/to/folder/*.sup

# Or pass a directory to scan for *.sup (non-recursive)
python convert_sup.py /path/to/folder

# If SubtitleEdit.CLI is not on PATH, point to it explicitly
python convert_sup.py /path/to/folder/*.sup --se-path $HOME/.dotnet/tools/SubtitleEdit.CLI
```

## Options

- `--audio-only`
  - Only process audio tracks.
- `--subtitles-only`
  - Only process subtitle tracks.
- `--output-dir PATH`
  - Base directory for outputs. Each MKV gets `PATH/<mkv_stem>/`.
  - If omitted, outputs go next to the source MKV (`<source_dir>/<mkv_stem>/`).
- `--make-editable`
  - Generate editor-friendly derivatives (video rewraps, audio references, subtitle conversions/OCR) alongside originals.
- `--editable-audio-format {aac|wav|flac}`
  - Choose the format for the audio reference when using `--make-editable`. Default: `wav`.
  - When the source is AC3 and you use `--make-editable`, a WAV reference is created; the original `.ac3` is kept.
- `--se-path PATH`
  - Optional path to `SubtitleEdit.CLI` if it is not on PATH.

Notes:
- `--audio-only` and `--subtitles-only` cannot be combined.
- Editor-friendly outputs are only created with `--make-editable`.

Audio notes:
- Default audio reference is WAV (fast, lossless, multi‑channel preserved).
- When the source is AC3 and you use `--make-editable`, a WAV reference is created; the original `.ac3` is kept.
- FFmpeg progress is streamed during audio reference creation (look for a `audio wav: 00:..` line).

Tip: Add `SubtitleEdit.CLI` to PATH once to simplify commands:

```bash
export PATH="$PATH:$HOME/.dotnet:$HOME/.dotnet/tools"
```

## Output structure

```
<output_root>/
  <mkv_stem>/
    manifest.yaml              # Summary of extracted tracks and paths
    track_<id>_video.<ext>     # Raw demuxed video
    track_<id>_audio.<ext>     # Raw demuxed audio
    track_<id>_subtitles.<ext> # Raw subtitles
    chapters.txt               # When chapters exist
    tags.xml                   # When tags exist
    <attachments>              # Any extracted attachments
    # Only with --make-editable:
    track_<id>_video.mp4|mov   # Editor-friendly container (when possible)
    track_<id>_audio.(aac|wav|flac) # Audio reference
    track_<id>_subtitles.srt   # Converted text subtitles
    track_<id>_subtitles.txt   # Plain text transcript (for OCR)
```

## Examples

- Process a single MKV (pure demux next to source):
  ```bash
  python mkv_juicer.py /media/video/movie.mkv
  ```

- Process a single MKV into the current directory (pure demux):
  ```bash
  python mkv_juicer.py /media/video/movie.mkv --output-dir .
  ```

- Process a folder of MKVs into a separate output root (pure demux):
  ```bash
  python mkv_juicer.py /media/video/archive --output-dir /tmp/juiced
  ```

- Make editor-friendly outputs alongside originals:
  ```bash
  python mkv_juicer.py /media/video/movie.mkv --make-editable
  ```

- Make editor-friendly outputs with WAV audio proxies:
  ```bash
  python mkv_juicer.py /media/video/movie.mkv --make-editable --editable-audio-format wav
  ```

- Only extract subtitles:
  ```bash
  python mkv_juicer.py /media/video/movie.mkv --subtitles-only
  ```

- Only extract audio:
  ```bash
  python mkv_juicer.py /media/video/movie.mkv --audio-only
  ```

## Troubleshooting

- Command not found: ensure required system tools are installed and on PATH.
- SubtitleEdit.CLI not found: verify your symlink or provide `--se-path`. You can also add the default locations to PATH:

  ```bash
  export PATH="$PATH:$HOME/.dotnet:$HOME/.dotnet/tools"
  ```

  Persist for zsh:

  ```bash
  echo 'export PATH="$PATH:$HOME/.dotnet:$HOME/.dotnet/tools"' >> ~/.zshrc && source ~/.zshrc
  ```

  Persist for bash:

  ```bash
  echo 'export PATH="$PATH:$HOME/.dotnet:$HOME/.dotnet/tools"' >> ~/.bashrc && source ~/.bashrc
  ```
- Permission errors: write to a directory where you have permissions or use `--output-dir`.

## Credits and licenses

- Subtitle Edit CLI (subtitleedit-cli) — LGPL-3.0. See the project: https://github.com/SubtitleEdit/subtitleedit-cli
- FFmpeg — LGPL/GPL. See https://ffmpeg.org/legal.html
- MKVToolNix (mkvmerge/mkvextract) — GPL-2.0+. See https://mkvtoolnix.download/
- ExifTool — Perl Artistic License/GPL. See https://exiftool.org/

This project orchestrates these tools and does not redistribute them. Please ensure their licenses are compatible with your use.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Disclaimer

This software is provided for lawful personal and archival purposes. You are responsible for ensuring you have the rights to process the media you use. The authors disclaim any liability for misuse or infringement arising from use of this tool.
