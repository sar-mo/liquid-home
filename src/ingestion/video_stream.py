from pathlib import Path
from typing import List, Optional

import cv2


def load_video_frames_bytes(
    video_name: str,
    max_width: Optional[int] = 640,
) -> List[bytes]:
    """
    Load an MP4 from data/test_data/{video_name}.mp4 and return a list of
    JPEG-encoded frames as bytes.

    - Optionally downscales frames so their width <= max_width.
    - Prints the actual FPS of the video for debugging.
    """
    root = Path(__file__).resolve().parents[2]  # repo root
    video_path = root / "data" / "test_data" / f"{video_name}.mp4"

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"[INFO] Video file {video_path} reports FPS ≈ {actual_fps:.2f}")

    frames: List[bytes] = []
    idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Optional downscale to reduce memory / VLM load
        if max_width is not None:
            h, w = frame.shape[:2]
            if w > max_width:
                scale = max_width / float(w)
                new_w = int(w * scale)
                new_h = int(h * scale)
                frame = cv2.resize(frame, (new_w, new_h))

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            print(f"[WARN] Failed to encode frame {idx}, skipping")
            idx += 1
            continue

        frames.append(buffer.tobytes())
        idx += 1

    cap.release()

    if not frames:
        raise RuntimeError(f"No frames decoded from video: {video_path}")

    print(f"[INFO] Loaded {len(frames)} frames from {video_path}")
    return frames