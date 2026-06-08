import os
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

api_url = "http://127.0.0.1:8045/v1/chat/completions"
api_key = os.getenv("LLM_API_KEY")
model = os.getenv("LLM_MODEL")

# A tiny 1x1 PNG image in base64
tiny_image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

print(f"Testing multimodal support on local LLM API...")
print(f"API URL: {api_url}")
print(f"Model: {model}")

try:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Đây là ảnh gì? Trả lời ngắn gọn bằng tiếng Việt."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{tiny_image_b64}"
                        }
                    }
                ]
            }
        ]
    }
    response = requests.post(api_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    print("\nCustom LLM Multimodal Response:")
    print(response.json())
except Exception as e:
    print(f"\nError occurred: {e}")
