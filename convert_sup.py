#!/usr/bin/env python3
"""Standalone SUP subtitle to text converter using Subtitle Edit CLI (seconv)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

 # No Python OCR libraries required; uses external CLI


class ConversionError(RuntimeError):
    """Raised when SUP conversion fails."""


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
        raise ConversionError(
            f"Command failed: {' '.join(cmd)}\n{exc.stderr.strip()}"
        ) from exc

    return result.stdout if capture_stdout and result.stdout is not None else ""


def resolve_se_path(se_path: Optional[Path]) -> Optional[Path]:
    if se_path and Path(se_path).exists():
        return Path(se_path)
    # Try default user-local install location
    default = Path.home() / ".dotnet" / "tools" / "SubtitleEdit.CLI"
    if default.exists():
        return default
    return None


def ensure_dependencies(*, se_path: Optional[Path]) -> None:
    # If explicit path provided or default exists, we're good
    if se_path and Path(se_path).exists():
        return
    # Otherwise, see if it's on PATH
    if shutil.which("SubtitleEdit.CLI") is None:
        raise SystemExit("Subtitle Edit CLI not found. Install it (dotnet tool) or provide --se-path.")


 # No image processing here; handled by Subtitle Edit CLI


def parse_float(value: Optional[str]) -> float:
    try:
        return float(value) if value is not None else 0.0
    except ValueError:
        return 0.0


 # Timing formatting not needed; Subtitle Edit writes SRT


def subtitleedit_convert(
    sup_path: Path,
    *,
    se_path: Optional[Path] = None,
    verbose: bool = True,
) -> Dict[str, Path]:
    def report(message: str) -> None:
        if verbose:
            print(message)
    srt_path = sup_path.with_suffix(".srt")
    if srt_path.exists():
        srt_path.unlink()
    exec_path = str(se_path) if se_path else "SubtitleEdit.CLI"
    report("Converting with Subtitle Edit CLI…")
    # seconv usage: seconv <pattern> <format>
    # Use absolute SUP path as pattern and request SRT output
    run_cmd([exec_path, str(sup_path), "srt"])
    txt_path = sup_path.with_suffix(".txt")
    try:
        if txt_path.exists():
            txt_path.unlink()
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
    return {"srt": srt_path, "txt": txt_path}


def convert_sup(
    sup_path: Path,
    *,
    verbose: bool = True,
    se_path: Optional[Path] = None,
) -> Dict[str, Path]:
    return subtitleedit_convert(sup_path, se_path=se_path, verbose=verbose)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a SUP subtitle file into SRT/TXT via OCR.")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more inputs: .sup files, directories (scan for *.sup), or shell globs (expand by shell)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages (errors will still be shown).",
    )
    parser.add_argument(
        "--se-path",
        type=Path,
        help="Path to SubtitleEdit.CLI executable if not on PATH.",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    resolved_se = resolve_se_path(args.se_path)
    ensure_dependencies(se_path=resolved_se)

    verbose = not args.quiet

    # Collect .sup files from inputs
    sup_files: List[Path] = []
    for item in args.inputs:
        p = Path(item)
        if any(ch in item for ch in "*?["):
            # Shell may have already expanded; if not, expand here
            for g in sorted(p.parent.glob(p.name) if p.parent != Path("") else Path.cwd().glob(p.name)):
                if g.is_file() and g.suffix.lower() == ".sup":
                    sup_files.append(g)
            continue
        if p.is_dir():
            for sup in sorted(p.glob("*.sup")):
                if sup.is_file():
                    sup_files.append(sup)
        elif p.is_file() and p.suffix.lower() == ".sup":
            sup_files.append(p)
        else:
            print(f"Skip (not a .sup file or directory): {p}")

    if not sup_files:
        print("No .sup files found to convert.", file=sys.stderr)
        return 1

    rc = 0
    for sup_path in sup_files:
        if verbose:
            print(f"Converting SUP: {sup_path}")
        try:
            outputs = convert_sup(sup_path, verbose=verbose, se_path=resolved_se)
            if verbose:
                print("Outputs:")
                for label, path in outputs.items():
                    print(f"  {label}: {path}")
        except ConversionError as exc:
            print(f"Conversion failed for {sup_path}: {exc}", file=sys.stderr)
            rc = 1

    return rc


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
