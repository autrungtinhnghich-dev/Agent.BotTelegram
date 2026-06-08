import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_url = "http://127.0.0.1:8045/v1/chat/completions"
api_key = os.getenv("LLM_API_KEY")
model = os.getenv("LLM_MODEL")

print(f"Testing custom LLM API on localhost...")
print(f"API URL: {api_url}")
print(f"API Key: {api_key[:10]}...{api_key[-5:] if api_key else ''}")
print(f"Model: {model}")

try:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Xin chào, bạn là ai? Hãy trả lời ngắn gọn trong 1 câu."},
        ]
    }
    response = requests.post(api_url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    print("\nCustom LLM Response:")
    print(response.json())
except Exception as e:
    print(f"\nError occurred: {e}")
