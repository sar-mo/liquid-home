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


### To start the llama server: 

- To run without downloading the models locally:


```
llama-server \
  -hf LiquidAI/LFM2-VL-450M-GGUF:F16 \
  -c 16384 \
  --n-gpu-layers 50 \
  --threads 8 \
  --port 8080 \
  --host 0.0.0.0
```

- If you’ve downloaded the GGUF + projector into models/lfm2-vl-450m-f16/, you can do:
```
llama-server \
  -m models/lfm2-vl-450m-f16/LFM2-VL-450M-F16.gguf \
  --mmproj models/lfm2-vl-450m-f16/mmproj-LFM2-VL-450M-F16.gguf \
  -c 16384 \
  --n-gpu-layers 50 \
  --threads 8 \
  --port 8080 \
  --host 0.0.0.0
```

### Run the frontend (webcam + Three.js room) and backend streaming pipeline

From the repo root:

```
uv run -m src.api.server 
  --num-frames-per-second 2 \
  --num-frames-in-sliding-window 4 \
  --sliding-window-frame-step-size 4 \
  --rules-json data/context/automation_rules.json \
  --base-url "http://localhost:8080/v1" \
  --model "lfm2-vl-3b-f16"
```

Then open:

http://localhost:8000/


You’ll see:

Left side:

- Live webcam feed from your MacBook camera
- UI to create up to 5 rules: IF <natural language> THEN <predefined action>

Right side (Three.js):
- 3D room with:
    - Ceiling lights (binary ON/OFF)
    - Window with curtains (binary OPEN/CLOSED)
- Test buttons that simulate actions:
    - Turn lights on/off
    - Open/close curtains
- Rule items each have a “Run” button that simulates that rule firing

Currently, the frontend actions are local (they call executeAction(actionId, source) in app.js).
WIP to wire this to your Python backend (e.g., /api/evaluate) to let the VLM drive the same actions.


### How to download

- To download a new model


Example


```
uvx hf download \
  LiquidAI/LFM2-VL-3B-GGUF \
  LFM2-VL-3B-F16.gguf \
  mmproj-LFM2-VL-3B-F16.gguf \
  --local-dir models/lfm2-vl-3b-f16
```


## TODOs


0. Connect the frontend and backend:


The rules are not being listed on the frontend. 
  
  
Furthermore, the modle is not directly outputting actions that affect the smart home.
1. Improve model quality
- try to utilize workbench.liquid.ai, maybe some sort of long-form summarization using a TtT model
2. Improve the frontend
- improve the threejs room look


3. Write a presentation
- Draw model architecture
- Give some context on why this is a good business decision
- Give some context on why this is perfect for LFMs and SSMs
- Demo
- Conclude for future directions