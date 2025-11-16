from openai import OpenAI
import base64
from typing import List


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

    contents.append(
        {
            "type": "text",
            "text": (
                "You are watching a short segment of a surveillance-style video. "
                f"This segment covers approximately {end_s - start_s:.1f} seconds "
                f"from time {start_s:.1f}s to {end_s:.1f}s in the video.\n\n"
                "Describe in detail what is happening across these images. "
                "Summarize the sequence over time, including any changes, "
                "movements, and interactions you observe."
            ),
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