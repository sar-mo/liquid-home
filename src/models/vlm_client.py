#!/usr/bin/env python

from __future__ import annotations

from typing import List, Dict, Any
import base64
import json

from openai import OpenAI

from src.pipeline.frame_context import AutomationConfig, automation_config_to_json_blob


def get_vlm_client(base_url: str = "http://localhost:8080/v1") -> OpenAI:
    """
    Return an OpenAI-compatible client pointing to llama-server.
    """
    return OpenAI(
        base_url=base_url,
        api_key="not-needed",
    )


def _images_to_content_blocks(images: List[bytes]) -> List[Dict[str, Any]]:
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
    max_tokens: int = 512,
) -> str:
    """
    Simple helper: summarize what changed in this segment, without
    considering home-automation rules. Useful for debugging.
    """
    client = get_vlm_client(base_url)

    contents = _images_to_content_blocks(images)

    summary_prompt = (
        "You are a home automation vision system. "
        f"These frames come from a video segment between {start_s:.2f}s and {end_s:.2f}s. "
        "Give a HIGH-LEVEL summary of what changed over this segment; don't analyze small details. "
        "Focus ONLY on big picture changes, for example:\n"
        "- Did someone enter or leave?\n"
        "- Is something unusual?\n"
        "- Did a door open or close?\n"
        "Ignore minor details like exact poses, clothing, small objects, or specific furniture. "
        "If nothing significant changed, just say 'No major changes'. "
        "Keep it to 1–2 sentences. Your output controls home automation—only report what matters."
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

    return resp.choices[0].message.content


def choose_actions_for_frames(
    images: List[bytes],
    config: AutomationConfig,
    start_s: float,
    end_s: float,
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    max_tokens: int = 512,
) -> Dict[str, Any]:
    """
    Given a list of JPEG-encoded image bytes and an AutomationConfig
    (actions + condition->action rules), ask the VLM which actions
    should fire for this time window.

    Returns a dictionary of the form:

    {
      "triggered_action_ids": [...],
      "triggered_rule_ids": [...],
      "reasoning": "...",
      "raw_text": "..."   # always included, even if JSON parsing fails
    }
    """
    client = get_vlm_client(base_url)

    contents = _images_to_content_blocks(images)

    rules_json = automation_config_to_json_blob(config)

    control_prompt = (
        "You are a home automation decision engine that can only decide which predefined "
        "actions to trigger. You will be given:\n\n"
        "1. A JSON object describing available actions and user-defined condition->action rules.\n"
        "2. A short video segment represented as multiple frames.\n\n"
        "Each rule has:\n"
        "- an 'id'\n"
        "- a natural language 'condition_text' describing when it should fire\n"
        "- an 'action_id' referring to one of the actions\n\n"
        "Your job is to look at the frames, understand what is happening between the start "
        "and end times, and then decide which rules' conditions are currently satisfied.\n\n"
        "IMPORTANT:\n"
        "- Only trigger actions whose conditions clearly match what you see.\n"
        "- If you are not confident a condition is met, do NOT trigger that rule.\n"
        "- Some rules may share the same action_id; if multiple rules fire, the action still "
        "only appears once in the actions list.\n\n"
        "Return ONLY a valid JSON object with the following fields:\n"
        "{\n"
        "  \"triggered_action_ids\": [\"action_id_1\", \"action_id_2\", ...],\n"
        "  \"triggered_rule_ids\": [\"rule_id_1\", \"rule_id_2\", ...],\n"
        "  \"reasoning\": \"Short natural language explanation of why you chose those actions.\"\n"
        "}\n\n"
        "Do not include any markdown, backticks, or extra commentary outside the JSON."
    )

    rules_block = (
        f"Video time range: {start_s:.2f}s to {end_s:.2f}s.\n\n"
        f"Automation configuration JSON:\n{rules_json}"
    )

    contents.append({"type": "text", "text": control_prompt})
    contents.append({"type": "text", "text": rules_block})

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

    raw_text = resp.choices[0].message.content or ""

    result: Dict[str, Any] = {
        "triggered_action_ids": [],
        "triggered_rule_ids": [],
        "reasoning": "",
        "raw_text": raw_text,
    }

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            for key in ("triggered_action_ids", "triggered_rule_ids", "reasoning"):
                if key in parsed:
                    result[key] = parsed[key]
    except Exception:
        # Leave result with empty lists / reasoning, but keep raw_text
        pass

    # Normalize lists to lists of strings
    for key in ("triggered_action_ids", "triggered_rule_ids"):
        value = result.get(key, [])
        if not isinstance(value, list):
            result[key] = []
        else:
            result[key] = [str(x) for x in value]

    if not isinstance(result.get("reasoning"), str):
        result["reasoning"] = str(result.get("reasoning", ""))

    return result
