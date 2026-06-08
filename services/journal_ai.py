import logging
import json
import re
import asyncio
from services.summarizer import _call, _lang

logger = logging.getLogger(__name__)

async def analyze_journal_entry(question, answer):
    """
    Sử dụng VNPT LLM để phân tích nội dung nhật ký.
    Trả về: {sentiment, topics, score, reply}
    """
    system = (
        "Bạn là chuyên gia phân tích tâm lý và ngôn ngữ. "
        "Nhiệm vụ của bạn là phân tích một đoạn nhật ký ngắn của người dùng. "
        "Hãy trả về kết quả dưới định dạng JSON duy nhất, không giải thích gì thêm."
    )
    
    prompt = f"""
Phân tích nhật ký sau:
Câu hỏi đã hỏi: "{question}"
Câu trả lời của người dùng: "{answer}"

Hãy trả về định dạng JSON chính xác như sau:
{{
  "sentiment": "Tích cực | Trung tính | Tiêu cực",
  "score": -1.0 đến 1.0 (mức độ tích cực),
  "topics": ["tag1", "tag2"], (tối đa 3 tags phù hợp nhất như: công việc, sức khỏe, gia đình, học tập, niềm vui, áp lực, tiền bạc, mối quan hệ, ...)
  "reply": "1-2 câu phản hồi ấm áp, cá nhân hóa, khích lệ người dùng (tiếng Việt)"
}}

Lưu ý: Chỉ trả về JSON, không thêm văn bản khác.
"""
    
    try:
        # _call dùng requests (blocking), chạy trong thread để không block event loop
        logger.info(f"Đang gọi AI để phân tích entry: {answer[:50]}...")
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(None, _call, system, prompt)
        
        # Trích xuất JSON từ response (Xử lý cả trường hợp có text dư thừa hoặc markdown blocks)
        data = None
        decoder = json.JSONDecoder()
        # Thử tìm các khối JSON hợp lệ trong response
        for match in re.finditer(r'\{', response_text):
            start_pos = match.start()
            try:
                obj, _ = decoder.raw_decode(response_text[start_pos:])
                if isinstance(obj, dict) and all(k in obj for k in ["sentiment", "score", "topics", "reply"]):
                    data = obj
                    break
            except (json.JSONDecodeError, ValueError):
                continue

        if data:
            logger.info(f"Kết quả AI: {data.get('sentiment')}, tags: {data.get('topics')}")
            return data
        else:
            logger.error(f"Không tìm thấy JSON hợp lệ trong response AI: {response_text}")
            return None
            
    except Exception as e:
        logger.error(f"Lỗi khi phân tích AI: {e}")
        return None

async def generate_journal_summary(entries, period="tuần"):
    """
    Tổng hợp nhật ký theo tuần hoặc tháng.
    """
    if not entries:
        return "Không có dữ liệu để tổng hợp."
        
    entries_text = "\n".join([
        f"- Ngày {e['date']}: Q: {e['question']} | A: {e['answer']} | Sentiment: {e['sentiment']}"
        for e in entries
    ])
    
    system = f"Bạn là trợ lý tổng kết nhật ký cá nhân. {_lang()}"
    
    prompt = f"""
Đây là danh sách nhật ký trong 1 {period} của tôi:
{entries_text}

Hãy viết một bản tổng kết thân thiện, sâu sắc bao gồm:
1. Phân tích tâm trạng chung trong {period}.
2. Các chủ đề/sự kiện nổi bật nhất.
3. Một lời khuyên hoặc lời chúc ý nghĩa cho {period} tới.

Hãy trình bày đẹp mắt bằng Markdown.
"""
    
    try:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, _call, system, prompt)
        return summary
    except Exception as e:
        logger.error(f"Lỗi khi tạo summary AI: {e}")
        return "Có lỗi xảy ra khi tạo tổng kết. Vui lòng thử lại sau."

async def generate_streak_summary(entries, streak_length: int):
    """
    Tổng hợp nhật ký theo chuỗi streak của người dùng.
    """
    if not entries:
        return "Không có dữ liệu chuỗi streak để tổng hợp."
        
    entries_text = "\n".join([
        f"- Ngày {e['date']}: Q: {e['question']} | A: {e['answer']} | Sentiment: {e['sentiment'] or 'N/A'}"
        for e in entries
    ])
    
    system = f"Bạn là trợ lý tổng kết chuỗi thói quen và nhật ký cá nhân. {_lang()}"
    
    prompt = f"""
Đây là danh sách nhật ký trong chuỗi streak {streak_length} ngày liên tiếp của tôi:
{entries_text}

Hãy viết một bản tổng kết chuỗi streak thật ấn tượng, thân thiện và giàu động lực bao gồm:
1. 🎉 Lời chúc mừng hành trình kiên trì {streak_length} ngày qua.
2. 📈 Phân tích sự phát triển bản thân, xu hướng tâm trạng và các chủ đề nổi bật bạn nhận thấy qua chuỗi ngày này.
3. 💡 Lời khuyên/nhắn gửi để tiếp tục duy trì thói quen viết nhật ký tốt đẹp này.

Hãy trình bày đẹp mắt bằng Markdown.
"""
    
    try:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, _call, system, prompt)
        return summary
    except Exception as e:
        logger.error(f"Lỗi khi tạo streak summary AI: {e}")
        return "Có lỗi xảy ra khi tạo tổng kết chuỗi streak. Vui lòng thử lại sau."
