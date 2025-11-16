#!/usr/bin/env python3

## src/ingestion/frame_store.py

import argparse
import subprocess
from pathlib import Path
import sys



from pathlib import Path
from typing import List


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

    # Adjust extension(s) if you later use .png or others.
    paths = sorted(frames_dir.glob("*.jpg"))

    if not paths:
        raise FileNotFoundError(f"No .jpg frames found in {frames_dir}")

    # Return as strings for easier JSON/logging later
    return [str(p) for p in paths]




def extract_frames(input_video: Path, output_root: Path, fps: int = 1) -> Path:
    """
    Extract frames from the input video at the given FPS and save them
    into a structured directory:

        output_root / <video_stem> / frames / frame_00001.jpg, ...

    Returns the path to the frames directory.
    """
    if not input_video.exists():
        raise FileNotFoundError(f"Input video does not exist: {input_video}")

    video_stem = input_video.stem
    frames_dir = output_root / video_stem / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Output pattern: frame_00001.jpg, frame_00002.jpg, ...
    output_pattern = str(frames_dir / "frame_%05d.jpg")

    # ffmpeg command: 1 frame per second
    cmd = [
        "ffmpeg",
        "-i",
        str(input_video),
        "-vf",
        f"fps={fps}",
        "-qscale:v",
        "2",  # quality (lower is better; 2 is usually visually good)
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


def main():
    parser = argparse.ArgumentParser(
        description="Extract one image per second from an MP4 into a structured directory."
    )
    parser.add_argument(
        "input_video",
        type=str,
        help="Path to the input .mp4 video file",
    )
    parser.add_argument(
        "output_root",
        type=str,
        help="Root directory where extracted frames will be stored",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=1,
        help="Frames per second to extract (default: 1)",
    )

    args = parser.parse_args()

    input_video = Path(args.input_video).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()

    try:
        frames_dir = extract_frames(input_video, output_root, fps=args.fps)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Frames saved in: {frames_dir}")


if __name__ == "__main__":
    main()