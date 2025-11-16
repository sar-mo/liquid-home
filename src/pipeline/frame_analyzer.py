import os
import sys
import argparse
import time
from typing import Iterable, Tuple, List

# # ---------------------------------------------------------------------
# # Make sure we can import `src.*` even when running this file directly:
# #   uv run src/pipeline/frame_analyzer.py ...
# # ---------------------------------------------------------------------
# ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# if ROOT not in sys.path:
#     sys.path.insert(0, ROOT)

from src.ingestion.video_stream import load_video_frames_bytes
from src.models.vlm_client import describe_image_bytes_batch


def select_window_images(
    frames: List[bytes],
    start_idx: int,
    end_idx: int,
    max_images: int,
) -> List[bytes]:
    """
    From frames[start_idx:end_idx], pick at most `max_images` frames.

    If the window has <= max_images frames, return all of them.
    Otherwise, sample approximately uniformly across the window.
    """
    slice_frames = frames[start_idx:end_idx]
    n = len(slice_frames)
    if n <= max_images:
        return slice_frames

    # uniform sampling of indices in [0, n)
    step = n / float(max_images)
    indices = [int(i * step) for i in range(max_images)]
    return [slice_frames[i] for i in indices]



def make_windows(
    num_frames: int,
    fps: float,
    window_seconds: float,
    step_seconds: float,
) -> Iterable[Tuple[int, int, float, float]]:
    """
    Yield (start_idx, end_idx, start_time_s, end_time_s) for each window.

    - Every `step_seconds` (t), we take a window of length `window_seconds` (k).
    - Frames indices follow Python slice semantics: [start_idx, end_idx)
    """
    window_size = int(round(window_seconds * fps))
    step_size = int(round(step_seconds * fps))

    if window_size <= 0:
        raise ValueError("window_seconds is too small for the given fps")
    if step_size <= 0:
        raise ValueError("step_seconds is too small for the given fps")

    start = 0
    while start + window_size <= num_frames:
        end = start + window_size
        start_time_s = start / fps
        end_time_s = end / fps
        yield start, end, start_time_s, end_time_s
        start += step_size

def run_vlm_stream_from_video(
    video_name: str,
    fps: float,
    window_seconds: float,
    step_seconds: float,
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    realtime: bool = True,
    max_images_per_window: int = 16,
):
    """
    High-level streaming pipeline from MP4:
    - Load frames from data/test_data/{video_name}.mp4
    - For each window [k seconds], call VLM
    - Print the output every t seconds
    """
    frames: List[bytes] = load_video_frames_bytes(video_name)
    num_frames = len(frames)
    total_video_seconds = num_frames / fps

    print(f"[INFO] Video '{video_name}'")
    print(f"[INFO] Frames decoded: {num_frames} (≈ {total_video_seconds:.2f}s at {fps} fps)")
    print(
        f"[INFO] Window = {window_seconds:.2f}s, step = {step_seconds:.2f}s "
        f"({int(round(window_seconds * fps))} frames/window before subsampling)"
    )
    print(f"[INFO] Max images per window: {max_images_per_window}")
    print(f"[INFO] Model = {model} @ {base_url}")

    for i, (start_idx, end_idx, start_s, end_s) in enumerate(
        make_windows(num_frames, fps, window_seconds, step_seconds)
    ):
        window_images = select_window_images(
            frames=frames,
            start_idx=start_idx,
            end_idx=end_idx,
            max_images=max_images_per_window,
        )

        print(
            f"\n[WINDOW {i}] frames {start_idx}–{end_idx - 1} "
            f"({start_s:.2f}s → {end_s:.2f}s, {len(window_images)} images after subsampling)"
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

        if realtime:
            time.sleep(step_seconds)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream MP4 video into VLM in fixed time windows."
    )
    parser.add_argument(
        "--video-name",
        required=True,
        help="Base name of MP4 under data/test_data (e.g. '15fps-surveillance-video').",
    )
    parser.add_argument(
        "--fps",
        type=float,
        required=True,
        help="Frames per second of the video (f). Used for timing/windowing.",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        required=True,
        help="Length of each chunk in seconds (k).",
    )
    parser.add_argument(
        "--step-seconds",
        type=float,
        required=True,
        help="How often to send a chunk in seconds (t).",
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
    parser.add_argument(
        "--max-images-per-window",
        type=int,
        default=16,
        help="Maximum number of frames to send to the VLM per window.",
    )
    return parser


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    run_vlm_stream_from_video(
        video_name=args.video_name,
        fps=args.fps,
        window_seconds=args.window_seconds,
        step_seconds=args.step_seconds,
        model=args.model,
        base_url=args.base_url,
        realtime=not args.no_realtime,
        max_images_per_window=args.max_images_per_window,
    )
