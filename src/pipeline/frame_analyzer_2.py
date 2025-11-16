#!/usr/bin/env python

import argparse
from datetime import datetime
import time
from typing import Iterable, Tuple, List

from src.ingestion.video_stream import load_video_frames_bytes
from src.models.vlm_client import describe_image_bytes_batch
from src.models.scene_detector import HomeAutomationActionDetector
import os


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
    room_name: str = "unknown",
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    realtime: bool = True,
):
    """
    High-level streaming pipeline from MP4:

    - Load frames from data/{video_name}.mp4
      (downsampled so we keep about `num_frames_per_second` frames/sec).
    - Slide a fixed-size window of frames across the sequence.
    - For each window, call the VLM and print the output.
    - Every 5 seconds of video, aggregate summaries and call home automation detector.

    Parameters (the only behavior knobs):

    - num_frames_per_second: how densely we sample the original video in time.
    - num_frames_in_sliding_window: how many frames the model sees at once.
    - sliding_window_frame_step_size: how many frames we advance between windows.
    - room_name: name of the room being monitored (for home automation context).
    """
    frames: List[bytes] = load_video_frames_bytes(
        video_name=video_name,
        num_frames_per_second=num_frames_per_second,
    )

    num_frames = len(frames)
    effective_fps = float(num_frames_per_second)
    total_video_seconds = num_frames / effective_fps

    print(f"[INFO] Video '{video_name}'")
    print(
        f"[INFO] Frames decoded after downsampling: {num_frames} "
        f"(≈ {total_video_seconds:.2f}s at {effective_fps:.2f} fps)"
    )
    print(
        f"[INFO] Window size (frames): {num_frames_in_sliding_window}, "
        f"step size (frames): {sliding_window_frame_step_size}"
    )
    print(f"[INFO] Model = {model} @ {base_url}")
    print(f"[INFO] Room = {room_name}")

    # For realtime sleep we map frame step -> seconds step.
    seconds_per_step = sliding_window_frame_step_size / effective_fps

    # Initialize home automation detector
    detector = HomeAutomationActionDetector(
        api_key=os.getenv("OPENAI_API_KEY", "your-api-key-here")
    )

    outputs = []
    summaries_buffer = []
    last_automation_check_time = 0.0
    AUTOMATION_CHECK_INTERVAL = 10.0  # Check every 5 seconds

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

        try:
            output = describe_image_bytes_batch(
                images=window_images,
                start_s=start_s,
                end_s=end_s,
                model=model,
                base_url=base_url,
            )
        except Exception as e:
            print(f"[ERROR] VLM call failed on window {i}: {e}")
            break

        print("[MODEL OUTPUT]")
        print(output)
        outputs.append(output)
        
        # Add summary to buffer with timestamp
        summaries_buffer.append({
            "timestamp": end_s,
            "summary": output
        })

        # Check if we've accumulated 5 seconds worth of summaries
        if end_s - last_automation_check_time >= AUTOMATION_CHECK_INTERVAL:
            print("\n" + "="*60)
            print(f"[HOME AUTOMATION] Processing summaries from {last_automation_check_time:.2f}s to {end_s:.2f}s")
            print("="*60)
            
            # Combine summaries from the last 5 seconds
            combined_summary = " ".join([s["summary"] for s in summaries_buffer])
    
            # Get time of day
            current_time = datetime.now()
            hour = current_time.hour
            if 7 <= hour < 12:
                time_of_day = "morning"
            elif 12 <= hour < 16:
                time_of_day = "afternoon"
            elif 16 <= hour < 19:
                time_of_day = "evening"
            else:
                time_of_day = "night"
            
            # Call home automation detector
            try:
                result = detector.process_video_summary(
                    room=room_name,
                    video_summary=combined_summary,
                    time_of_day=time_of_day
                )
                
                # Display results
                print(f"\n[SCENE DETECTED]")
                scene = result.get("scene_input", {})
                print(f"  Description: {scene.get('scene_description', 'N/A')}")
                print(f"  Objects: {scene.get('objects_detected', [])}")
                print(f"  People Count: {scene.get('people_count', 0)}")
                print(f"  Activities: {scene.get('activities', [])}")
                
                print(f"\n[AUTOMATION ACTIONS]")
                actions = result.get("actions", [])
                if actions:
                    for action in actions:
                        print(f"  → {action['action_type']}: {action.get('target', 'N/A')}")
                        if action.get('parameters'):
                            print(f"    Parameters: {action['parameters']}")
                        print(f"    Priority: {action.get('priority', 'medium')}")
                else:
                    print("  No actions recommended")
                
                if result.get("unusual_activity_detected"):
                    print(f"\n⚠️  [ALERT] Unusual Activity Detected!")
                    print(f"  {result.get('unusual_activity_description', 'N/A')}")
                
                print(f"\nConfidence: {result.get('confidence', 0.0):.2f}")
                
            except Exception as e:
                print(f"[ERROR] Home automation detector failed: {e}")
            
            # Reset buffer and update last check time
            summaries_buffer = []
            last_automation_check_time = end_s
            print("="*60 + "\n")

        if realtime:
            time.sleep(seconds_per_step)
    
    # Process any remaining summaries at the end
    if summaries_buffer:
        print("\n" + "="*60)
        print(f"[HOME AUTOMATION] Processing final summaries")
        print("="*60)
        
        combined_summary = " ".join([s["summary"] for s in summaries_buffer])
        
        try:
            result = detector.process_video_summary(
                room=room_name,
                video_summary=combined_summary
            )
            
            print(f"\n[FINAL SCENE]")
            scene = result.get("scene_input", {})
            print(f"  Description: {scene.get('scene_description', 'N/A')}")
            print(f"  Actions: {[a['action_type'] for a in result.get('actions', [])]}")
            
        except Exception as e:
            print(f"[ERROR] Home automation detector failed: {e}")
        
        print("="*60 + "\n")
    
    return outputs


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream MP4 video into VLM using frame-based windows."
    )
    parser.add_argument(
        "--video-name",
        required=True,
        help="Base name of MP4 under data (e.g. '15fps-surveillance-video').",
    )
    parser.add_argument(
        "--num-frames-per-second",
        type=float,
        required=True,
        help=(
            "How many frames to keep per second of video after downsampling. "
            "Example: 1.0 -> ~1 frame per real second."
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
        "--room-name",
        default="unknown",
        help="Name of the room being monitored (e.g., 'living_room', 'bedroom').",
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


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    result = run_vlm_stream_from_video(
        video_name=args.video_name,
        num_frames_per_second=args.num_frames_per_second,
        num_frames_in_sliding_window=args.num_frames_in_sliding_window,
        sliding_window_frame_step_size=args.sliding_window_frame_step_size,
        room_name=args.room_name,
        model=args.model,
        base_url=args.base_url,
        realtime=not args.no_realtime,
    )

    print(f"\n[INFO] Processed {len(result)} total windows")