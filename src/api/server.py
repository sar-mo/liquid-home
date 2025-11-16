#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from queue import Queue, Empty, Full
from typing import Iterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.models.scene_detector import HomeAutomationActionDetector
from src.pipeline.frame_analyzer import WindowResult
from src.pipeline.frame_context import (
    load_automation_config,
    ConditionActionRule,
)
from src.models.vlm_client import (
    describe_image_bytes_batch,
    evaluate_rules_from_summary,
)

# Global queue where the frontend pushes live webcam frames (JPEG bytes).
LIVE_FRAME_QUEUE: "Queue[bytes]" = Queue(maxsize=256)


def build_arg_parser() -> argparse.ArgumentParser:
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
        help="Vision model name exposed by llama-server.",
    )
    parser.add_argument(
        "--policy-model",
        default=None,
        help="Text-only policy model for rule evaluation (defaults to --model).",
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


def create_app(args: argparse.Namespace, detector) -> FastAPI:
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

    # Helper for serializing current config to JSON-serializable dict
    def config_to_dict() -> dict:
        return {
            "actions": [
                {
                    "id": a.id,
                    "label": a.label,
                    "description": a.description,
                }
                for a in config.actions
            ],
            "rules": [
                {
                    "id": r.id,
                    "condition_text": r.condition_text,
                    "action_id": r.action_id,
                }
                for r in config.rules
            ],
        }

    # ===== Config API: frontend <-> backend sync for rules + actions =====

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        """
        Return the current automation config (actions + rules).
        Frontend uses this to populate dropdown + rules list.
        """
        return JSONResponse(content=config_to_dict())

    @app.post("/api/config/rules")
    async def create_rule(request: Request) -> JSONResponse:
        """
        Add a new rule. Body:
        {
          "condition_text": "...",
          "action_id": "turn_lights_on"
        }
        """
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"message": "Invalid JSON payload."},
            )

        condition_text = payload.get("condition_text")
        action_id = payload.get("action_id")

        if not isinstance(condition_text, str) or not condition_text.strip():
            return JSONResponse(
                status_code=400,
                content={"message": "condition_text must be a non-empty string."},
            )
        if not isinstance(action_id, str) or not action_id.strip():
            return JSONResponse(
                status_code=400,
                content={"message": "action_id must be a non-empty string."},
            )

        # Ensure the action_id exists in the current actions list
        if not any(a.id == action_id for a in config.actions):
            return JSONResponse(
                status_code=400,
                content={"message": f"Unknown action_id '{action_id}'."},
            )

        rule_id = f"rule-{uuid.uuid4().hex[:8]}"
        new_rule = ConditionActionRule(
            id=rule_id,
            condition_text=condition_text.strip(),
            action_id=action_id.strip(),
        )
        config.rules.append(new_rule)

        return JSONResponse(
            status_code=201,
            content={
                "id": new_rule.id,
                "condition_text": new_rule.condition_text,
                "action_id": new_rule.action_id,
            },
        )

    @app.delete("/api/config/rules/{rule_id}")
    async def delete_rule(rule_id: str) -> JSONResponse:
        """
        Delete a rule by ID.
        """
        before = len(config.rules)
        config.rules = [r for r in config.rules if r.id != rule_id]
        after = len(config.rules)

        if before == after:
            return JSONResponse(
                status_code=404,
                content={"message": f"No rule found with id '{rule_id}'."},
            )

        return JSONResponse(content={"status": "deleted", "rule_id": rule_id})

    # === Live frame ingestion endpoint =====================================

    @app.post("/api/live_frame")
    async def live_frame(request: Request) -> JSONResponse:
        """
        Accepts a JSON payload with a base64 image, decodes it, and pushes
        it to a queue for processing.
        """
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            print("[ERROR] /api/live_frame: Received invalid JSON.")
            return JSONResponse(
                status_code=400,
                content={"message": "Invalid JSON payload."},
            )

        image_data = payload.get("image_base64")
        if not isinstance(image_data, str):
            return JSONResponse(
                status_code=400,
                content={"message": "Missing 'image_base64' string in payload."},
            )

        # Strip "data:image/jpeg;base64," prefix if present
        if "," in image_data:
            try:
                image_data = image_data.split(",", 1)[1]
            except IndexError:
                return JSONResponse(
                    status_code=400,
                    content={"message": "Malformed data URL."},
                )

        try:
            img_bytes = base64.b64decode(image_data)
        except (ValueError, TypeError):
            return JSONResponse(
                status_code=400,
                content={"message": "Invalid base64 data."},
            )

        try:
            LIVE_FRAME_QUEUE.put_nowait(img_bytes)
        except Full:
            print("[WARN] /api/live_frame: Frame queue is full. Dropping frame.")
            return JSONResponse(
                status_code=503,
                content={"status": "queue_full"},
            )

        return JSONResponse(content={"status": "ok"})

    # === SSE endpoint reading from LIVE_FRAME_QUEUE =========================

    @app.get("/api/stream")
    def stream() -> StreamingResponse:
        """
        Server-Sent Events endpoint:
        - Reads frames from LIVE_FRAME_QUEUE
        - Groups into sliding windows
        - For each window:
            1) VLM summarization (vision-only)
            2) Text-only rule evaluation
            3) Local rule→action mapping
        - Emits WindowResult as SSE JSON.
        """
        q: "Queue[WindowResult | None]" = Queue()

        def worker() -> None:
            window_index = 0
            fps = float(args.num_frames_per_second) if args.num_frames_per_second > 0 else 2.0
            seconds_per_frame = 1.0 / fps

            window_size = args.num_frames_in_sliding_window
            step = args.sliding_window_frame_step_size

            buffer: "deque[bytes]" = deque()
            frames_seen = 0

            policy_model_name = args.policy_model or args.model

            print(
                f"[LIVE] Starting live VLM stream with window_size={window_size}, "
                f"step={step}, fps={fps}"
            )
            print(f"[LIVE] Vision model  = {args.model} @ {args.base_url}")
            print(f"[LIVE] Policy model  = {policy_model_name} @ {args.base_url}")
            print(f"[LIVE] Current rules = {len(config.rules)}")

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

                        # 1) Vision-only summary
                        summary = describe_image_bytes_batch(
                            images=window_frames,
                            start_s=t_start_sec,
                            end_s=t_end_sec,
                            model=args.model,
                            base_url=args.base_url,
                        )

                        print(summary)

                        # 2) Rule evaluation (text-only model)
                        if config.rules:

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

                            room = "bedroom"

                            print("------- HERE -----------")

                            decision = detector.process_video_summary(summary, config)

                            # decision = evaluate_rules_from_summary(
                            #     summary=summary,
                            #     config=config,
                            #     model=policy_model_name,
                            #     base_url=args.base_url,
                            # )
                            print(decision)
                        else:
                            decision = {
                                "triggered_rule_ids": [],
                                "reasoning": "No rules configured.",
                                "raw_text": "",
                            }

                        elapsed = time.time() - t0

                    except Exception as e:
                        print(f"[ERROR] Model call failed on live window {window_index}: {e}")
                        q.put(None)
                        return

                    triggered_rules = decision.get("triggered_rule_ids", []) or []

                    # 3) Local mapping rule_id -> action_id
                    rules_by_id = config.rules_by_id()
                    triggered_action_ids: list[str] = []
                    seen_actions: set[str] = set()
                    for rule_id in triggered_rules:
                        rule = rules_by_id.get(rule_id)
                        if rule is None:
                            continue
                        action_id = rule.action_id
                        if action_id not in seen_actions:
                            seen_actions.add(action_id)
                            triggered_action_ids.append(action_id)

                    result = WindowResult(
                        window_index=window_index,
                        t_start_sec=t_start_sec,
                        t_end_sec=t_end_sec,
                        description=summary,
                        delay_seconds=elapsed,
                        triggered_action_ids=list(triggered_action_ids),
                        triggered_rule_ids=list(triggered_rules),
                    )

                    print(
                        f"[LIVE WINDOW {result.window_index}] "
                        f"t={result.t_start_sec:.2f}s→{result.t_end_sec:.2f}s, "
                        f"rules={result.triggered_rule_ids}, "
                        f"actions={result.triggered_action_ids}"
                    )

                    q.put(result)
                    window_index += 1

                    # Slide window
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

    detector = HomeAutomationActionDetector(
        api_key="no-key-needed",
    )
    
    app = create_app(args, detector)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
