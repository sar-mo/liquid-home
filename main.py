#!/usr/bin/env python3
"""
Liquid Home: Vision-based home automation demo.

This tool:

- Reads a local MP4 video from `data/<video-name>.mp4`
- Downsamples it to a fixed number of frames per second
- Slides a fixed-size window of frames over the sequence
- Sends each window to a vision-language model (VLM)
- Applies user-defined IF/THEN rules from a JSON file
- Prints which actions and rules are triggered for each window

Typical usage:

    uv run main.py \
      --video-name video \
      --num-frames-per-second 2 \
      --num-frames-in-sliding-window 4 \
      --sliding-window-frame-step-size 4 \
      --rules-json data/context/automation_rules.json
"""

from pathlib import Path
import argparse

from src.pipeline.frame_analyzer import run_vlm_stream_from_video
from src.pipeline.frame_context import load_automation_config


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Liquid Home: stream video into a VLM and trigger automation rules."
    )
    parser.add_argument(
        "--video-name",
        required=True,
        help="Base name of MP4 under data/ (e.g. 'video' for data/video.mp4).",
    )
    parser.add_argument(
        "--num-frames-per-second",
        type=float,
        default=2.0,
        help=(
            "How many frames to keep per second of video after downsampling. "
            "Example: 2.0 -> ~2 frames per real second."
        ),
    )
    parser.add_argument(
        "--num-frames-in-sliding-window",
        type=int,
        default=4,
        help="How many frames the model analyzes at a time.",
    )
    parser.add_argument(
        "--sliding-window-frame-step-size",
        type=int,
        default=4,
        help="How many frames to advance between consecutive windows.",
    )
    parser.add_argument(
        "--rules-json",
        type=str,
        default="data/context/automation_rules.json",
        help=(
            "Path to a JSON file containing 'actions' and 'rules' definitions "
            "for the home automation engine."
        ),
    )
    parser.add_argument(
        "--model",
        default="lfm2-vl-450m-f16",
        help="Model name exposed by llama-server.",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080/v1",
        help="Base URL for llama-server's OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="If set, do NOT sleep between windows (process as fast as possible).",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    rules_path = Path(args.rules_json).expanduser().resolve()
    config = load_automation_config(rules_path)

    run_vlm_stream_from_video(
        video_name=args.video_name,
        num_frames_per_second=args.num_frames_per_second,
        num_frames_in_sliding_window=args.num_frames_in_sliding_window,
        sliding_window_frame_step_size=args.sliding_window_frame_step_size,
        config=config,
        model=args.model,
        base_url=args.base_url,
        realtime=not args.no_realtime,
    )


if __name__ == "__main__":
    main()
