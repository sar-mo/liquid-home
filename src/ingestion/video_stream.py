#!/usr/bin/env python

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import cv2


def load_video_frames_bytes(
    video_name: str,
    max_width: Optional[int] = 640,
    num_frames_per_second: Optional[float] = None,
) -> List[bytes]:
    """
    Load an MP4 from data/{video_name}.mp4 and return a list of
    JPEG-encoded frames as bytes.

    - Optionally downscales frames so their width <= max_width.
    - Optionally downsamples in time so we keep about num_frames_per_second
      frames per second of video. For example, a 22-second video with
      num_frames_per_second=2 will yield ≈44 frames.
    """
    root = Path(__file__).resolve().parents[2]  # repo root
    video_path = root / "data" / f"{video_name}.mp4"

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    actual_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if actual_fps <= 0:
        # Fallback if metadata is missing; treat as 30fps.
        actual_fps = 30.0

    print(f"[INFO] Video file {video_path} reports FPS ≈ {actual_fps:.2f}")

    keep_every_n = 1
    if num_frames_per_second is not None:
        if num_frames_per_second <= 0:
            raise ValueError("num_frames_per_second must be > 0")
        # Keep roughly num_frames_per_second frames per second.
        keep_every_n = max(1, int(round(actual_fps / num_frames_per_second)))
        effective_fps = actual_fps / keep_every_n
        print(
            f"[INFO] Target ~{num_frames_per_second:.2f} frames/sec; "
            f"keeping 1 of every {keep_every_n} frames "
            f"(effective ≈ {effective_fps:.2f} fps)."
        )
    else:
        effective_fps = actual_fps
        print("[INFO] num_frames_per_second not set; keeping all frames.")

    frames: List[bytes] = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Only keep frames according to temporal downsampling rule.
        if frame_idx % keep_every_n != 0:
            frame_idx += 1
            continue

        # Optional downscale to reduce memory / VLM load.
        if max_width is not None:
            h, w = frame.shape[:2]
            if w > max_width:
                scale = max_width / float(w)
                new_w = int(w * scale)
                new_h = int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h))

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            print(f"[WARN] Failed to encode frame {frame_idx}, skipping")
            frame_idx += 1
            continue

        frames.append(buffer.tobytes())
        frame_idx += 1

    cap.release()

    if not frames:
        raise RuntimeError(f"No frames decoded from video: {video_path}")

    print(f"[INFO] Loaded {len(frames)} frames from {video_path}")
    return frames
