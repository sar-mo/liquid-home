# src/video_intel/models/vlm_client.py
from typing import Any, Dict, List
from PIL import Image
import torch
from transformers import AutoModelForCausalLM, AutoProcessor

DEFAULT_VLM_MODEL_ID = "LiquidAI/LFM2-VL-1.6B"

class VLMClient:
    def __init__(self, model_id: str = DEFAULT_VLM_MODEL_ID):
        self.model_id = model_id
        self.model, self.processor = self._load_model(model_id)

    def _load_model(self, model_id: str):
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            device_map="auto",
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        )
        processor = AutoProcessor.from_pretrained(model_id)
        return model, processor

    def analyze_frame_pair(
        self,
        previous_image: Image.Image,
        current_image: Image.Image,
        semantic_context: str,
        max_new_tokens: int = 256,
    ) -> str:
        prompt_text = f"""...same JSON instruction text as before..."""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "image"},
                    {"type": "text", "text": prompt_text.strip()},
                ],
            }
        ]

        prompt = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self.processor(
            images=[previous_image, current_image],
            text=prompt,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            output = self.model.generate(**inputs, max_new_tokens=max_new_tokens)

        return self.processor.batch_decode(output, skip_special_tokens=True)[0]