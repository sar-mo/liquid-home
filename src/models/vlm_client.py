#!/usr/bin/env python

from typing import List
import base64

from openai import OpenAI


def get_vlm_client(base_url: str = "http://localhost:8080/v1") -> OpenAI:
    """
    Return an OpenAI-compatible client pointing to llama-server.
    """
    return OpenAI(
        base_url=base_url,
        api_key="not-needed",
    )


def describe_image_bytes_batch(
    images: List[bytes],
    start_s: float,
    end_s: float,
    model: str = "lfm2-vl-450m-f16",
    base_url: str = "http://localhost:8080/v1",
    max_tokens: int = 512,
) -> str:
    """
    Given a list of JPEG-encoded image bytes and the time range they span,
    call the VLM and return the textual description.
    """
    client = get_vlm_client(base_url)

    contents = []
    for data in images:
        b64 = base64.b64encode(data).decode("utf-8")
        contents.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                },
            }
        )

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
