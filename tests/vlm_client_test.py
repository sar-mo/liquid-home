from openai import OpenAI
import base64
import glob
import os

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)

# List of image paths
image_paths = [
    "/Users/sarthakmohanty/liquid-home/data/test_data/cat.jpg",
]

# Build message content entries for each image
contents = []

for path in image_paths:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    contents.append({
        "type": "image_url",
        "image_url": {
            "url": f"data:image/jpeg;base64,{b64}"
        }
    })

# Add the final text question AFTER all images
contents.append({
    "type": "text",
    "text": "Describe in detail what is happening across these images. Summarize the sequence."
})

# Send request
response = client.chat.completions.create(
    model="lfm2-vl-450m-f16",
    messages=[
        {
            "role": "user",
            "content": contents
        }
    ],
    max_tokens=512,  # a bit more room for multi-frame reasoning
)

print(response.choices[0].message.content)