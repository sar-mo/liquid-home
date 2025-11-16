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
        "Give a HIGH-LEVEL summary of the scene through images from the security cameras in bedroom; don't analyze small details."
        "Focus ONLY on big picture changes like suspicious activity, person entering etc"
        "Ignore minor details like exact poses, clothing, small objects, decorations or specific furniture."
        "More interested in operating devices, people etc"
        "Keep it to 1–2 sentences."
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
