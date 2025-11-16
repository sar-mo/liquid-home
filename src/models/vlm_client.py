#!/usr/bin/env python

from __future__ import annotations

from typing import List, Dict, Any
import base64
import json

from openai import OpenAI

from src.pipeline.frame_context import AutomationConfig


def get_vlm_client(base_url: str = "http://localhost:8080/v1") -> OpenAI:
    """
    Return an OpenAI-compatible client pointing to llama-server (or any
    OpenAI-compatible endpoint). We use the same factory for both the
    vision model and the text-only policy model; which one you get is
    controlled by the `model` name you pass to `.chat.completions.create`.
    """
    return OpenAI(
        base_url=base_url,
        api_key="not-needed",
    )


def _images_to_content_blocks(images: List[bytes]) -> List[Dict[str, Any]]:
    """
    Convert raw JPEG bytes into OpenAI chat image_url content blocks.
    """
    blocks: List[Dict[str, Any]] = []
    for data in images:
        b64 = base64.b64encode(data).decode("utf-8")
        blocks.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                },
            }
        )
    return blocks


def describe_image_bytes_batch(
    images: List[bytes],
    start_s: float,
    end_s: float,
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    max_tokens: int = 256,
) -> str:
    """
    Use the *vision* model ONLY for semantic understanding / summarization.

    Given a list of JPEG-encoded frames covering [start_s, end_s], return a
    short natural-language summary of what *meaningfully* changed. No rules,
    no actions; this is intentionally "pure perception" to avoid polluting
    the VLM with home-automation specifics.
    """
    if not images:
        return "No frames available in this segment."

    client = get_vlm_client(base_url)

    contents: List[Dict[str, Any]] = _images_to_content_blocks(images)

    summary_prompt = (
        "You are a home automation *vision* system.\n"
        f"These frames come from a video segment between {start_s:.2f}s and {end_s:.2f}s.\n\n"
        "TASK:\n"
        "- Give a HIGH-LEVEL summary of what changed over this segment.\n"
        "- Focus ONLY on big picture changes, for example:\n"
        "  • Did someone enter or leave?\n"
        "  • Did a door or curtain open/close?\n"
        "  • Did the overall lighting change dramatically (bright vs dark)?\n"
        "- Ignore small details (exact pose, clothing, small objects, furniture arrangement).\n"
        "- If nothing significant changed, just say: 'No major changes.'\n"
        "- Keep it to 1–2 sentences.\n\n"
        "IMPORTANT: Do NOT suggest actions or automations. Only describe what you *see*."
    )

    contents.append(
        {
            "type": "text",
            "text": summary_prompt,
        }
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": contents,
            }
        ],
        max_tokens=max_tokens,
    )

    text = resp.choices[0].message.content
    return text if isinstance(text, str) and text.strip() else "No summary returned by model."


def evaluate_rules_from_summary(
    summary: str,
    config: AutomationConfig,
    model: str,
    base_url: str = "http://localhost:8080/v1",
    max_tokens: int = 512,
) -> Dict[str, Any]:
    """
    Given a natural-language `summary` of the scene (from the VLM) and an
    AutomationConfig containing rules, use a *text-only* model to decide
    which rules fire.

    CRITICAL: Only the rules are passed to the model (id + condition_text).
    The model never sees action IDs or action labels. We map rules→actions
    separately in Python.

    Returns:
        {
          "triggered_rule_ids": [...],
          "reasoning": "...",
          "raw_text": "..."   # always included, even if JSON parsing fails
        }
    """
    client = get_vlm_client(base_url)

    # Only expose rule IDs and condition text — no action IDs.
    rules_payload: Dict[str, Any] = {
        "rules": [
            {"id": r.id, "condition_text": r.condition_text}
            for r in config.rules
        ]
    }
    rules_json = json.dumps(rules_payload, ensure_ascii=False)

    control_prompt = (
        "You are a text-only home automation rule engine.\n\n"
        "You will be given:\n"
        "1. A short natural-language SUMMARY describing what is happening in the home.\n"
        "2. A JSON object listing user-defined rules. Each rule has:\n"
        "   - 'id': a unique identifier\n"
        "   - 'condition_text': when this rule should fire, in natural language.\n\n"
        "Your job is to decide which rules' conditions are clearly satisfied *right now*.\n\n"
        "Guidelines:\n"
        "- If you are NOT confident that a condition is satisfied, DO NOT trigger that rule.\n"
        "- Ignore any references to specific actions (lights, curtains, etc.) in the conditions;\n"
        "  your output is ONLY about which *rules* are active.\n"
        "- A rule is 'triggered' if the summary implies its condition is currently true.\n\n"
        "Return ONLY a valid JSON object with this exact shape:\n"
        "{\n"
        '  \"triggered_rule_ids\": [\"rule-id-1\", \"rule-id-2\", ...],\n'
        '  \"reasoning\": \"Short explanation of why those rules fired (or why none fired).\"\n'
        "}\n\n"
        "Do not include markdown, backticks, or any extra commentary outside the JSON."
    )

    user_block = (
        "SUMMARY:\n"
        f"{summary.strip() or 'No summary provided.'}\n\n"
        "RULES_JSON:\n"
        f"{rules_json}"
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": control_prompt},
                    {"type": "text", "text": user_block},
                ],
            }
        ],
        max_tokens=max_tokens,
    )

    raw_text = resp.choices[0].message.content or ""

    result: Dict[str, Any] = {
        "triggered_rule_ids": [],
        "reasoning": "",
        "raw_text": raw_text,
    }

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            # triggered_rule_ids
            trig = parsed.get("triggered_rule_ids", [])
            if isinstance(trig, list):
                result["triggered_rule_ids"] = [str(x) for x in trig]
            # reasoning
            if "reasoning" in parsed:
                result["reasoning"] = str(parsed["reasoning"])
    except Exception:
        # Leave defaults; raw_text is preserved for debugging.
        pass

    if not isinstance(result.get("reasoning"), str):
        result["reasoning"] = str(result.get("reasoning", ""))

    return result
