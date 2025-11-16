# Liquid Home – Vision-based Home Automation Demo

This repo is a small end-to-end demo of **vision-based home automation** using a
Liquid AI vision-language model (VLM) running via `llama.cpp` / `llama-server`.

- **Backend**: Python pipeline that:
  - Reads an MP4 from `data/<video-name>.mp4`
  - Downsamples the video to a fixed number of frames per second
  - Slides a fixed-size window over the frames
  - Sends each window to a VLM
  - Applies user-defined `IF <condition> THEN <action>` rules (from JSON)
- **Frontend**: A simple JS/Three.js UI that:
  - Shows a **live webcam feed** (MacBook camera)
  - Lets the user define up to **5 rules** in an `IF / THEN` format
  - Renders a **3D sample room** (lights + curtains) with Three.js
  - Executes actions like `turn lights on/off`, `open/close curtains` in the scene

---

## Project layout

(Not fully up-to-date)

```text
.
├── data
│   ├── context
│   │   └── automation_rules.json        # actions + IF/THEN rules JSON
│   ├── test_data
│   │   └── cat.jpg
│   ├── video
│   └── video.mp4                        # sample video (you can replace this)
├── frontend
│   ├── index.html                       # dashboard + Three.js room UI
│   ├── styles.css                       # styling
│   └── app.js                           # webcam, rules UI, Three.js scene
├── models
│   └── lfm2-vl-450m-f16
│       ├── LFM2-VL-450M-F16.gguf
│       └── mmproj-LFM2-VL-450M-F16.gguf
├── src
│   ├── api
│   │   └── server.py                    # (placeholder for future HTTP API)
│   ├── ingestion
│   │   ├── frame_store.py               # ffmpeg frame extraction (optional)
│   │   └── video_stream.py              # loads & downsamples frames from MP4
│   ├── models
│   │   ├── text_client.py
│   │   └── vlm_client.py                # VLM client + rule-aware decision helper
│   ├── pipeline
│   │   ├── frame_analyzer.py            # frame windows + automation decisions
│   │   └── frame_context.py             # AutomationConfig + JSON helpers
│   └── utils
│       ├── json_utils.py
│       └── paths.py
├── main.py                              # main entrypoint for backend demo
├── pyproject.toml
├── uv.lock
└── README.md
```

## Running full pipeline


First, set some env variables. should work in zsh + bash

```
MODEL_NAME="LFM2-VL-450M-F16"
MODEL_REPO="LiquidAI/LFM2-VL-450M-GGUF"

MODEL_DIR="models/$(echo "$MODEL_NAME" | tr '[:upper:]' '[:lower:]')"

GGUF_FILE="${MODEL_NAME}.gguf"
MM_PROJ_FILE="mmproj-${MODEL_NAME}.gguf"

echo "$MODEL_DIR"
```

### Download models

```
uvx hf download \
  $MODEL_REPO \
  $GGUF_FILE \
  $MM_PROJ_FILE \
  --local-dir $MODEL_DIR
```
Should automatically put the GGUF + projector into your chosen model directory.

### To start the llama server: 



Option A — Run directly from HuggingFace (no local models)
```
llama-server \
  -hf $MODEL_REPO:$MODEL_NAME \
  -c 16384 \
  --n-gpu-layers 50 \
  --threads 8 \
  --port 8080 \
  --host 0.0.0.0
```

Option B (Preferred) — Run using locally downloaded GGUF + projector
```
llama-server \
  -m $MODEL_DIR/$GGUF_FILE \
  --mmproj $MODEL_DIR/$MM_PROJ_FILE \
  -c 16384 \
  --n-gpu-layers 50 \
  --threads 8 \
  --port 8080 \
  --host 0.0.0.0
```

### Run the frontend (webcam + Three.js room) and backend streaming pipeline

From the repo root:

```
uv run -m src.api.server \
  --num-frames-per-second 2 \
  --num-frames-in-sliding-window 4 \
  --sliding-window-frame-step-size 4 \
  --rules-json data/context/automation_rules.json \
  --base-url "http://localhost:8080/v1" \
  --model "$MODEL_NAME"
```

Then open: http://localhost:8000/


You’ll see:

Left side:

- Live webcam feed
- Rule Editor (up to 5 rules): IF <natural language> THEN <predefined action>

Right side:
- Three.js 3D room with:
    - Ceiling lights (binary ON/OFF)
    - Window with curtains (binary OPEN/CLOSED)
- Test buttons for manual action simulation
- Real-time updates when VLM-triggered rules fire.

