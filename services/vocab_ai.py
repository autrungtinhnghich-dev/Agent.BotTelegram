import logging
import json
import re
import asyncio
from services.summarizer import _call, _lang

logger = logging.getLogger(__name__)

async def generate_daily_vocab_ai(recent_words=None):
    """
    Sử dụng LLM để sinh ra một đoạn giao tiếp/hội thoại ngắn, thông dụng hàng ngày.
    recent_words: list các đoạn đã sinh gần đây để tránh lặp.
    Trả về định dạng JSON: {"en": "...", "zh": "...", "ja": "...", "vi": "..."}
    """
    if recent_words is None:
        recent_words = []
        
    avoid_list_str = ", ".join(recent_words[:5]) if recent_words else "Không có"
    
    system = "Bạn là một giáo viên ngôn ngữ đa quốc gia xuất sắc, chuyên dạy giao tiếp thực tế."
    
    import time
    seed = time.time()
    
    prompt = f"""
(Random Seed: {seed})
Nhiệm vụ: Tạo một đoạn giao tiếp/hội thoại ngắn (1-2 câu hoặc 1 cặp câu đối thoại A-B) bằng tiếng Anh, chủ đề thực tế đời sống hàng ngày (A2-B1). 
Danh sách cần tránh: [{avoid_list_str}].

Yêu cầu bắt buộc trong JSON:
- "en": Đoạn tiếng Anh (Ví dụ: "A: How much is this? B: It's 10 dollars.").
- "zh": Nghĩa tiếng Trung kèm Pinyin (Ví dụ: "A: 这个多少钱？(Zhège duōshǎo qián?) B: 10美元 (Shí měiyuán)").
- "ja": Nghĩa tiếng Nhật kèm Romaji (Ví dụ: "A: これはいくらですか？ (Kore wa ikura desu ka?) B: 10ドルです (Jū doru desu)").
- "vi": Nghĩa tiếng Việt.

Chỉ trả về duy nhất khối JSON sạch, không có text thừa.
"""
    for attempt in range(3):
        try:
            logger.info(f"Đang gọi AI để tạo đoạn giao tiếp mới (Lần {attempt+1}).")
            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(None, _call, system, prompt)
            
            data = None
            decoder = json.JSONDecoder()
            for match in re.finditer(r'\{', response_text):
                start_pos = match.start()
                try:
                    obj, _ = decoder.raw_decode(response_text[start_pos:])
                    if isinstance(obj, dict) and all(k in obj for k in ["en", "zh", "ja", "vi"]):
                        word_en = str(obj.get('en', '')).lower().strip()
                        # Kiểm tra placeholder (tránh trường hợp AI trả về text mẫu hoặc boilerplate)
                        placeholders = ["english word", "từ vựng mẫu", "ví dụ:"]
                        is_boilerplate = any(x in word_en for x in placeholders)
                        
                        # Nếu là hội thoại A-B hợp lệ thì không coi là placeholder kể cả khi chứa từ khóa (như "password")
                        if is_boilerplate and not ("a:" in word_en and "b:" in word_en):
                            logger.warning(f"AI trả về placeholder '{word_en}', đang thử lại...")
                            continue
                        
                        # Kiểm tra nếu word_en quá ngắn hoặc chỉ là một từ đơn lẻ trong list cấm
                        if word_en in ["apple", "word", "example"]:
                            logger.warning(f"AI trả về từ khóa placeholder '{word_en}', đang thử lại...")
                            continue

                        data = obj
                        break
                except (json.JSONDecodeError, ValueError):
                    continue

            if data:
                logger.info(f"Kết quả AI tạo đoạn giao tiếp: {data['en'][:30]}...")
                return data
                
            logger.warning(f"Lần {attempt+1} không tìm thấy JSON hợp lệ hoặc AI trả về placeholder.")
            prompt += "\nLưu ý: Hãy trả về DUY NHẤT khối JSON sạch, KHÔNG bao gồm 'thinking process' hay văn bản giải thích. Hãy chọn một chủ đề giao tiếp thực tế khác."
            
        except Exception as e:
            logger.error(f"Lỗi khi gọi AI lần {attempt+1}: {e}")
            if attempt == 2:
                return None
            
    return None
