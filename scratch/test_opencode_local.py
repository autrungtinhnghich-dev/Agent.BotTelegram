import asyncio
import os
import sys

# Thêm đường dẫn gốc để import được services/config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from services.opencode_service import OpenCodeService

async def main():
    print("--- BẮT ĐẦU KIỂM THỬ KẾT NỐI OPENCODE LOCAL ---")
    url = config.OPENCODE_LOCAL_URL
    print(f"Địa chỉ cấu hình: {url}")
    print(f"Cấu hình USE_LOCAL_OPENCODE: {config.USE_LOCAL_OPENCODE}")
    
    service = OpenCodeService(url)
    
    print("\n1. Đang tạo session mới...")
    session_id = await service.create_session("Test script session")
    if not session_id:
        print("❌ Lỗi: Không thể tạo session. Đảm bảo bạn đã chạy 'opencode serve' ở cổng 4096.")
        return
        
    print(f"✅ Tạo session thành công. Session ID: {session_id}")
    
    print("\n2. Đang gửi câu hỏi test...")
    prompt = "Say hello in 3 words"
    print(f"Prompt: {prompt}")
    
    response_text = ""
    async for chunk in service.send_message_stream(session_id, prompt):
        print(chunk, end="", flush=True)
        response_text += chunk
        
    print("\n\n3. Lấy lại toàn bộ lịch sử tin nhắn trong session để kiểm tra...")
    messages = await service.get_session_messages(session_id)
    print(f"Số lượng tin nhắn trả về: {len(messages)}")
    for i, msg in enumerate(messages):
        info = msg.get("info", {})
        role = info.get("role", "unknown")
        print(f"  Tin nhắn {i+1} [Role: {role}]:")
        for part in msg.get("parts", []):
            if part.get("type") == "text":
                print(f"    - Content: {part.get('text', '')}")
                
    print("\n--- HOÀN TẤT KIỂM THỬ ---")

if __name__ == "__main__":
    asyncio.run(main())
