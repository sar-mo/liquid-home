#!/usr/bin/env python3
"""
Utilities for working with extracted frame folders on disk.

This module is mostly for tests / experiments. The main streaming pipeline
does not depend on it.
"""

from pathlib import Path
from typing import List
import subprocess


def list_test_video_frames(video_name: str) -> List[str]:
    """
    Given a logical video name (e.g. '15fps-surveillance-video'), return a
    sorted list of absolute frame paths from:

        data/{video_name}/frames/*.jpg
    """
    root = Path(__file__).resolve().parents[2]  # go from src/ingestion/... -> repo root
    frames_dir = root / "data" / video_name / "frames"

    if not frames_dir.exists():
        raise FileNotFoundError(f"Frames directory does not exist: {frames_dir}")

    paths = sorted(frames_dir.glob("*.jpg"))
    if not paths:
        raise FileNotFoundError(f"No .jpg frames found in {frames_dir}")

    return [str(p) for p in paths]


def extract_frames(
    input_video: Path,
    output_root: Path,
    num_frames_per_second: int = 1,
) -> Path:
    """
    Extract frames from the input video at a fixed rate and save them into:

        output_root / <video_stem> / frames / frame_00001.jpg, ...

    num_frames_per_second: how many frames to keep per second of video.
    """
    if not input_video.exists():
        raise FileNotFoundError(f"Input video does not exist: {input_video}")

    video_stem = input_video.stem
    frames_dir = output_root / video_stem / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = str(frames_dir / "frame_%05d.jpg")

    cmd = [
        "ffmpeg",
        "-i",
        str(input_video),
        "-vf",
        f"fps={num_frames_per_second}",
        "-qscale:v",
        "2",
        output_pattern,
    ]

    print(f"Running command:\n{' '.join(cmd)}\n")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found. Please install ffmpeg and make sure it's in your PATH."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed with exit code {e.returncode}") from e

    return frames_dir
