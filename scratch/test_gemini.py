import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model_name = "gemini-2.0-flash"

print(f"Testing Gemini SDK...")
print(f"API Key: {api_key[:10]}...{api_key[-5:] if api_key else ''}")
print(f"Model Name: {model_name}")

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content("Xin chào, bạn là ai? Hãy trả lời ngắn gọn trong 1 câu.")
    print("\nGemini Response:")
    print(response.text)
except Exception as e:
    print(f"\nError occurred: {e}")
