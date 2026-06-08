import os
import asyncio
from PIL import Image, ImageDraw
from dotenv import load_dotenv

# Load env before any imports
load_dotenv()

# We need to change LLM_API_URL locally if it contains host.docker.internal
api_url = os.getenv("LLM_API_URL")
if api_url and "host.docker.internal" in api_url:
    local_url = api_url.replace("host.docker.internal", "127.0.0.1")
    os.environ["LLM_API_URL"] = local_url
    print(f"Substituted LLM_API_URL to: {local_url}")

from services.brain_service import process_image_file, ask_brain
from services.journal_db import init_db

async def main():
    # 1. Initialize Database
    await init_db()
    
    # 2. Create a test image with text
    image_path = "scratch/test_brain_image.png"
    print("\nCreating test image with text...")
    
    # Create blank white image
    img = Image.new("RGB", (650, 300), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    
    # Draw simple lines of text
    text_content = [
        "GHI CHU BAO MAT HE THONG",
        "Ma PIN cua server kiem thu la: 9876-1234",
        "Du an su dung Python RAG va sqlite.",
        "Ngay cap nhat: 2026-05-19"
    ]
    
    y = 30
    for line in text_content:
        d.text((40, y), line, fill=(0, 0, 0))
        y += 50
        
    img.save(image_path)
    print(f"Test image saved to {image_path}")
    
    # 3. Process the image file (Extract and Save to Brain)
    user_id = 722793625  # A sample allowed user_id
    print("\nRunning process_image_file...")
    count = await process_image_file(user_id, image_path, "test_brain_image.png")
    print(f"process_image_file result count: {count}")
    
    if count > 0:
        print("✅ Successfully analyzed image and stored knowledge blocks!")
    else:
        print("❌ Failed to store knowledge blocks.")
        return
        
    # 4. Search and retrieve from Brain
    print("\nTesting ask_brain query to see if it remembers the image content...")
    question = "Mã PIN của server kiểm thử là bao nhiêu?"
    print(f"Question: {question}")
    
    answer = await ask_brain(user_id, question)
    print("\nAnswer from Brain:")
    print(answer)
    
    if "9876-1234" in answer:
        print("\n🎉 SUCCESS: The brain remembers the text content extracted from the image!")
    else:
        print("\n❌ FAILURE: The brain could not answer based on the image content.")

    # Cleanup temp test image
    if os.path.exists(image_path):
        os.remove(image_path)
        print("\nCleaned up test image.")

if __name__ == "__main__":
    asyncio.run(main())
