#!/usr/bin/env python

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple, List, Callable, Optional

from src.ingestion.video_stream import load_video_frames_bytes
from src.models.vlm_client import (
    describe_image_bytes_batch,
    evaluate_rules_from_summary,
)
from src.pipeline.frame_context import AutomationConfig, load_automation_config


@dataclass
class WindowResult:
    window_index: int
    t_start_sec: float
    t_end_sec: float
    description: str
    delay_seconds: float
    triggered_action_ids: List[str]
    triggered_rule_ids: List[str]


def make_windows(
    num_frames: int,
    frames_per_second: float,
    num_frames_in_sliding_window: int,
    sliding_window_frame_step_size: int,
) -> Iterable[Tuple[int, int, float, float]]:
    """
    Yield (start_idx, end_idx, start_time_s, end_time_s) for each window.

    Windows are defined in *frames*:

    - Each window contains `num_frames_in_sliding_window` frames.
    - Consecutive windows start `sliding_window_frame_step_size` frames apart.
    - Time is derived from frames_per_second (the *downsampled* effective fps).
    """
    if num_frames_in_sliding_window <= 0:
        raise ValueError("num_frames_in_sliding_window must be > 0")
    if sliding_window_frame_step_size <= 0:
        raise ValueError("sliding_window_frame_step_size must be > 0")
    if frames_per_second <= 0:
        raise ValueError("frames_per_second must be > 0")

    start = 0
    while start + num_frames_in_sliding_window <= num_frames:
        end = start + num_frames_in_sliding_window
        start_time_s = start / frames_per_second
        end_time_s = end / frames_per_second
        yield start, end, start_time_s, end_time_s
        start += sliding_window_frame_step_size


def run_vlm_stream_from_video(
    video_name: str,
    num_frames_per_second: float,
    num_frames_in_sliding_window: int,
    sliding_window_frame_step_size: int,
    config: AutomationConfig,
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    policy_model: Optional[str] = None,
    realtime: bool = True,
    on_window_result: Optional[Callable[[WindowResult], None]] = None,
) -> None:
    """
    High-level streaming pipeline from MP4, now split into two stages:

    1. Use the VLM purely for *summarization* of each window of frames.
    2. Use a separate text-only model to evaluate which rules fire, based
       solely on the summary + rule conditions.

    This avoids exposing the vision model to any action metadata and keeps
    the action mapping as a pure Python step.
    """
    frames: List[bytes] = load_video_frames_bytes(
        video_name=video_name,
        num_frames_per_second=num_frames_per_second,
    )

    num_frames = len(frames)
    effective_fps = float(num_frames_per_second)
    total_video_seconds = num_frames / effective_fps

    if policy_model is None:
        # By default, fall back to the same model name; callers can override.
        policy_model = model

    print(f"[INFO] Video '{video_name}'")
    print(
        f"[INFO] Frames decoded after downsampling: {num_frames} "
        f"(≈ {total_video_seconds:.2f}s at {effective_fps:.2f} fps)"
    )
    print(
        f"[INFO] Window size (frames): {num_frames_in_sliding_window}, "
        f"step size (frames): {sliding_window_frame_step_size}"
    )
    print(f"[INFO] Vision model  = {model} @ {base_url}")
    print(f"[INFO] Policy model  = {policy_model} @ {base_url}")
    print(f"[INFO] Loaded {len(config.actions)} actions and {len(config.rules)} rules.")

    # Precompute map for fast rule→action lookup.
    rules_by_id = config.rules_by_id()

    # For realtime sleep we map frame step -> seconds step.
    seconds_per_step = sliding_window_frame_step_size / effective_fps

    for i, (start_idx, end_idx, start_s, end_s) in enumerate(
        make_windows(
            num_frames=num_frames,
            frames_per_second=effective_fps,
            num_frames_in_sliding_window=num_frames_in_sliding_window,
            sliding_window_frame_step_size=sliding_window_frame_step_size,
        )
    ):
        window_images = frames[start_idx:end_idx]

        print(
            f"\n[WINDOW {i}] frames {start_idx}–{end_idx - 1} "
            f"({start_s:.2f}s → {end_s:.2f}s, {len(window_images)} images)"
        )

        t0 = time.time()
        try:
            # Stage 1: pure perception (vision-only).
            summary = describe_image_bytes_batch(
                images=window_images,
                start_s=start_s,
                end_s=end_s,
                model=model,
                base_url=base_url,
            )

            # Stage 2: text-only rule evaluation.
            if config.rules:
                decision = evaluate_rules_from_summary(
                    summary=summary,
                    config=config,
                    model=policy_model,
                    base_url=base_url,
                )
            else:
                decision = {
                    "triggered_rule_ids": [],
                    "reasoning": "No rules configured.",
                    "raw_text": "",
                }
        except Exception as e:
            print(f"[ERROR] Model call failed on window {i}: {e}")
            break

        elapsed = time.time() - t0

        triggered_rules: List[str] = decision.get("triggered_rule_ids", []) or []

        # Map triggered rules → actions locally; the model never sees actions.
        triggered_action_ids: List[str] = []
        seen_actions = set()
        for rule_id in triggered_rules:
            rule = rules_by_id.get(rule_id)
            if rule is None:
                continue
            action_id = rule.action_id
            if action_id not in seen_actions:
                seen_actions.add(action_id)
                triggered_action_ids.append(action_id)

        reasoning = decision.get("reasoning") or ""
        description = summary

        print("[SUMMARY]:", description)
        print("[DECISION] triggered_rule_ids:", triggered_rules)
        print("[DECISION] triggered_action_ids:", triggered_action_ids)
        if reasoning:
            print("[DECISION] reasoning:", reasoning)
        print(f"[DECISION] total latency (vision + policy): {elapsed:.2f}s")

        result = WindowResult(
            window_index=i,
            t_start_sec=start_s,
            t_end_sec=end_s,
            description=description,
            delay_seconds=elapsed,
            triggered_action_ids=list(triggered_action_ids),
            triggered_rule_ids=list(triggered_rules),
        )

        if on_window_result is not None:
            on_window_result(result)

        if realtime:
            time.sleep(seconds_per_step)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream MP4 video into VLM using frame-based windows and automation rules.",
    )
    parser.add_argument(
        "--video-name",
        required=True,
        help="Base name of MP4 under data (e.g. 'video' for data/video.mp4).",
    )
    parser.add_argument(
        "--num-frames-per-second",
        type=float,
        required=True,
        help=(
            "How many frames to keep per second of video after downsampling. "
            "Example: 2.0 -> ~2 frames per real second."
        ),
    )
    parser.add_argument(
        "--num-frames-in-sliding-window",
        type=int,
        required=True,
        help="How many frames the model analyzes at a time.",
    )
    parser.add_argument(
        "--sliding-window-frame-step-size",
        type=int,
        required=True,
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
        help="Vision model name exposed by llama-server.",
    )
    parser.add_argument(
        "--policy-model",
        default=None,
        help=(
            "Optional text-only model used to evaluate which rules fire.\n"
            "Defaults to the same as --model if not set."
        ),
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


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    config_path = Path(args.rules_json).expanduser().resolve()
    config = load_automation_config(config_path)

    run_vlm_stream_from_video(
        video_name=args.video_name,
        num_frames_per_second=args.num_frames_per_second,
        num_frames_in_sliding_window=args.num_frames_in_sliding_window,
        sliding_window_frame_step_size=args.sliding_window_frame_step_size,
        config=config,
        model=args.model,
        base_url=args.base_url,
        policy_model=args.policy_model,
        realtime=not args.no_realtime,
    )
