import httpx
import json
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

class OpenCodeService:
    def __init__(self, base_url: str = "http://localhost:4096"):
        self.base_url = base_url.rstrip("/")

    async def create_session(self, title: str) -> Optional[str]:
        """Tạo một phiên làm việc mới trên OpenCode."""
        url = f"{self.base_url}/session"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"title": title}, timeout=15.0)
                response.raise_for_status()
                data = response.json()
                session_id = data.get("id")
                logger.info(f"Đã tạo OpenCode session mới: {session_id}")
                return session_id
            except Exception as e:
                logger.error(f"Lỗi khi tạo session trên OpenCode: {e}")
                return None

    async def get_session_messages(self, session_id: str) -> list:
        """Lấy danh sách tin nhắn trong một session."""
        url = f"{self.base_url}/session/{session_id}/message"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=15.0)
                response.raise_for_status()
                return response.json()  # Trả về Array<{ info: Message, parts: Part[] }>
            except Exception as e:
                logger.error(f"Lỗi khi lấy tin nhắn của session {session_id}: {e}")
                return []

    async def send_message_stream(self, session_id: str, prompt: str) -> AsyncGenerator[str, None]:
        """
        Gửi yêu cầu tới session và stream kết quả trả về từ OpenCode Server.
        Tự động fallback sang dạng blocking HTTP + polling nếu Server không stream.
        """
        url = f"{self.base_url}/session/{session_id}/message"
        
        # Gửi dữ liệu theo format chuẩn của OpenCode
        payload = {
            "text": prompt
        }
        
        logger.info(f"Đang gửi tin nhắn tới OpenCode session {session_id}: {prompt[:50]}...")
        
        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                # Gửi request với headers yêu cầu SSE
                headers = {"Accept": "text/event-stream"}
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    # Nếu server trả về 2xx và dùng event-stream
                    content_type = response.headers.get("content-type", "")
                    
                    if response.status_code == 200 and "text/event-stream" in content_type:
                        buffer = ""
                        async for chunk in response.aiter_text():
                            buffer += chunk
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if not line:
                                    continue
                                
                                # Xử lý SSE data
                                if line.startswith("data:"):
                                    data_str = line[5:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        event = json.loads(data_str)
                                        event_type = event.get("type")
                                        if event_type == "message.part.updated":
                                            properties = event.get("properties", {})
                                            part = properties.get("part", {})
                                            delta = properties.get("delta")
                                            if delta:
                                                yield delta
                                            elif part.get("type") == "text" and "text" in part:
                                                yield part.get("text", "")
                                        elif event_type == "message.updated":
                                            pass
                                    except Exception as je:
                                        logger.warning(f"Error parsing SSE event json: {je} for line: {line}")
                    else:
                        # Fallback: Chạy chế độ blocking và lấy tin nhắn cuối cùng của assistant
                        logger.info("Server không hỗ trợ text/event-stream, chạy chế độ blocking/polling...")
                        
                        # Đọc hết toàn bộ body của request POST ban đầu (vì nó block cho đến khi agent xong)
                        await response.aread()
                        
                        # Gọi API GET tin nhắn của session để lấy tin nhắn cuối cùng
                        messages = await self.get_session_messages(session_id)
                        if messages:
                            # Tìm tin nhắn assistant cuối cùng
                            assistant_text = ""
                            for msg in reversed(messages):
                                info = msg.get("info", {})
                                if info.get("role") == "assistant":
                                    parts = msg.get("parts", [])
                                    # Ghép các phần text lại
                                    for part in parts:
                                        if part.get("type") == "text":
                                            assistant_text += part.get("text", "")
                                    break
                            
                            if assistant_text:
                                yield assistant_text
                            else:
                                yield "⚠️ OpenCode Server phản hồi thành công nhưng không tìm thấy tin nhắn trả lời."
                        else:
                            yield "⚠️ Không thể tải tin nhắn phản hồi từ OpenCode Server."
                            
            except Exception as e:
                logger.error(f"Lỗi khi kết nối với OpenCode Server: {e}", exc_info=True)
                yield f"\n❌ Lỗi kết nối OpenCode Server: {str(e)}"
