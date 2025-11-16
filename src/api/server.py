#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import threading
import time
from collections import deque
from pathlib import Path
from queue import Queue, Empty, Full
from typing import Iterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.pipeline.frame_analyzer import WindowResult
from src.pipeline.frame_context import load_automation_config
from src.models.vlm_client import choose_actions_for_frames

# Global queue where the frontend pushes live webcam frames (JPEG bytes).
LIVE_FRAME_QUEUE: "Queue[bytes]" = Queue(maxsize=256)


def build_arg_parser() -> argparse.ArgumentParser:
    # ... (this function remains the same)
    parser = argparse.ArgumentParser(
        description="Liquid Home: serve frontend + stream live video into VLM."
    )
    parser.add_argument(
        "--video-name",
        default="video",
        help="(Currently unused for live mode) Base name of MP4 under data/.",
    )
    parser.add_argument(
        "--num-frames-per-second",
        type=float,
        default=2.0,
        help="Expected frame rate of incoming live frames after downsampling.",
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
        help="Path to JSON containing 'actions' and 'rules'.",
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
        "--host",
        default="0.0.0.0",
        help="Host for the web server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the web server.",
    )
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="(Ignored for live mode, kept for compatibility).",
    )
    return parser


def create_app(args: argparse.Namespace) -> FastAPI:
    app = FastAPI()

    # --- Frontend mounting ---
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"

    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_dir), html=False),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        index_path = frontend_dir / "index.html"
        return index_path.read_text(encoding="utf-8")

    # --- Automation config (rules + actions) ---
    rules_path = Path(args.rules_json).expanduser().resolve()
    config = load_automation_config(rules_path)

    # === Live frame ingestion endpoint (YOUR CORRECTED VERSION) =============
    
    @app.post("/api/live_frame")
    async def live_frame(request: Request) -> JSONResponse:
        """
        Accepts a JSON payload with a base64 image, decodes it, and pushes
        it to a queue for processing. This uses manual parsing for robustness.
        """
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            print("[ERROR] /api/live_frame: Received invalid JSON.")
            return JSONResponse(status_code=400, content={"message": "Invalid JSON payload."})

        image_data = payload.get("image_base64")
        if not isinstance(image_data, str):
            return JSONResponse(status_code=400, content={"message": "Missing 'image_base64' string in payload."})

        if "," in image_data:
            try:
                # Strip the "data:image/jpeg;base64," prefix
                image_data = image_data.split(",", 1)[1]
            except IndexError:
                 return JSONResponse(status_code=400, content={"message": "Malformed data URL."})


        try:
            img_bytes = base64.b64decode(image_data)
        except (ValueError, TypeError):
            return JSONResponse(status_code=400, content={"message": "Invalid base64 data."})

        try:
            LIVE_FRAME_QUEUE.put_nowait(img_bytes)
        except Full:
            print("[WARN] /api/live_frame: Frame queue is full. Dropping frame.")
            return JSONResponse(status_code=503, content={"status": "queue_full"})

        return JSONResponse(content={"status": "ok"})


    # === SSE endpoint reading from LIVE_FRAME_QUEUE =========================

    @app.get("/api/stream")
    def stream() -> StreamingResponse:
        # ... (this function remains the same as your corrected version)
        q: "Queue[WindowResult | None]" = Queue()

        def worker() -> None:
            window_index = 0
            fps = float(args.num_frames_per_second) if args.num_frames_per_second > 0 else 2.0
            seconds_per_frame = 1.0 / fps

            window_size = args.num_frames_in_sliding_window
            step = args.sliding_window_frame_step_size

            buffer: "deque[bytes]" = deque()
            frames_seen = 0

            print(
                f"[LIVE] Starting live VLM stream with window_size={window_size}, "
                f"step={step}, fps={fps}"
            )

            while True:
                try:
                    frame_bytes = LIVE_FRAME_QUEUE.get(timeout=10.0)
                except Empty:
                    print("[LIVE] No frames received for 10s, ending stream.")
                    break

                buffer.append(frame_bytes)
                frames_seen += 1

                while len(buffer) >= window_size:
                    window_frames = list(buffer)[:window_size]

                    start_index = frames_seen - len(buffer)
                    t_start_sec = start_index * seconds_per_frame
                    t_end_sec = (start_index + window_size) * seconds_per_frame

                    try:
                        t0 = time.time()
                        decision = choose_actions_for_frames(
                            images=window_frames,
                            config=config,
                            start_s=t_start_sec,
                            end_s=t_end_sec,
                            model=args.model,
                            base_url=args.base_url,
                        )
                        elapsed = time.time() - t0
                    except Exception as e:
                        print(f"[ERROR] VLM call failed on live window {window_index}: {e}")
                        q.put(None)
                        return

                    result = WindowResult(
                        window_index=window_index,
                        t_start_sec=t_start_sec,
                        t_end_sec=t_end_sec,
                        description=(
                            decision.get("description")
                            or decision.get("reasoning")
                            or "No description from model."
                        ),
                        delay_seconds=elapsed,
                        triggered_action_ids=list(decision.get("triggered_action_ids", [])),
                        triggered_rule_ids=list(decision.get("triggered_rule_ids", [])),
                    )
                    
                    print(f"[LIVE WINDOW {result.window_index}] t={result.t_start_sec:.2f}s, actions={result.triggered_action_ids}")

                    q.put(result)
                    window_index += 1

                    for _ in range(step):
                        if buffer:
                            buffer.popleft()
                        else:
                            break
            q.put(None)

        threading.Thread(target=worker, daemon=True).start()

        def event_stream() -> Iterator[bytes]:
            while True:
                item = q.get()
                if item is None:
                    break
                payload = {
                    "window_index": item.window_index,
                    "t_start_sec": item.t_start_sec,
                    "t_end_sec": item.t_end_sec,
                    "description": item.description,
                    "delay_seconds": item.delay_seconds,
                    "triggered_action_ids": item.triggered_action_ids,
                    "triggered_rule_ids": item.triggered_rule_ids,
                }
                yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    app = create_app(args)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()