from transformers import pipeline

# Load model
generator = pipeline("text-generation", "LiquidAI/LFM2-1.2B", device_map="auto")

# Generate
messages = [{"role": "user", "content": "What is machine learning?"}]
response = generator(messages, max_new_tokens=256)
print(response[0]["generated_text"][-1]["content"])