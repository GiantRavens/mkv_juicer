#!/usr/bin/env python3
"""MKV Juicer - Extract and convert MKV components."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    # Prefer reusing the standalone SUP converter to avoid duplication (kept for potential future use)
    from convert_sup import convert_sup as sup_convert  # noqa: F401
except Exception:
    sup_convert = None

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "PyYAML is required. Install with `pip install pyyaml`."
    ) from exc

# Tesseract no longer required; Subtitle Edit CLI handles PGS OCR


class ExtractionError(RuntimeError):
    """Represents a failure while running an external extraction command."""


VIDEO_EXTENSIONS: Dict[str, str] = {
    "V_MPEG4/ISO/AVC": "h264",
    "V_MPEGH/ISO/HEVC": "h265",
    "V_MPEG2": "m2v",
    "V_MPEG1": "mpg",
    "V_MS/VFW/FOURCC": "avi",
    "V_MS/VFW/FOURCC/h264": "h264",
    "V_PRORES": "mov",
    "V_QUICKTIME": "mov",
    "V_VC1": "vc1",
}

AUDIO_EXTENSIONS: Dict[str, str] = {
    "A_AAC": "aac",
    "A_AC3": "ac3",
    "A_ALAC": "alac",
    "A_DTS": "dts",
    "A_DTS/EXPRESS": "ddp",
    "A_EAC3": "eac3",
    "A_FLAC": "flac",
    "A_MLP": "mlp",
    "A_MPEG/L2": "mp2",
    "A_MPEG/L3": "mp3",
    "A_OPUS": "opus",
    "A_PCM/INT/BIG": "wav",
    "A_PCM/INT/LIT": "wav",
    "A_PCM/INT": "wav",
    "A_TRUEHD": "thd",
    "A_VORBIS": "ogg",
}

SUBTITLE_EXTENSIONS: Dict[str, str] = {
    "S_TEXT/UTF8": "srt",
    "S_TEXT/SSA": "ssa",
    "S_TEXT/ASS": "ass",
    "S_TEXT/USF": "usf",
    "S_TEXT/WEBVTT": "vtt",
    "S_VOBSUB": "sub",
    "S_HDMV/PGS": "sup",
    "S_KATE": "kate",
}

VIDEO_EDITOR_CONTAINERS: Dict[str, str] = {
    "V_MPEG4/ISO/AVC": "mp4",
    "V_MPEGH/ISO/HEVC": "mp4",
    "V_PRORES": "mov",
    "V_QUICKTIME": "mov",
    "V_MPEG2": "mpg",
    "V_MPEG1": "mpg",
}

AAC_BITRATE = "192k"


@dataclass
class TrackResult:
    track_id: int
    type: str
    codec_id: Optional[str]
    language: Optional[str]
    original: Optional[Path] = None
    derivatives: List[Path] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_manifest_entry(self) -> Dict[str, Any]:
        return {
            "id": self.track_id,
            "type": self.type,
            "codec_id": self.codec_id,
            "language": self.language,
            "original": str(self.original) if self.original else None,
            "derivatives": [str(path) for path in self.derivatives],
            "notes": self.notes,
        }


def run_cmd(cmd: List[str], *, capture_stdout: bool = False) -> str:
    stdout = subprocess.PIPE if capture_stdout else None
    try:
        result = subprocess.run(
            cmd,
            stdout=stdout,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - thin wrapper
        raise ExtractionError(
            f"Command failed: {' '.join(cmd)}\n{exc.stderr.strip()}"
        ) from exc

    return result.stdout if capture_stdout and result.stdout is not None else ""


def run_ffmpeg_with_progress(cmd: List[str], *, label: str = "ffmpeg") -> None:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        last_print = ""
        assert process.stderr is not None
        for line in process.stderr:
            line = line.strip()
            if not line:
                continue
            # Look for time=HH:MM:SS.xx in ffmpeg progress lines
            if "time=" in line:
                # extract substring after 'time='
                try:
                    tpos = line.index("time=") + 5
                    time_str = line[tpos:].split()[0]
                    msg = f"  {label}: {time_str}"
                except Exception:
                    msg = f"  {label}: working…"
                if msg != last_print:
                    print(msg, end="\r", flush=True)
                    last_print = msg
        code = process.wait()
        if last_print:
            print()  # newline after carriage updates
        if code != 0:
            raise ExtractionError(f"Command failed: {' '.join(cmd)}")
    except Exception:
        process.kill()
        process.wait()
        raise


def ensure_dependencies(*, make_editable: bool, se_path: Optional[Path] = None) -> None:
    base_tools = ("mkvmerge", "mkvextract", "exiftool")
    for tool in base_tools:
        if shutil.which(tool) is None:
            raise SystemExit(
                f"Required tool '{tool}' not found in PATH. Please install it (e.g. `brew install {tool}`)."
            )

    if make_editable:
        for tool in ("ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                raise SystemExit(
                    f"Required tool '{tool}' not found in PATH for --make-editable. Please install it."
                )
        # Accept explicit path or default user-local location; otherwise require on PATH
        if se_path and Path(se_path).exists():
            pass
        elif shutil.which("SubtitleEdit.CLI") is None:
            raise SystemExit(
                "Subtitle Edit CLI not found (SubtitleEdit.CLI). Install it or provide --se-path."
            )

def resolve_se_path(se_path: Optional[Path]) -> Optional[Path]:
    if se_path and Path(se_path).exists():
        return Path(se_path)
    default = Path.home() / ".dotnet" / "tools" / "SubtitleEdit.CLI"
    if default.exists():
        return default
    return None


def sanitize_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return sanitized or "component"


def inspect_mkv(path: Path) -> Dict[str, Any]:
    output = run_cmd(["mkvmerge", "-J", str(path)], capture_stdout=True)
    return json.loads(output)


def ffprobe_stream_info(path: Path) -> Dict[str, Any]:
    data = run_cmd([
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        str(path),
    ], capture_stdout=True)
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return {}


def get_channel_labels(channels: int, layout: Optional[str]) -> List[str]:
    layout = (layout or "").lower()
    # Common layouts based on FFmpeg default order
    known: Dict[str, List[str]] = {
        "mono": ["C"],
        "stereo": ["L", "R"],
        "2.1": ["L", "R", "LFE"],
        "3.0": ["L", "R", "C"],
        "3.1": ["L", "R", "C", "LFE"],
        "4.0": ["FL", "FR", "BL", "BR"],
        "5.0": ["FL", "FR", "FC", "SL", "SR"],
        "5.1": ["FL", "FR", "FC", "LFE", "SL", "SR"],
        "7.1": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    }
    if layout in known and len(known[layout]) == channels:
        return known[layout]
    # Fallback by channel count
    by_count: Dict[int, List[str]] = {
        1: ["C"],
        2: ["L", "R"],
        6: ["FL", "FR", "FC", "LFE", "SL", "SR"],
        8: ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    }
    if channels in by_count:
        return by_count[channels]
    return [f"c{i}" for i in range(channels)]


def extract_exif_metadata(path: Path) -> Dict[str, Any]:
    output = run_cmd(["exiftool", "-j", "-n", str(path)], capture_stdout=True)
    try:
        entries = json.loads(output)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive parsing
        raise ExtractionError(f"Failed to parse exiftool output for {path}: {exc}") from exc

    if not entries:
        return {}

    entry = entries[0]
    fields_of_interest = [
        "FileName",
        "Directory",
        "FileSize",
        "FileType",
        "FileTypeExtension",
        "MIMEType",
        "Duration",
        "DurationSeconds",
        "FrameRate",
        "VideoFrameRate",
        "AvgBitrate",
        "VideoCodecID",
        "VideoCodecName",
        "AudioCodecID",
        "AudioCodecName",
        "ImageWidth",
        "ImageHeight",
        "DisplayAspectRatio",
        "PixelAspectRatio",
        "MatrixCoefficients",
        "AudioChannels",
        "AudioBitrate",
        "Title",
        "Description",
        "Album",
        "Track",
        "DateTimeOriginal",
        "CreationDate",
        "WritingApp",
        "MuxingApp",
    ]

    metadata: Dict[str, Any] = {}
    for field in fields_of_interest:
        if field in entry:
            metadata[field] = entry[field]

    return metadata


def parse_time_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_timestamp(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis >= 1000:
        millis -= 1000
        whole += 1
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


# OCR image preprocessing removed (Subtitle Edit CLI handles it)


def convert_sup_to_text(
    sup_path: Path,
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    # This function is deprecated in favor of Subtitle Edit CLI path.
    raise ExtractionError("Internal OCR is disabled. Use Subtitle Edit CLI.")

def subtitleedit_convert_sup(sup_path: Path, *, lang: Optional[str], se_path: Optional[Path]) -> List[Path]:
    srt_path = sup_path.with_suffix(".srt")
    if srt_path.exists():
        srt_path.unlink()
    exec_path = str(se_path) if se_path else "SubtitleEdit.CLI"
    # seconv usage: seconv <pattern> <format>
    cmd = [exec_path, str(sup_path), "srt"]
    run_cmd(cmd)
    txt_path = sup_path.with_suffix(".txt")
    if txt_path.exists():
        txt_path.unlink()
    try:
        lines: List[str] = []
        with srt_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "-->" in line:
                    continue
                if line.strip().isdigit():
                    continue
                if not line.strip():
                    continue
                lines.append(line.rstrip("\n"))
        with txt_path.open("w", encoding="utf-8", newline="") as out:
            for l in lines:
                out.write(l + "\n")
    except Exception:
        pass
    return [srt_path, txt_path]


def choose_extension(track: Dict[str, Any]) -> str:
    codec_id = (track.get("properties") or {}).get("codec_id")
    track_type = track.get("type")
    if track_type == "video" and codec_id in VIDEO_EXTENSIONS:
        return VIDEO_EXTENSIONS[codec_id]
    if track_type == "audio" and codec_id in AUDIO_EXTENSIONS:
        return AUDIO_EXTENSIONS[codec_id]
    if track_type == "subtitles" and codec_id in SUBTITLE_EXTENSIONS:
        return SUBTITLE_EXTENSIONS[codec_id]
    return "bin"


def extract_track(source: Path, track: Dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["mkvextract", "tracks", str(source), f"{track['id']}:{destination}"])


def package_video_for_editor(source_mkv: Path, track: Dict[str, Any], video_index: int, output_dir: Path) -> Optional[Path]:
    codec_id = (track.get("properties") or {}).get("codec_id")
    container_ext = VIDEO_EDITOR_CONTAINERS.get(codec_id)
    if not container_ext:
        return None

    base_name = sanitize_name(f"track_{track['id']}_video")
    packaged = (output_dir / base_name).with_suffix(f".{container_ext}")
    if packaged.exists():
        packaged.unlink()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_mkv),
        "-map",
        f"0:v:{video_index}",
        "-c:v",
        "copy",
        str(packaged),
    ]

    run_cmd(cmd)
    return packaged


def create_audio_reference(original: Path, *, fmt: str) -> Optional[Path]:
    fmt = fmt.lower()
    if fmt == "aac":
        reference = original.with_suffix(".aac")
        if reference.exists():
            reference.unlink()
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(original),
            "-c:a",
            "aac",
            "-b:a",
            AAC_BITRATE,
            str(reference),
        ]
    elif fmt == "wav":
        reference = original.with_suffix(".wav")
        if reference.exists():
            reference.unlink()
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(original),
            "-c:a",
            "pcm_s16le",
            str(reference),
        ]
    elif fmt == "flac":
        reference = original.with_suffix(".flac")
        if reference.exists():
            reference.unlink()
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(original),
            "-c:a",
            "flac",
            str(reference),
        ]
    else:
        raise ExtractionError(f"Unsupported editable audio format: {fmt}")

    print(f"Creating audio reference ({fmt.upper()})…")
    run_ffmpeg_with_progress(cmd, label=f"audio {fmt}")
    return reference


def split_audio_channels(reference: Path) -> List[Path]:
    info = ffprobe_stream_info(reference)
    streams = info.get("streams", [])
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not a:
        return []
    channels = int(a.get("channels", 0) or 0)
    if channels <= 1:
        return []
    layout = a.get("channel_layout")
    labels = get_channel_labels(channels, layout)
    print(f"Splitting audio channels: {channels} channels, layout='{layout or 'unknown'}' -> {labels}")
    stems: List[Path] = []
    for idx in range(channels):
        label = labels[idx] if idx < len(labels) else f"c{idx}"
        target = reference.with_name(reference.stem + f"_{label}" + reference.suffix)
        if target.exists():
            target.unlink()
        # Use pan filter to select channel by index, robust even when layout is missing
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(reference),
            "-filter_complex",
            f"pan=mono|c0=c{idx}",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
        print(f"Creating stem {label}…")
        run_ffmpeg_with_progress(cmd, label=f"stem {label}")
        stems.append(target)
    return stems


def derive_subtitle_outputs(
    extracted: Path,
    track: Dict[str, Any],
    *,
    se_path: Optional[Path] = None,
) -> List[Path]:
    codec_id = (track.get("properties") or {}).get("codec_id")
    derivatives: List[Path] = []

    if codec_id in {"S_TEXT/UTF8", "S_TEXT/WEBVTT"} and extracted.suffix != ".srt":
        target = extracted.with_suffix(".srt")
        shutil.copy2(extracted, target)
        derivatives.append(target)
    elif codec_id in {"S_TEXT/SSA", "S_TEXT/ASS"}:
        target = extracted.with_suffix(".txt")
        with target.open("w", encoding="utf-8", newline="") as handle:
            with extracted.open("r", encoding="utf-8", errors="replace") as src:
                handle.write(src.read())
        derivatives.append(target)
    elif codec_id == "S_HDMV/PGS":
        derivatives.extend(subtitleedit_convert_sup(extracted, lang=None, se_path=se_path))
    else:
        pass

    return derivatives


def extract_attachments(source: Path, attachments: Iterable[Dict[str, Any]], output_dir: Path) -> List[Dict[str, Any]]:
    attachments = list(attachments)
    if not attachments:
        return []

    cmd = ["mkvextract", "attachments", str(source)]
    extracted_paths: List[Dict[str, Any]] = []

    for attachment in attachments:
        attachment_id = attachment.get("id")
        file_name = attachment.get("file_name") or f"attachment_{attachment_id}"
        target = output_dir / sanitize_name(file_name)
        cmd.append(f"{attachment_id}:{target}")
        extracted_paths.append(
            {
                "id": attachment_id,
                "file_name": file_name,
                "mime_type": attachment.get("content_type"),
                "path": str(target),
            }
        )

    run_cmd(cmd)
    return extracted_paths


def extract_chapters(source: Path, output_dir: Path) -> Optional[Path]:
    chapters_path = output_dir / "chapters.txt"
    output = run_cmd(["mkvextract", "chapters", "--simple", str(source)], capture_stdout=True)
    if not output.strip():
        return None
    chapters_path.write_text(output, encoding="utf-8")
    return chapters_path


def extract_tags(source: Path, output_dir: Path) -> Optional[Path]:
    tags_path = output_dir / "tags.xml"
    output = run_cmd(["mkvextract", "tags", str(source)], capture_stdout=True)
    if not output.strip():
        return None
    tags_path.write_text(output, encoding="utf-8")
    return tags_path


def process_track(
    source: Path,
    track: Dict[str, Any],
    output_dir: Path,
    audio_only: bool,
    subtitles_only: bool,
    *,
    make_editable: bool,
    editable_audio_format: str,
    video_index_map: Optional[Dict[int, int]] = None,
    se_path: Optional[Path] = None,
    split_audio_channels_flag: bool = False,
) -> Optional[TrackResult]:
    track_type = track.get("type")
    if audio_only and track_type != "audio":
        return None
    if subtitles_only and track_type != "subtitles":
        return None

    codec_id = (track.get("properties") or {}).get("codec_id")
    language = (track.get("properties") or {}).get("language")

    extension = choose_extension(track)
    base_name = sanitize_name(f"track_{track['id']}_{track_type}")
    extracted_path = output_dir / f"{base_name}.{extension}"

    result = TrackResult(
        track_id=track["id"],
        type=track_type,
        codec_id=codec_id,
        language=language,
        original=extracted_path,
    )

    extract_track(source, track, extracted_path)

    if make_editable:
        if track_type == "video":
            index = None
            if video_index_map is not None:
                index = video_index_map.get(track["id"])
            if index is None:
                result.notes.append("Could not determine video stream index for rewrap; skipping.")
            else:
                packaged = package_video_for_editor(source, track, index, output_dir)
                if packaged:
                    result.derivatives.append(packaged)
                else:
                    result.notes.append("No editor-friendly container generated for this codec.")
        elif track_type == "audio":
            try:
                # If source is AC3 and user left default AAC, prefer WAV to avoid lossy transcode and speed up
                fmt_for_track = (
                    "wav" if (editable_audio_format == "aac" and codec_id == "A_AC3") else editable_audio_format
                )
                reference = create_audio_reference(extracted_path, fmt=fmt_for_track)
                if reference:
                    result.derivatives.append(reference)
                    if split_audio_channels_flag and reference.suffix.lower() == ".wav":
                        try:
                            stems = split_audio_channels(reference)
                            result.derivatives.extend(stems)
                        except ExtractionError as exc:
                            result.notes.append(f"Failed to split audio channels: {exc}")
            except ExtractionError as exc:
                result.notes.append(f"Failed to create audio reference: {exc}")
        elif track_type == "subtitles":
            try:
                result.derivatives.extend(derive_subtitle_outputs(extracted_path, track, se_path=se_path))
            except ExtractionError as exc:
                result.notes.append(f"Subtitle conversion issue: {exc}")

    return result


def process_file(
    path: Path,
    *,
    audio_only: bool,
    subtitles_only: bool,
    base_output_dir: Optional[Path] = None,
    make_editable: bool = False,
    editable_audio_format: str = "aac",
    se_path: Optional[Path] = None,
    split_audio_channels_flag: bool = False,
) -> Dict[str, Any]:
    print(f"Juicing: {path}")
    metadata = inspect_mkv(path)
    tracks = metadata.get("tracks", [])
    attachments_meta = metadata.get("attachments", [])

    base_dir = base_output_dir if base_output_dir else path.parent
    output_dir = base_dir / sanitize_name(path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {
        "source": str(path),
        "output_dir": str(output_dir),
        "audio_only": audio_only,
        "subtitles_only": subtitles_only,
        "make_editable": make_editable,
        "editable_audio_format": editable_audio_format,
        "tracks": [],
    }

    exif_metadata = extract_exif_metadata(path)
    if exif_metadata:
        manifest["container_metadata"] = exif_metadata

    # Build a map from mkvmerge track id -> video stream index (0-based among video streams)
    video_index_map: Dict[int, int] = {}
    vid_idx = 0
    for t in tracks:
        if t.get("type") == "video":
            video_index_map[t["id"]] = vid_idx
            vid_idx += 1

    extracted_tracks: List[TrackResult] = []
    for track in tracks:
        result = process_track(
            path,
            track,
            output_dir,
            audio_only,
            subtitles_only,
            make_editable=make_editable,
            editable_audio_format=editable_audio_format,
            video_index_map=video_index_map,
            se_path=se_path,
            split_audio_channels_flag=split_audio_channels_flag,
        )
        if result:
            extracted_tracks.append(result)

    manifest["tracks"] = [track.to_manifest_entry() for track in extracted_tracks]

    if not audio_only and not subtitles_only:
        attachments = extract_attachments(path, attachments_meta, output_dir)
        if attachments:
            manifest["attachments"] = attachments

        chapters_path = extract_chapters(path, output_dir)
        if chapters_path:
            manifest["chapters"] = str(chapters_path)

        tags_path = extract_tags(path, output_dir)
        if tags_path:
            manifest["tags"] = str(tags_path)

    manifest_path = output_dir / "manifest.yaml"
    with manifest_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(manifest, handle, sort_keys=False, allow_unicode=True)

    print(f"  Manifest written to {manifest_path}")
    return manifest


def iter_mkv_files(target: Path) -> Iterable[Path]:
    if target.is_file() and target.suffix.lower() == ".mkv":
        yield target
        return
    if target.is_dir():
        for mkv in sorted(target.rglob("*.mkv")):
            yield mkv
        return
    raise SystemExit(f"No MKV files found at {target}")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demux MKV components into editable assets.")
    parser.add_argument(
        "path",
        type=Path,
        help="Path to an MKV file or a directory containing MKVs.",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Only process audio tracks.",
    )
    parser.add_argument(
        "--subtitles-only",
        action="store_true",
        help="Only process subtitle tracks.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Base directory to place per-file output folders.",
    )
    parser.add_argument(
        "--make-editable",
        action="store_true",
        help="Generate editor-friendly derivatives (video rewraps, audio refs, subtitle conversions).",
    )
    parser.add_argument(
        "--editable-audio-format",
        choices=["aac", "wav", "flac"],
        default="wav",
        help="Audio format for editor-friendly reference when using --make-editable.",
    )
    parser.add_argument(
        "--se-path",
        type=Path,
        help="Path to SubtitleEdit.CLI executable if not on PATH.",
    )
    parser.add_argument(
        "--split-audio-channels",
        action="store_true",
        help="Also create per-channel WAV stems from the audio reference (when using --make-editable).",
    )
    args = parser.parse_args(argv)
    if args.audio_only and args.subtitles_only:
        parser.error("--audio-only and --subtitles-only cannot be combined.")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    resolved_se = resolve_se_path(args.se_path)
    ensure_dependencies(make_editable=args.make_editable, se_path=resolved_se)

    targets = list(iter_mkv_files(args.path))
    if not targets:
        print("No MKV files found to process.")
        return 1

    for mkv_path in targets:
        try:
            process_file(
                mkv_path,
                audio_only=args.audio_only,
                subtitles_only=args.subtitles_only,
                base_output_dir=args.output_dir,
                make_editable=args.make_editable,
                editable_audio_format=args.editable_audio_format,
                se_path=resolved_se,
                split_audio_channels_flag=args.split_audio_channels,
            )
        except ExtractionError as exc:
            print(f"Extraction failed for {mkv_path}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
