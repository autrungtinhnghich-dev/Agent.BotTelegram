import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.summarizer import _call

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

def test_ai():
    print("Testing AI with new configuration...")
    system = "You are a helpful assistant."
    prompt = "Say hello in 3 different languages."
    
    try:
        response = _call(system, prompt)
        print("\nAI Response:")
        print("-" * 20)
        print(response)
        print("-" * 20)
        print("\nAI check successful!")
    except Exception as e:
        print(f"\nAI check failed: {e}")

if __name__ == "__main__":
    test_ai()
