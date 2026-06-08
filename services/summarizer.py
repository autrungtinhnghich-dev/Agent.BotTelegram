"""
services/summarizer.py
Gọi LLM API (VNPT) để tóm tắt, phân tích hội thoại.
"""

from __future__ import annotations
import logging
import requests
from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL, LANGUAGE, CHAT_MAX_HISTORY
from services.fetcher import FetchResult

# Tự động phân giải host.docker.internal thành 127.0.0.1 nếu chạy ngoài môi trường Docker
import socket
try:
    socket.gethostbyname("host.docker.internal")
except socket.gaierror:
    LLM_API_URL = LLM_API_URL.replace("host.docker.internal", "127.0.0.1")


logger = logging.getLogger(__name__)

LANG = {
    "vi": "Luôn trả lời bằng tiếng Việt. Ngắn gọn, súc tích, tuyệt đối không dài dòng. Tổng độ dài câu trả lời không quá 1500 ký tự.",
    "en": "Always reply in English. Be concise and brief. Do not exceed 1500 characters in your total response.",
}


def _lang() -> str:
    return LANG.get(LANGUAGE, LANG["vi"])


def _call(system: str, prompt: str) -> str:
    """Gọi LLM API với system prompt và user prompt."""
    try:
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 4096
        }
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        logger.info(f"Raw LLM response: {data}")

        # Thử các format response phổ biến (OpenAI-compatible, custom...)
        content = ""
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]
        elif "content" in data:
            content = data["content"]
        elif "response" in data:
            content = data["response"]
        else:
            logger.error(f"Unexpected response format: {data}")
            raise ValueError(f"Không nhận diện được format response: {list(data.keys())}")

        # Xóa các tag suy nghĩ (reasoning/thought) nếu có
        import re
        
        # 1. Nếu có thẻ đóng </think>, lấy phần nội dung sau nó
        if "</think>" in content:
            content = content.split("</think>")[-1]
        
        # 2. Xóa các block tag phổ biến
        content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL)
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL) # Thêm thẻ <think>
        
        # 3. Xóa các đoạn bắt đầu bằng "Here's a thinking process:" hoặc "Thinking:" (Chỉ khi có marker 📍 theo sau)
        content = re.sub(r'(?i)Here\'s a thinking process:.*?(?=\n\n📍|\n📍)', '', content, flags=re.DOTALL)
        content = re.sub(r'(?i)Thinking:.*?(?=\n\n📍|\n📍)', '', content, flags=re.DOTALL)
        
        # 4. Cuối cùng, nếu vẫn còn rác và có icon 📍, chỉ lấy từ icon 📍 trở đi
        if "📍" in content:
            # Tìm vị trí của icon 📍 đầu tiên
            pos = content.find("📍")
            content = content[pos:]
        
        return content.strip()

    except requests.exceptions.Timeout:
        logger.error("LLM API timeout")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"LLM API HTTP error: {e} — {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"LLM API error: {e}")
        raise




def chat_with_history(history: list[dict], user_message: str) -> str:
    """
    Gửi tin nhắn đến LLM kèm toàn bộ lịch sử hội thoại.

    history: list of {"role": "user"|"assistant", "content": str}
             (chưa bao gồm user_message hiện tại)
    Trả về: chuỗi reply từ AI.
    """
    system = (
        f"Bạn là trợ lý AI thông minh, hữu ích và trung thực. {_lang()} "
        "Trả lời chính xác, đầy đủ. Nếu không biết thì nói rõ. "
        "Với câu hỏi tính toán hoặc lập luận, hãy trình bày từng bước."
    )

    # Ghép history + tin nhắn mới
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": 4096
        }
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        elif "message" in data:
            return data["message"].strip()
        elif "content" in data:
            return data["content"].strip()
        elif "response" in data:
            return data["response"].strip()
        else:
            raise ValueError(f"Không nhận diện được format response: {list(data.keys())}")

    except requests.exceptions.Timeout:
        logger.error("LLM chat timeout")
        raise
    except requests.exceptions.HTTPError as e:
        logger.error(f"LLM chat HTTP error: {e} — {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"LLM chat error: {e}")
        raise


def summarize(result: FetchResult, mode: str = "default") -> str:
    if not result.messages:
        return "Không có tin nhắn nào để tóm tắt."

    modes = {
        "default": (
            "Tóm tắt theo cấu trúc:\n"
            "• **Chủ đề chính**: (1-2 câu)\n"
            "• **Điểm nổi bật**: (3-5 ý)\n"
            "• **Kết luận / Hành động**: (nếu có)"
        ),
        "short": "Tóm tắt toàn bộ trong 1-2 câu ngắn nhất có thể.",
        "formal": (
            "Viết biên bản họp chuyên nghiệp:\n"
            "- Chủ đề\n- Người tham gia\n- Nội dung chính\n- Quyết định / Hành động"
        ),
    }
    system = f"Bạn là trợ lý tóm tắt hội thoại. {_lang()}"
    prompt = (
        f"Chat: **{result.chat_name}** | {result.total_fetched} tin nhắn\n\n"
        f"--- Hội thoại ---\n{result.formatted_text()}\n---\n\n"
        f"{modes.get(mode, modes['default'])}"
    )
    return _call(system, prompt)


def answer_question(result: FetchResult, question: str) -> str:
    if not result.messages:
        return "Không có tin nhắn nào để phân tích."
    system = (
        f"Bạn là trợ lý thông minh. {_lang()} "
        "Chỉ trả lời dựa trên nội dung hội thoại. "
        "Nếu không tìm thấy thông tin, hãy nói rõ."
    )
    prompt = (
        f"--- Hội thoại: {result.chat_name} ---\n"
        f"{result.formatted_text()}\n---\n\n"
        f"Câu hỏi: {question}"
    )
    return _call(system, prompt)


def analyze_vibe(result: FetchResult) -> str:
    if not result.messages:
        return "Không có tin nhắn."
    system = f"Bạn là chuyên gia phân tích cảm xúc ngôn ngữ. {_lang()}"
    prompt = (
        f"--- Hội thoại: {result.chat_name} ---\n"
        f"{result.formatted_text()}\n---\n\n"
        "Phân tích không khí hội thoại:\n"
        "• 🌡️ Nhiệt độ: (Sôi nổi / Bình thường / Lạnh nhạt)\n"
        "• 😊 Tâm trạng: (Vui / Căng thẳng / Nghiêm túc / ...)\n"
        "• ⚡ Năng lượng: (Cao / Trung bình / Thấp)\n"
        "• 💬 Tổng kết: 1-2 câu"
    )
    return _call(system, prompt)


def who_dominated(result: FetchResult) -> str:
    if not result.messages:
        return "Không có dữ liệu."
    stats = result.user_stats()
    total = sum(stats.values())
    board = "\n".join(
        f"  {i+1}. {u}: {c} tin ({c/total*100:.0f}%)"
        for i, (u, c) in enumerate(stats.items())
    )
    system = f"Bạn là trợ lý phân tích. {_lang()}"
    prompt = (
        f"--- Thống kê ---\n{board}\n\n"
        f"--- Mẫu hội thoại ---\n{result.formatted_text()[:2000]}\n---\n\n"
        "1. Liệt kê bảng xếp hạng\n"
        "2. Nhận xét phong cách/vai trò của 2-3 người nổi bật"
    )
    return _call(system, prompt)


def summarize_search(keyword: str, result: FetchResult) -> str:
    if not result.messages:
        return f"Không tìm thấy tin nhắn nào về '{keyword}'."
    system = f"Bạn là trợ lý phân tích. {_lang()}"
    prompt = (
        f"Tìm kiếm '{keyword}' trong {result.chat_name} — {result.total_fetched} kết quả:\n\n"
        f"--- Nội dung ---\n{result.formatted_text()}\n---\n\n"
        f"Tóm tắt những gì mọi người nói về '{keyword}': quan điểm, thông tin chính, kết luận."
    )
    return _call(system, prompt)


def analyze_sentiment(result: FetchResult) -> str:
    """Phân tích cảm xúc từng người trong hội thoại."""
    if not result.messages:
        return "Không có tin nhắn."

    user_msgs: dict[str, list[str]] = {}
    for m in result.messages:
        user_msgs.setdefault(m.user, []).append(m.text)

    user_summary = "\n".join(
        f"{user} ({len(msgs)} tin):\n  " + " | ".join(msgs[:5])
        for user, msgs in list(user_msgs.items())[:10]
    )

    system = f"Bạn là chuyên gia tâm lý và phân tích ngôn ngữ. {_lang()}"
    prompt = (
        f"Phân tích cảm xúc từng người trong nhóm: {result.chat_name}\n"
        f"Tổng {result.total_fetched} tin nhắn từ {len(user_msgs)} người.\n\n"
        f"--- Nội dung theo từng người ---\n{user_summary}\n\n"
        f"--- Toàn bộ hội thoại ---\n{result.formatted_text()[:3000]}\n---\n\n"
        "Hãy phân tích cảm xúc từng người theo format:\n"
        "[Tên]: [Emoji trạng thái] [Cảm xúc chủ đạo] — [Nhận xét 1 câu]\n\n"
        "Ví dụ:\n"
        "An: 😰 Căng thẳng — Đang bị áp lực deadline, dùng nhiều từ gấp\n"
        "Bình: 😄 Vui vẻ — Hay đùa, dùng emoji nhiều\n\n"
        "Sau đó thêm phần TỔNG KẾT nhóm: ai cần được hỏi thăm, không khí chung."
    )
    return _call(system, prompt)


def summarize_mention(chat_name: str, messages: list, trigger_user: str) -> str:
    """Tóm tắt nhanh khi bot được mention trong group."""
    if not messages:
        return "Không có tin nhắn nào trước đó."

    conversation = "\n".join(
        f"[{m.date.strftime('%H:%M')}] {m.user}: {m.text}"
        for m in messages
    )
    system = f"Bạn là trợ lý tóm tắt nhanh. {_lang()}"
    prompt = (
        f"{trigger_user} vừa tag bot trong nhóm '{chat_name}'.\n"
        f"Đây là {len(messages)} tin nhắn trước đó:\n\n"
        f"--- Hội thoại ---\n{conversation}\n---\n\n"
        "Hãy tóm tắt và trả về DUY NHẤT format sau, không thêm bất kỳ văn bản dẫn nhập, giải thích hay 'thinking process' nào:\n\n"
        "📍 **HỌ MUỐN GÌ**: (Tóm gọn mục đích trong 1 câu)\n"
        "💬 **BỐI CẢNH**: (Chủ đề chính đang bàn trong 1 câu)\n"
        "⚖️ **MỨC ĐỘ**: (Gấp / Bình thường / Bỏ qua)\n"
        "💡 **GỢI Ý**: (Câu trả lời mẫu hoặc hành động tiếp theo)"
    )
    return _call(system, prompt)


def draft_message(result: FetchResult, intent: str) -> str:
    """
    Soạn sẵn một tin nhắn để gửi vào group dựa trên context và ý định của chủ.
    Trả về 2-3 phiên bản khác nhau để chủ chọn.
    """
    context_text = result.formatted_text()[-3000:] if result.messages else "(Không có context)"

    system = (
        f"Bạn là trợ lý soạn thảo tin nhắn Telegram chuyên nghiệp. {_lang()} "
        "Viết tin nhắn tự nhiên, phù hợp văn hóa nhóm, không quá formal trừ khi cần. "
        "KHÔNG giải thích, chỉ đưa ra các phiên bản tin nhắn."
    )
    prompt = (
        f"Nhóm: {result.chat_name} ({result.total_fetched} tin gần nhất)\n\n"
        f"--- Context hội thoại ---\n{context_text}\n---\n\n"
        f"Ý định của tôi: {intent}\n\n"
        "Soạn 3 phiên bản tin nhắn để tôi copy gửi vào nhóm, theo format:\n\n"
        "📝 Phiên bản 1 — [Phong cách: Ngắn gọn/Thân thiện/Formal]\n"
        "[Nội dung tin nhắn]\n\n"
        "📝 Phiên bản 2 — [Phong cách]\n"
        "[Nội dung tin nhắn]\n\n"
        "📝 Phiên bản 3 — [Phong cách]\n"
        "[Nội dung tin nhắn]\n\n"
        "Lưu ý: Viết tin nhắn sẵn sàng copy-paste, không thêm giải thích bên ngoài format."
    )
    return _call(system, prompt)


def suggest_reply(
    result: FetchResult,
    target_name: str,
    target_messages: list,
) -> str:
    """
    Phân tích lịch sử chat của một người cụ thể và gợi ý cách reply với họ.
    Trả về phân tích phong cách + 2-3 mẫu reply.
    """
    # Context chung của nhóm
    context_text = result.formatted_text()[-2000:] if result.messages else "(Không có)"

    # Tin nhắn riêng của người đó
    if target_messages:
        target_text = "\n".join(
            f"[{m.date.strftime('%H:%M')}] {m.text}"
            for m in target_messages[-30:]
        )
        last_msg = target_messages[-1].text if target_messages else ""
    else:
        target_text = "(Không tìm thấy tin nhắn nào)"
        last_msg = ""

    system = (
        f"Bạn là chuyên gia phân tích giao tiếp và soạn thảo tin nhắn. {_lang()} "
        "Phân tích ngắn gọn, thực tế, tập trung vào hành động."
    )
    prompt = (
        f"Nhóm: {result.chat_name}\n"
        f"Tôi muốn reply với: {target_name}\n\n"
        f"--- Tin nhắn gần đây của {target_name} ---\n{target_text}\n---\n\n"
        f"--- Context nhóm (20 tin gần nhất) ---\n{context_text}\n---\n\n"
        f"Tin nhắn gần nhất của họ: \"{last_msg}\"\n\n"
        "Hãy phân tích và gợi ý theo format:\n\n"
        f"🔍 PHONG CÁCH CỦA {target_name.upper()}:\n"
        "(2-3 câu: họ hay nói kiểu gì, tone như thế nào, điều gì quan trọng với họ)\n\n"
        "💡 NÊN REPLY THẾ NÀO:\n"
        "(1-2 câu gợi ý chiến lược: nên dùng tone gì, nên đề cập gì)\n\n"
        "✉️ MẪU REPLY 1 — [Phong cách]:\n"
        "[Nội dung — sẵn sàng copy]\n\n"
        "✉️ MẪU REPLY 2 — [Phong cách]:\n"
        "[Nội dung — sẵn sàng copy]\n\n"
        "✉️ MẪU REPLY 3 — [Phong cách]:\n"
        "[Nội dung — sẵn sàng copy]"
    )
    return _call(system, prompt)


def analyze_owner_mention(
    chat_name: str,
    mention_text: str,
    sender_name: str,
    sender_username: str,
    context_messages: list,
    owner_username: str,
) -> str:
    """
    Phân tích khi ai tag chính owner trong group.
    Trả về:
      - Họ muốn gì / hỏi gì
      - Context đang nói về chủ đề gì
      - Mức độ urgent
      - Đề xuất cách reply
    """
    if not context_messages:
        context_text = "(Không có tin nhắn context)"
    else:
        context_text = "\n".join(
            f"[{m.date.strftime('%H:%M')}] {m.user}: {m.text}"
            for m in context_messages[-20:]
        )

    system = (
        f"Bạn là trợ lý thông minh giúp chủ quản lý tin nhắn Telegram. {_lang()} "
        "Phân tích nhanh, thực tế, có thể hành động được."
    )
    prompt = (
        f"Chủ ({owner_username}) vừa bị tag trong nhóm '{chat_name}'.\n\n"
        f"Tin nhắn tag:\n\"{mention_text}\"\n\n"
        f"Người gửi: {sender_name}"
        + (f" (@{sender_username})" if sender_username else "")
        + f"\n\n--- Context {len(context_messages)} tin trước đó ---\n{context_text}\n---\n\n"
        "Hãy phân tích và trả về DUY NHẤT format sau, không thêm bất kỳ văn bản dẫn nhập, giải thích hay 'thinking process' nào:\n\n"
        "📍 **HỌ MUỐN GÌ**: (Tóm gọn mục đích trong 1 câu)\n"
        "💬 **BỐI CẢNH**: (Chủ đề chính đang bàn trong 1 câu)\n"
        "⚖️ **MỨC ĐỘ**: (Gấp / Bình thường / Bỏ qua)\n"
        "💡 **GỢI Ý**: (Câu trả lời mẫu ngắn gọn)"
    )
    return _call(system, prompt)


def analyze_mentions_topics(mentions: list[dict], days: int) -> str:
    """
    Sử dụng LLM để phân tích chủ đề các tin nhắn tag/mention.
    mentions: list of dict {"sender_name": str, "chat_name": str, "message_text": str, "created_at": str}
    """
    if not mentions:
        return "Không có nội dung tag nào để phân tích."
        
    formatted_mentions = []
    for m in mentions:
        formatted_mentions.append(
            f"- [{m['created_at'][:16]}] {m['sender_name']} trong nhóm '{m['chat_name']}': {m['message_text']}"
        )
    mentions_text = "\n".join(formatted_mentions)
    
    system = f"Bạn là trợ lý thông minh phân tích hiệu suất làm việc và giao tiếp. {_lang()}"
    prompt = (
        f"Dưới đây là danh sách các tin nhắn mà mọi người đã tag/mention tôi trong {days} ngày qua:\n\n"
        f"--- Danh sách Tag ---\n{mentions_text}\n---\n\n"
        f"Hãy phân tích và viết báo cáo theo format sau:\n\n"
        f"📊 **PHÂN TÍCH CHỦ ĐỀ CÁC CUỘC HỘI THOẠI:**\n"
        f"• **Chủ đề chính được nhắc đến nhiều nhất**: (Phân tích 2-3 chủ đề chính, ví dụ: công việc, lỗi hệ thống, hỏi đáp tài liệu...)\n"
        f"• **Phân tích theo người tag**: (Nhận xét ngắn gọn xem từng người hay tag bạn vì việc gì. Ví dụ: 'Nguyễn Văn A hay tag báo lỗi Server', 'Trần Thị B hay hỏi tài liệu'...)\n\n"
        f"⚠️ **CÁC VẤN ĐỀ NỔI BẬT / CẦN LƯU Ý:**\n"
        f"• (Liệt kê các vấn đề hoặc task quan trọng/gấp rút xuất hiện trong các tin nhắn tag cần giải quyết)\n\n"
        f"💡 **ĐỀ XUẤT CỦA AI:**\n"
        f"• (Đưa ra đề xuất để tối ưu hóa thời gian xử lý các tag này, ví dụ: viết FAQ, setup bot tự trả lời, phân quyền...)"
    )
    return _call(system, prompt)


def answer_from_brain(context: str, question: str) -> str:
    """Trả lời câu hỏi dựa trên kiến thức từ bộ nhớ cá nhân (RAG)."""
    system = (
        f"Bạn là 'Bộ não thứ hai' của người dùng. {_lang()} "
        "Hãy dựa vào những kiến thức được cung cấp bên dưới để trả lời câu hỏi của người dùng một cách chính xác nhất. "
        "Nếu thông tin cung cấp không đủ để trả lời, hãy nói rằng bạn chưa biết rõ về vấn đề này trong bộ nhớ hiện tại. "
        "Luôn ưu tiên các thông tin có ngày tháng gần nhất nếu có xung đột."
    )
    prompt = (
        f"--- KIẾN THỨC TỪ BỘ NHỚ CỦA BẠN ---\n"
        f"{context}\n"
        f"-----------------------------------\n\n"
        f"CÂU HỎI: {question}\n\n"
        f"Hãy trả lời dựa trên kiến thức trên:"
    )
    return _call(system, prompt)


def extract_tags(text: str) -> str:
    """Trích xuất 3-5 tags (từ khóa) từ nội dung văn bản."""
    system = "Bạn là trợ lý phân loại dữ liệu. Trả về duy nhất danh sách các tag, phân cách bằng dấu phẩy. Ví dụ: server, setup, linux"
    prompt = f"Hãy trích xuất 3-5 từ khóa chính từ văn bản sau:\n\n{text}"
    return _call(system, prompt)


# ═══════════════════════════════════════════════════════════
# 🥊 AI DEBATE
# ═══════════════════════════════════════════════════════════

def debate_opening(topic: str, side_a: str, side_b: str) -> str:
    """
    Lượt mở đầu — Phe A trình bày lập luận ban đầu.
    side_a: phe đang lập luận, side_b: đối thủ.
    """
    system = (
        f"Bạn đang nhập vai là người ủng hộ '{side_a}' trong cuộc tranh luận về '{topic}'. "
        f"Hãy lập luận mạnh mẽ, tự tin và có dẫn chứng thực tế. "
        f"Tuyệt đối KHÔNG thừa nhận điểm yếu nào. {_lang()} "
        f"Giới hạn 300 từ."
    )
    prompt = (
        f"Chủ đề tranh luận: **{topic}**\n"
        f"Lập trường của bạn: ủng hộ **{side_a}** (chống lại {side_b})\n\n"
        f"Hãy trình bày lập luận mở đầu của phe {side_a} với:\n"
        f"• Luận điểm chính (1-2 câu mạnh mẽ)\n"
        f"• 3 bằng chứng/ví dụ thực tế cụ thể\n"
        f"• Câu kết thách thức phe {side_b}"
    )
    return _call(system, prompt)


def debate_counter(topic: str, my_side: str, opp_side: str, opp_argument: str) -> str:
    """
    Lượt phản biện — Phe này bác bỏ lập luận của đối phương và đưa ra điểm mới.
    """
    system = (
        f"Bạn đang nhập vai là người ủng hộ '{my_side}' trong cuộc tranh luận về '{topic}'. "
        f"Bạn vừa nghe đối thủ '{opp_side}' lập luận. Hãy phản biện sắc bén và trực tiếp. "
        f"PHẢI đề cập và bác bỏ ít nhất 1 điểm cụ thể của đối thủ. {_lang()} "
        f"Giới hạn 280 từ."
    )
    prompt = (
        f"Chủ đề: **{topic}**\n"
        f"Lập trường của bạn: **{my_side}**\n\n"
        f"Đối thủ ({opp_side}) vừa nói:\n---\n{opp_argument}\n---\n\n"
        f"Hãy phản biện theo format:\n"
        f"⚡ Bác bỏ điểm mạnh nhất của {opp_side}\n"
        f"🔥 Đưa ra 2 lập luận mới của {my_side}\n"
        f"🎯 Câu kết tấn công"
    )
    return _call(system, prompt)


def debate_verdict(topic: str, side_a: str, side_b: str, arguments: list[dict]) -> str:
    """
    AI phán xử công bằng — ai thắng và tại sao.
    arguments: list of {"side": str, "text": str}
    """
    debate_log = "\n\n".join(
        f"[{a['side']}]: {a['text'][:400]}..." if len(a['text']) > 400 else f"[{a['side']}]: {a['text']}"
        for a in arguments
    )
    system = (
        f"Bạn là trọng tài tranh luận công bằng và khách quan. "
        f"Hãy phân tích và phán xử dựa trên chất lượng lập luận, bằng chứng và logic. "
        f"KHÔNG thiên vị bên nào. {_lang()}"
    )
    prompt = (
        f"Chủ đề tranh luận: **{topic}**\n"
        f"Hai phe: **{side_a}** vs **{side_b}**\n\n"
        f"=== Nội dung tranh luận ===\n{debate_log}\n===\n\n"
        f"Hãy phán xử theo format sau:\n\n"
        f"⚖️ **KẾT QUẢ**: [Phe thắng hoặc Hòa]\n\n"
        f"🏆 **LÝ DO**: (2-3 câu giải thích tại sao phe đó thắng)\n\n"
        f"💪 **ĐIỂM MẠNH CỦA {side_a.upper()}**: (1 câu)\n"
        f"💪 **ĐIỂM MẠNH CỦA {side_b.upper()}**: (1 câu)\n\n"
        f"📝 **KẾT LUẬN**: (1 câu tổng kết ý nghĩa của cuộc tranh luận)"
    )
    return _call(system, prompt)


# ═══════════════════════════════════════════════════════════
# 🕵️ SPY MODE
# ═══════════════════════════════════════════════════════════

def spy_summary(result: FetchResult, owner_username: str = "", time_label: str = "") -> str:
    """
    Tóm tắt nhóm theo góc nhìn 'người vừa quay lại'.
    Chỉ highlight những gì THỰC SỰ QUAN TRỌNG, bỏ qua small talk.

    Trả về report với 4 sections:
      📌 Quyết định/thông tin quan trọng
      🏷️ Ai nhắc tới owner (nếu có)
      ❓ Câu hỏi chưa được trả lời
      ⚡ Điểm nóng / Drama (nếu có)
    """
    if not result.messages:
        return f"Nhóm im lặng hoàn toàn{' trong ' + time_label if time_label else ''}. 😴"

    conversation = "\n".join(
        f"[{m.date.strftime('%H:%M')}] {m.user}: {m.text}"
        for m in result.messages
    )

    owner_note = ""
    if owner_username:
        owner_note = (
            f"\nLưu ý: Người dùng là '{owner_username}'. "
            f"Hãy đặc biệt chú ý nếu có ai nhắc tới họ trong chat."
        )

    system = (
        f"Bạn là trợ lý thông minh giúp người dùng nắm bắt nhanh những gì xảy ra khi họ vắng mặt. "
        f"Hãy CHỈ báo cáo những điều THỰC SỰ QUAN TRỌNG — bỏ qua hoàn toàn small talk, chào hỏi, "
        f"và các tin nhắn không có giá trị thông tin. {_lang()}{owner_note}"
    )

    prompt = (
        f"Nhóm: {result.chat_name} | {result.total_fetched} tin nhắn{' | ' + time_label if time_label else ''}\n\n"
        f"=== NỘI DUNG CHAT ===\n{conversation[:4000]}\n===\n\n"
        f"Hãy viết SPY REPORT theo format SAU ĐÂY. "
        f"Nếu một section không có nội dung, hãy bỏ qua section đó hoàn toàn (đừng viết 'Không có'):\n\n"
        f"📌 **QUYẾT ĐỊNH / THÔNG TIN QUAN TRỌNG:**\n"
        f"(Liệt kê các quyết định, thông báo, kế hoạch được đề cập — mỗi mục 1 dòng, bắt đầu bằng •)\n\n"
        f"🏷️ **NHẮC TỚI BẠN:**\n"
        f"(Nếu ai nhắc tới '{owner_username or 'bạn'}' — ghi rõ ai nói gì và lúc mấy giờ)\n\n"
        f"❓ **CÂU HỎI CHƯA CÓ ĐÁP ÁN:**\n"
        f"(Các câu hỏi được đặt ra nhưng chưa ai trả lời — ghi rõ ai hỏi lúc mấy giờ)\n\n"
        f"⚡ **ĐIỂM NÓNG:**\n"
        f"(Drama, tranh luận, vấn đề căng thẳng nếu có — tóm tắt ngắn gọn)"
    )
    return _call(system, prompt)

# ═══════════════════════════════════════════════════════════
# 🔍 AI CODE REVIEW
# ═══════════════════════════════════════════════════════════

def review_code_changes(code_input: str, is_full_file: bool = False) -> str:
    """
    Gửi diff code hoặc full file cho AI để review và đề xuất các điểm cần điều chỉnh.
    """
    input_type = "TOÀN BỘ NỘI DUNG FILE (FULL CONTENT)" if is_full_file else "ĐOẠN THAY ĐỔI (DIFF)"
    system = (
        f"Bạn là một Senior Developer chuyên review code (Merge Request/Pull Request). {_lang()} "
        f"Hãy đọc kĩ {input_type} sau đây để đưa ra đánh giá khách quan. "
        "NHIỆM VỤ QUAN TRỌNG NHẤT: \n"
        "1. Tập trung review các dòng có dấu '>>> ' ở đầu (đây là các dòng thực sự thay đổi trong MR). \n"
        "2. Sử dụng các dòng xung quanh (không có dấu '>>> ') làm ngữ cảnh (context) để kiểm tra biến đã khai báo chưa, logic có khớp không. \n"
        "3. Tìm bug nghiêm trọng (biến chưa khai báo, null pointer, logic sai). \n"
        "4. Đề xuất tối ưu nhưng không nhắc lại các vấn đề ở phần code cũ không liên quan. \n"
        "Luôn giữ thái độ xây dựng, rõ ràng và trực tiếp."
    )

    prompt = (
        f"=== NỘI DUNG CODE ({input_type}) ===\n"
        f"{code_input}\n"
        f"=====================================\n\n"
        f"Hãy review đoạn code trên và phản hồi theo cấu trúc sau (Dùng Markdown format, chú ý Gom nhóm theo File - dùng tên file sau chữ 'FILE:' trong input và chỉ rõ dòng/đoạn code cần sửa):\n\n"
        f"🔍 **TÓM TẮT THAY ĐỔI:**\n"
        f"(Giải thích ngắn gọn mục đích của MR)\n\n"
        f"🛠️ **CHI TIẾT REVIEW THEO FILE:**\n"
        f"(Lưu ý quan trọng: Với các lỗi **NGHIÊM TRỌNG**, hãy bắt đầu bằng icon 🔴, viết đậm tiêu đề lỗi, và sử dụng block ```diff với dấu trừ '-' ở đầu mỗi dòng code lỗi để Telegram tô màu đỏ)\n\n"
        f"**File: [Tên_File_1]**\n"
        f"• **Dòng [Số_Dòng]:** 🔴 **[LỖI NGHIÊM TRỌNG: Tên_Vấn_Đề]**\n"
        f"  - Giải thích: [Tại sao lỗi này nghiêm trọng]\n"
        f"  - Code hiện tại: \n"
        f"```diff\n"
        f"- [đoạn code cũ]\n"
        f"```\n"
        f"  - Gợi ý sửa: \n"
        f"```diff\n"
        f"+ [đoạn code mới]\n"
        f"```\n"
        f"• **Dòng [Số_Dòng]:** [Vấn đề/Gợi ý bình thường]\n"
        f"  - Code hiện tại: `[đoạn code cũ]`\n"
        f"  - Gợi ý sửa: `[đoạn code mới]`\n"
        f"• ...\n\n"
        f"**File: [Tên_File_2]**\n"
        f"• ...\n\n"
        f"⚠️ **VẤN ĐỀ CHUNG (Bảo mật/Hiệu năng):**\n"
        f"(Các vấn đề mang tính hệ thống hoặc kiến trúc)\n\n"
        f"✅ **KẾT LUẬN:**\n"
        f"(Approve | Request Changes | Comment)"
    )
    return _call(system, prompt)


def answer_from_brain_with_history(history: list[dict], context: str, question: str) -> str:
    """Trả lời câu hỏi dựa trên kiến thức từ bộ nhớ cá nhân (RAG) và lịch sử hội thoại."""
    system = (
        f"Bạn là 'Bộ não thứ hai' của người dùng. {_lang()} "
        "Hãy dựa vào những kiến thức được cung cấp bên dưới để trả lời câu hỏi của người dùng một cách chính xác nhất. "
        "Ngoài ra, hãy chú ý đến lịch sử hội thoại để trả lời các câu hỏi nối tiếp. "
        "Nếu thông tin cung cấp không đủ để trả lời, hãy nói rằng bạn chưa biết rõ về vấn đề này trong bộ nhớ hiện tại. "
        "Luôn ưu tiên các thông tin có ngày tháng gần nhất nếu có xung đột."
    )
    
    messages = [{"role": "system", "content": system}]
    
    context_msg = f"--- KIẾN THỨC TỪ BỘ NHỚ CỦA BẠN ---\n{context}\n-----------------------------------"
    messages.append({"role": "system", "content": context_msg})
    
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    
    try:
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": 4096
        }
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        content = ""
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]
        elif "content" in data:
            content = data["content"]
        elif "response" in data:
            content = data["response"]
        else:
            raise ValueError(f"Không nhận diện được format response: {list(data.keys())}")
            
        import re
        if "</think>" in content:
            content = content.split("</think>")[-1]
        content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL)
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        return content.strip()
    except Exception as e:
        logger.error(f"Lỗi khi gọi AI trả lời từ brain với history: {e}")
        raise e


def summarize_web_article(title: str, text: str) -> str:
    """Tóm tắt bài viết từ link web."""
    system = f"Bạn là trợ lý đọc hiểu và tóm tắt bài viết chuyên nghiệp. {_lang()}"
    prompt = (
        f"Hãy tóm tắt bài viết sau đây một cách chi tiết và rõ ràng theo cấu trúc:\n\n"
        f"📝 **TIÊU ĐỀ:** {title}\n\n"
        f"📌 **TÓM TẮT Ý CHÍNH (TL;DR):**\n"
        f"(Tóm tắt tổng quan bài viết trong 2-3 câu)\n\n"
        f"🔑 **CÁC ĐIỂM NHẤN QUAN TRỌNG:**\n"
        f"(Liệt kê các luận điểm, thông tin cốt lõi, số liệu cụ thể dưới dạng gạch đầu dòng •)\n\n"
        f"💡 **KẾT LUẬN / HÀNH ĐỘNG:**\n"
        f"(Bài học rút ra hoặc kết luận của bài viết)\n\n"
        f"--- NỘI DUNG BÀI VIẾT ---\n{text[:6000]}"
    )
    return _call(system, prompt)


def summarize_youtube_video(video_id: str, transcript: str) -> str:
    """Tóm tắt video YouTube từ phụ đề."""
    system = f"Bạn là chuyên gia phân tích và tóm tắt nội dung video YouTube. {_lang()}"
    prompt = (
        f"Dưới đây là phụ đề (transcript) của một video YouTube (ID: {video_id}). "
        f"Hãy đọc phụ đề này và tóm tắt chi tiết nội dung video theo cấu trúc:\n\n"
        f"🎥 **TÓM TẮT VIDEO YOUTUBE**\n\n"
        f"📌 **TỔNG QUAN (TL;DR):**\n"
        f"(Tóm tắt chủ đề chính và thông điệp của video trong 2-3 câu)\n\n"
        f"🔑 **NỘI DUNG CHI TIẾT:**\n"
        f"(Tóm tắt các phần chính được chia sẻ trong video dưới dạng gạch đầu dòng •)\n\n"
        f"💡 **BÀI HỌC / THÔNG ĐIỆP CHÍNH:**\n"
        f"(Ý nghĩa chính hoặc lời khuyên của người nói trong video)\n\n"
        f"--- PHỤ ĐỀ VIDEO ---\n{transcript[:8000]}"
    )
    return _call(system, prompt)


def analyze_jira_issue_risk(issue_data: dict) -> dict:
    """
    Sử dụng LLM để phân tích rủi ro trễ hạn của một task Jira.
    Nhận vào dictionary chứa thông tin chi tiết (fields, comments, status history).
    Trả về dict chứa thông tin phân tích và báo cáo HTML.
    """
    import json
    from services.markdown import escape, bold, italic, code, link, build
    from config import JIRA_BASE_URL
    
    # 1. Định dạng Estimate, Spent, Remaining
    def seconds_to_str(s):
        if not s: return "0h"
        return f"{s // 3600}h"

    orig = seconds_to_str(issue_data.get("timeoriginalestimate"))
    spent = seconds_to_str(issue_data.get("timespent"))
    est = seconds_to_str(issue_data.get("timeestimate"))
    
    # 2. Định dạng danh sách comment
    comments_str = ""
    if issue_data.get("comments"):
        comments_str = "\n".join(
            f"- {c['author']} ({c['created'][:10]}): {c['body']}"
            for c in issue_data["comments"][-10:]
        )
    else:
        comments_str = "(Không có comment nào)"
        
    # 3. Định dạng lịch sử đổi trạng thái
    history_str = ""
    if issue_data.get("status_history"):
        history_str = "\n".join(
            f"- {h['author']} ({h['created'][:10]}): {h['from']} -> {h['to']}"
            for h in issue_data["status_history"][-5:]
        )
    else:
        history_str = "(Không có lịch sử thay đổi trạng thái)"

    # 4. Tạo Prompt phân tích
    system = (
        "Bạn là một chuyên gia Quản lý dự án (Project Manager) và trợ lý AI phân tích rủi ro chuyên nghiệp. "
        "Nhiệm vụ của bạn là đọc thông tin chi tiết của một Task trên Jira (thời hạn, ước lượng thời gian làm việc, các bình luận trao đổi, lịch sử trạng thái) "
        "để phân tích xem task này có nguy cơ trễ hạn hay không.\n\n"
        "Hãy phân tích thật logic và thực tế:\n"
        "- So sánh thời gian còn lại đến hạn chót (duedate) so với thời gian ước lượng còn lại (timeestimate).\n"
        "- Đánh giá mô tả task có quá dài/phức tạp nhưng Estimate quá ít không.\n"
        "- Xem xét các bình luận thảo luận gần đây có dấu hiệu bị nghẽn (blocker), bất đồng ý kiến, thiếu tài liệu, hoặc chờ đợi phê duyệt không.\n"
        "- Đánh giá lịch sử trạng thái (ví dụ: chuyển qua lại giữa các trạng thái nhiều lần hoặc giậm chân tại chỗ quá lâu).\n\n"
        "Bắt buộc trả về kết quả dưới định dạng JSON duy nhất, không có văn bản thừa bên ngoài khối JSON. Định dạng JSON như sau:\n"
        "{\n"
        '  "risk_level": "HIGH" | "MEDIUM" | "LOW",\n'
        '  "risk_score": 85, // số nguyên từ 0 đến 100\n'
        '  "analysis": "Tóm tắt ngắn gọn 2-3 câu đánh giá tổng thể tình hình của task và lý do đánh giá mức rủi ro như vậy.",\n'
        '  "reasons": ["Lý do chi tiết 1", "Lý do chi tiết 2"],\n'
        '  "recommendations": ["Khuyến nghị khắc phục 1", "Khuyến nghị khắc phục 2"]\n'
        "}"
    )

    prompt = (
        f"=== THÔNG TIN JIRA TASK {issue_data['key']} ===\n"
        f"Mã Task: {issue_data['key']}\n"
        f"Tiêu đề: {issue_data['summary']}\n"
        f"Mô tả: {issue_data['description']}\n"
        f"Trạng thái hiện tại: {issue_data['status']}\n"
        f"Độ ưu tiên: {issue_data['priority']}\n"
        f"Người xử lý: {issue_data['assignee']}\n"
        f"Ngày tạo: {issue_data.get('created')}\n"
        f"Ngày cập nhật cuối: {issue_data.get('updated')}\n"
        f"Hạn chót (duedate): {issue_data.get('duedate') or 'Chưa cấu hình'}\n"
        f"Thời gian ước lượng ban đầu (Original Estimate): {orig}\n"
        f"Thời gian đã logwork (Spent): {spent}\n"
        f"Thời gian cần thêm ước lượng (Remaining Estimate): {est}\n\n"
        f"--- BÌNH LUẬN THẢO LUẬN GẦN ĐÂY ---\n{comments_str}\n\n"
        f"--- LỊCH SỬ THAY ĐỔI TRẠNG THÁI ---\n{history_str}\n\n"
        "Hãy thực hiện phân tích rủi ro trễ hạn cho task này và trả về JSON đúng cấu trúc yêu cầu."
    )

    try:
        response_text = _call(system, prompt)
        
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        result = json.loads(clean_text)
        
        # Tạo báo cáo HTML trực quan và sang trọng
        risk_level = result.get("risk_level", "LOW").upper()
        risk_score = result.get("risk_score", 0)
        analysis_text = result.get("analysis", "")
        reasons = result.get("reasons", [])
        recommendations = result.get("recommendations", [])
        
        risk_emoji = {
            "HIGH": "🔴 CAO",
            "MEDIUM": "🟡 TRUNG BÌNH",
            "LOW": "🟢 THẤP"
        }.get(risk_level, risk_level)
        
        issue_link = f"{JIRA_BASE_URL}/browse/{issue_data['key']}"
        
        report_lines = [
            f"📊 {bold('BÁO CÁO PHÂN TÍCH RỦI RO JIRA')}",
            "",
            f"🎫 {bold('Task:')} {link(issue_data['key'], issue_link)} — {escape(issue_data['summary'])}",
            f"👤 {bold('Người xử lý:')} {escape(issue_data['assignee'])}",
            f"🕒 {bold('Hạn chót:')} {code(issue_data.get('duedate') or 'Chưa cài đặt')}",
            f"⏱️ {bold('Thời gian:')} Estimate: {code(orig)} | Logged: {code(spent)} | Còn lại: {code(est)}",
            "",
            f"🔥 {bold('Mức độ rủi ro:')} {bold(risk_emoji)} ({bold(str(risk_score))}/100)",
            "",
            f"📝 {bold('Đánh giá tổng thể:')}",
            f"<i>{escape(analysis_text)}</i>",
            "",
            f"🔎 {bold('Nguyên nhân chính:')}"
        ]
        
        if reasons:
            for r in reasons:
                report_lines.append(f" • {escape(r)}")
        else:
            report_lines.append(" • Chưa phát hiện rủi ro đáng kể nào.")
            
        report_lines.extend([
            "",
            f"💡 {bold('Đề xuất giải quyết:')}"
        ])
        
        if recommendations:
            for rec in recommendations:
                report_lines.append(f" • {escape(rec)}")
        else:
            report_lines.append(" • Chưa có đề xuất cụ thể.")
            
        result["markdown_report"] = "\n".join(report_lines)
        return result
        
    except Exception as e:
        logger.error(f"Lỗi khi AI phân tích rủi ro Jira: {e}")
        # Trả về dict fallback
        fallback_msg = build(
            f"⚠️ {bold('Không thể phân tích rủi ro tự động bằng AI')}",
            f"Task: {code(issue_data['key'])}",
            f"Lỗi: {escape(str(e))}"
        )
        return {
            "risk_level": "MEDIUM",
            "risk_score": 50,
            "reasons": ["Không thể phân tích bằng AI do lỗi hệ thống hoặc format phản hồi."],
            "recommendations": ["Kiểm tra lại kết nối API hoặc cấu hình LLM."],
            "markdown_report": fallback_msg
        }


def analyze_release_commits(commits: list[dict], current_version: str | None, project_name: str | None = None) -> str:
    """
    Sử dụng LLM để phân tích danh sách các commit trong MR và đề xuất release tag tiếp theo cùng Changelog/Release Notes cực kỳ ngắn gọn.
    """
    current_ver_str = current_version if current_version else "v1.0.0"
    proj_name = project_name if project_name else "SmartTown"
    
    # Định dạng danh sách commit thành text gửi cho LLM
    commits_text_list = []
    for c in commits:
        author = c.get("author_name", "Anonymous")
        msg = c.get("title", "")
        description = c.get("message", "")
        if description and description.strip() != msg.strip():
            msg = f"{msg}\n{description}"
        commits_text_list.append(f"- [{author}]: {msg}")
    
    commits_text = "\n".join(commits_text_list)

    system = (
        "Bạn là một Trưởng nhóm Phát triển (Tech Lead / Release Manager) chuyên nghiệp. "
        "Nhiệm vụ của bạn là đọc các commit messages của một Merge Request và trả về đề xuất phiên bản tiếp theo kèm tài liệu Release Notes cực kỳ ngắn gọn, cô đọng.\n\n"
        "YÊU CẦU QUAN TRỌNG VỀ ĐỊNH DẠNG VÀ PHONG CÁCH:\n"
        "1. Trích xuất mã task Jira (ví dụ: `G038-18694`, `G038-18622`, `G038-18767`) từ nội dung commit message nếu có. Sử dụng mã task này ở đầu mỗi gạch đầu dòng.\n"
        "2. Gom nhóm các thay đổi thành đúng 2 nhóm:\n"
        "   - 🚀 **Tính năng mới**\n"
        "   - 🔧 **Cải tiến & điều chỉnh** (Gộp cả sửa lỗi/bugfix, refactor, clean code, nâng cấp sdk... vào đây)\n"
        "3. Mỗi commit/thay đổi chỉ viết đúng 1 dòng cực kỳ ngắn gọn và súc tích. Bôi đậm các từ khóa quan trọng của hành động/chức năng (ví dụ: `* **G038-18622**: **Điều chỉnh check chọn công khai thông tin** khi **thêm/cập nhật PAKN** trên **app Cư dân số**`).\n"
        "4. Nếu commit không chứa mã task Jira, hãy viết dạng: `* **[Tóm tắt chức năng bôi đậm]** [mô tả phụ]`.\n"
        "5. Phân tích SemVer để đề xuất tag mới (MAJOR nếu có breaking change, MINOR nếu có feat mới, PATCH nếu chỉ có fix/cải tiến)."
    )

    prompt = (
        f"--- THÔNG TIN DỰ ÁN CẦN PHÂN TÍCH ---\n"
        f"Tên ứng dụng: {proj_name}\n"
        f"Phiên bản hiện tại: {current_ver_str}\n\n"
        f"Danh sách commits trong MR:\n"
        f"{commits_text}\n"
        f"--------------------------------------\n\n"
        f"Hãy phân tích và trả về phản hồi theo cấu trúc Markdown chính xác sau đây (không được thêm bất kỳ câu dẫn nhập hay giải thích nào khác):\n\n"
        f"📦 **ĐỀ XUẤT VERSION:** `[Gợi ý tag mới, ví dụ: v1.2.0]` ([MAJOR / MINOR / PATCH]) - Từ: `{current_ver_str}`\n\n"
        f"📋 **Nhấp vào khung dưới đây để sao chép Markdown (dán vào GitLab Release):**\n"
        f"```markdown\n"
        f"📌 **Release Notes – {proj_name}**\n\n"
        f"🚀 **Tính năng mới**\n\n"
        f"* **[Mã Task nếu có]**: **[Tóm tắt chức năng bôi đậm]** [mô tả phụ ngắn gọn].\n"
        f"* ...\n\n"
        f"🔧 **Cải tiến & điều chỉnh**\n\n"
        f"* **[Mã Task nếu có]**: **[Tóm tắt sửa đổi bôi đậm]** [mô tả phụ ngắn gọn].\n"
        f"* ...\n"
        f"```\n"
    )

    return _call(system, prompt)


def generate_release_notes(commits: list[dict], project_name: str) -> str:
    """
    Tạo Release Notes tóm tắt tất cả commits từ merge request.
    Chỉ trả về nội dung Release Notes (dạng bullet points), không trả về văn bản dẫn nhập.
    """
    commits_text_list = []
    for c in commits:
        author = c.get("author_name", "Anonymous")
        msg = c.get("title", "")
        description = c.get("message", "")
        if description and description.strip() != msg.strip():
            msg = f"{msg}\n{description}"
        commits_text_list.append(f"- [{author}]: {msg}")
    
    commits_text = "\n".join(commits_text_list)
    
    system = (
        "Bạn là một Trưởng nhóm Phát triển (Tech Lead / Release Manager) chuyên nghiệp. "
        "Nhiệm vụ của bạn là đọc các commit messages của một Merge Request và tạo tài liệu Release Notes cực kỳ ngắn gọn, cô đọng bằng tiếng Việt.\n\n"
        "YÊU CẦU QUAN TRỌNG VỀ ĐỊNH DẠNG VÀ PHONG CÁCH:\n"
        "1. Trích xuất mã task Jira (ví dụ: `G038-18694`, `G038-18622`, `G038-18767`) từ nội dung commit message nếu có. Sử dụng mã task này ở đầu mỗi gạch đầu dòng theo dạng: `* **[Mã Task]**: **[Chức năng bôi đậm]** [mô tả phụ ngắn gọn]`.\n"
        "2. Gom nhóm các thay đổi thành đúng 2 nhóm:\n"
        "   - 🚀 **Tính năng mới**\n"
        "   - 🔧 **Cải tiến & điều chỉnh** (Gộp cả sửa lỗi/bugfix, refactor, cải tiến vào đây)\n"
        "3. Mỗi thay đổi chỉ viết đúng 1 dòng cực kỳ ngắn gọn và súc tích. Bôi đậm các từ khóa quan trọng của hành động/chức năng (ví dụ: `* **G038-18622**: **Điều chỉnh check chọn công khai thông tin** khi **thêm/cập nhật PAKN** trên **app Cư dân số**`).\n"
        "4. Nếu commit không chứa mã task Jira, hãy viết dạng: `* **[Tóm tắt chức năng bôi đậm]** [mô tả phụ]`.\n"
        "5. Chỉ trả về nội dung markdown của Release Notes (bắt đầu bằng tiêu đề `📌 **Release Notes – [Tên dự án]**`), tuyệt đối không viết lời dẫn, giải thích hay đặt trong thẻ code block ngoài cùng."
    )
    
    prompt = (
        f"Dự án: {project_name}\n"
        f"Danh sách commits:\n"
        f"{commits_text}\n\n"
        "Tạo tóm tắt Release Notes theo đúng định dạng yêu cầu:"
    )
    
    return _call(system, prompt)


def analyze_task_with_srs(task_data: dict, srs_context: str) -> str:
    """
    Sử dụng LLM để đối chiếu Jira task với tài liệu đặc tả SRS,
    phân tích tính khả thi và lập kế hoạch triển khai chi tiết.
    """
    system = (
        "Bạn là một Solution Architect kiêm Tech Lead giàu kinh nghiệm. "
        "Nhiệm vụ của bạn là đọc thông tin của một Jira Task (hoặc yêu cầu task phát triển phần mềm) "
        "và đối chiếu với tài liệu đặc tả yêu cầu hệ thống (SRS) được cung cấp để phân tích tính khả thi, "
        "mâu thuẫn logic nghiệp vụ, đồng thời đề xuất giải pháp thiết kế kỹ thuật chi tiết bằng tiếng Việt.\n\n"
        "Yêu cầu báo cáo phân tích phải đầy đủ, mạch lạc, trực quan, sử dụng Markdown của Telegram.\n"
        "Hãy tập trung phân tích sâu:\n"
        "1. Đánh giá tính khả thi & Mâu thuẫn nghiệp vụ (đặc biệt chỉ rõ nếu task vi phạm quy định nào trong SRS).\n"
        "2. Đề xuất thiết kế (Database schema mới/sửa đổi, API endpoints cần tạo/sửa, Business Logic chính).\n"
        "3. Kế hoạch triển khai (Step-by-step checklist cho Dev).\n"
        "4. Tác động phụ và rủi ro."
    )
    
    prompt = (
        f"=== TÀI LIỆU ĐẶC TẢ SRS LIÊN QUAN ===\n"
        f"{srs_context}\n"
        f"======================================\n\n"
        f"=== THÔNG TIN JIRA TASK CẦN PHÂN TÍCH ===\n"
        f"Mã Task: {task_data.get('key', 'N/A')}\n"
        f"Tiêu đề: {task_data.get('summary', 'N/A')}\n"
        f"Mô tả chi tiết: {task_data.get('description', 'N/A')}\n"
        f"Thảo luận/Bình luận: {task_data.get('comments_str', 'Không có')}\n"
        f"=========================================\n\n"
        f"Hãy tiến hành phân tích chi tiết và xuất báo cáo theo cấu trúc Markdown sau:\n\n"
        f"📋 **BÁO CÁO PHÂN TÍCH NGHIỆP VỤ & KỸ THUẬT (Jira & SRS)**\n"
        f"🎫 **Task:** `[Mã Task]` - [Tiêu đề Task]\n\n"
        f"⚖️ **1. ĐÁNH GIÁ TÍNH KHẢ THI & PHÙ HỢP NGHIỆP VỤ:**\n"
        f"- [Phân tích chi tiết khả thi/mâu thuẫn dựa trên SRS, sử dụng 🔴 Cảnh báo nếu mâu thuẫn]\n\n"
        f"⚙️ **2. GIẢI PHÁP THIẾT KẾ KỸ THUẬT:**\n"
        f"- 🗄️ **Database Schema:** [Thay đổi database, bảng biểu, cột]\n"
        f"- 🔌 **API Endpoints:** [Chi tiết REST API hoặc GraphQL: Method, Path, Payload]\n"
        f"- 🧠 **Business Logic:** [Luồng logic chính cần code ở backend]\n\n"
        f"📝 **3. KẾ HOẠCH TRIỂN KHAI CHO DEV (STEP-BY-STEP):**\n"
        f"- [ ] Bước 1: [Mô tả]\n"
        f"- [ ] Bước 2: [Mô tả]\n\n"
        f"⚠️ **4. TÁC ĐỘNG PHỤ & RỦI RO (SIDE EFFECTS):**\n"
        f"- [Các module bị ảnh hưởng, các trường hợp ngoại lệ cần lưu ý]"
    )
    
    return _call(system, prompt)


def generate_jira_estimate(task_text: str, historical_issues: list[dict], task_key: str = None) -> str:
    """
    Sử dụng LLM để ước lượng thời gian cho Jira task mới dựa trên lịch sử làm việc.
    """
    history_lines = []
    for idx, h in enumerate(historical_issues, 1):
        orig_h = h['orig'] // 3600
        spent_h = h['spent'] // 3600
        desc_truncated = h['description'][:200] + "..." if len(h['description']) > 200 else h['description']
        history_lines.append(
            f"{idx}. Task [{h['key']}]: {h['summary']}\n"
            f"   - Mô tả: {desc_truncated}\n"
            f"   - Estimate ban đầu: {orig_h}h | Thực tế tốn: {spent_h}h\n"
        )
    history_text = "\n".join(history_lines) if history_lines else "(Không có task lịch sử tham khảo)"

    target_desc = f"Mã Task: {task_key}\nNội dung: {task_text}" if task_key else f"Nội dung yêu cầu: {task_text}"

    system = (
        "Bạn là một Solution Architect kiêm Project Manager/Scrum Master dày dạn kinh nghiệm. "
        "Nhiệm vụ của bạn là đưa ra ước lượng thời gian (Original Estimate) tối ưu và phân rã các bước thực hiện "
        "cho một yêu cầu công việc mới, dựa vào danh sách các task lịch sử đã hoàn thành làm mốc so sánh hiệu suất thực tế.\n\n"
        "Hãy phân tích thật logic, chi tiết và thực tế:\n"
        "- So sánh độ phức tạp, quy mô nghiệp vụ, thiết kế kỹ thuật giữa task mới và các task cũ.\n"
        "- Xem xét chênh lệch giữa Estimate ban đầu và thời gian Thực tế tốn của các task cũ để đưa ra hệ số điều chỉnh sát thực tế nhất.\n"
        "- Đưa ra khoảng ước lượng đề xuất (Estimated Range) và số giờ cụ thể khuyên dùng để cấu hình Jira.\n"
        "Luôn phản hồi bằng tiếng Việt chuyên nghiệp, cấu trúc rõ ràng bằng Markdown."
    )

    prompt = (
        f"=== DANH SÁCH TASK LỊCH SỬ THAM KHẢO (ĐÃ DONE) ===\n"
        f"{history_text}\n"
        f"===================================================\n\n"
        f"=== THÔNG TIN YÊU CẦU TASK MỚI CẦN ESTIMATE ===\n"
        f"{target_desc}\n"
        f"===============================================\n\n"
        "Hãy tiến hành phân tích độ phức tạp và đưa ra đề xuất ước lượng theo định dạng cấu trúc sau:\n\n"
        "🤖 **AI ESTIMATION ASSISTANT**\n"
        "🎫 **Yêu cầu:** [Tóm tắt ngắn gọn tiêu đề task mới]\n\n"
        "⏱ **1. ƯỚC LƯỢNG ĐỀ XUẤT (RECOMMENDED ESTIMATE):**\n"
        "• **Khoảng ước lượng đề xuất (Estimated Range):** `[Số_giờ_min]h - [Số_giờ_max]h`\n"
        "• **Thời gian khuyên dùng (Recommended Value):** `[Số_giờ_đề_xuất]h`\n"
        "• **Độ tự tin (Confidence Level):** `[HIGH / MEDIUM / LOW]` - Lý do: [Tại sao tự tin ở mức này]\n\n"
        "📊 **2. PHÂN RÃ CÔNG VIỆC CHI TIẾT (WORK BREAKDOWN STRUCTURE):**\n"
        "(Gợi ý các bước triển khai chi tiết cho Dev kèm thời gian ước lượng của từng bước)\n"
        "• **[Bước 1]**: `[Số_giờ_bước_1]h` - [Mô tả chi tiết việc cần làm ở bước 1]\n"
        "• **[Bước 2]**: `[Số_giờ_bước_2]h` - [Mô tả chi tiết việc cần làm ở bước 2]\n"
        "• ...\n\n"
        "🔍 **3. ĐỐI CHIẾU VỚI LỊCH SỬ (HISTORICAL COMPARISON):**\n"
        "- [Phân tích điểm tương đồng và khác biệt về độ khó/quy mô giữa task mới này với 1-2 task Done trong lịch sử để chứng minh tính thực tế của con số đề xuất]\n\n"
        "💡 **4. LƯU Ý & RỦI RO ƯỚC LƯỢNG (RISKS & ASSUMPTIONS):**\n"
        "- [Các yếu tố không chắc chắn hoặc rủi ro công nghệ có thể làm đội thời gian lên, và giả định đi kèm]"
    )

    return _call(system, prompt)


def generate_weekly_velocity_report(
    user_name: str, 
    resolved_issues: list[dict], 
    active_issues: list[dict], 
    total_logged_seconds: int
) -> str:
    """
    Sử dụng LLM để phân tích hiệu suất làm việc hàng tuần (Weekly Dev Velocity Report) và đánh giá hiện tại.
    """
    resolved_lines = []
    for idx, r in enumerate(resolved_issues, 1):
        orig_h = r['orig'] // 3600
        spent_h = r['spent'] // 3600
        resolved_lines.append(f"• [{r['key']}]: {r['summary']} (Estimate: {orig_h}h | Logged: {spent_h}h | Trạng thái: {r['status']})")
    resolved_text = "\n".join(resolved_lines) if resolved_lines else "• Không có task nào hoàn thành Done trong tuần này."

    active_lines = []
    for idx, a in enumerate(active_issues, 1):
        orig_h = a['orig'] // 3600
        spent_h = a['spent'] // 3600
        rem_h = a['remaining'] // 3600
        duedate = a['duedate'] or "Chưa cấu hình"
        active_lines.append(
            f"• [{a['key']}]: {a['summary']}\n"
            f"  - Trạng thái: {a['status']} | Deadline: {duedate}\n"
            f"  - Est: {orig_h}h | Logged: {spent_h}h | Còn thiếu (Remaining): {rem_h}h"
        )
    active_text = "\n".join(active_lines) if active_lines else "• Không có task nào đang hoạt động (active) được gán."

    logged_hours = total_logged_seconds / 3600
    logged_hours_str = f"{logged_hours:.1f}h"

    system = (
        "Bạn là một Delivery Manager kiêm Agile Coach lão luyện. "
        "Nhiệm vụ của bạn là đọc báo cáo tổng hợp các task đã hoàn thành tuần này, các task đang chạy "
        "và tổng số giờ logwork thực tế của một Lập trình viên để tạo ra một bản báo cáo hiệu suất cá nhân hàng tuần (Weekly Dev Velocity Report) "
        "cực kỳ chuyên nghiệp, sâu sắc và khách quan.\n\n"
        "Hãy tập trung đánh giá chuyên môn:\n"
        "- Đánh giá Năng suất (Velocity): So sánh tổng số giờ Estimate của các task đã giải quyết xong đối chọi với tổng số giờ thực tế đã logwork tuần qua.\n"
        "- Đánh giá tính chuyên cần logwork: Dev có logwork đầy đủ cho các task, hay có dấu hiệu quên log/log lệch quá mức?\n"
        "- Đánh giá Tiến độ Hiện tại (Assessment to Date): Đánh giá rủi ro trễ deadline của các task đang chạy dựa trên Remaining Estimate và Due Date.\n"
        "Luôn phản hồi bằng tiếng Việt, thiết kế định dạng HTML/Markdown Telegram premium sinh động."
    )

    prompt = (
        f"=== BÁO CÁO HOẠT ĐỘNG JIRA CỦA: {user_name} ===\n"
        f"Tổng thời gian logwork thực tế ghi nhận tuần này: {logged_hours_str}\n\n"
        f"--- DANH SÁCH TASK ĐÃ DONE TUẦN NÀY (RESOLVED) ---\n"
        f"{resolved_text}\n\n"
        f"--- DANH SÁCH TASK ĐANG CHẠY (ACTIVE & TODO) ---\n"
        f"{active_text}\n"
        f"================================================\n\n"
        "Hãy tiến hành phân tích chi tiết hiệu năng và xuất báo cáo theo định dạng cấu trúc sau:\n\n"
        "📊 **WEEKLY DEV VELOCITY REPORT**\n"
        "👤 **Nhân sự:** [Họ tên / Account người thực hiện]\n"
        "⏱ **Tổng thời gian logwork tuần này:** `[Số_giờ_log_thực_tế]h`\n\n"
        "🚀 **1. ĐÁNH GIÁ NĂNG SUẤT TUẦN QUA (VELOCITY ASSESSMENT):**\n"
        "- [Phân tích xem tuần qua nhân sự làm việc hiệu quả không, tỉ lệ hoàn thành task so với estimate ban đầu thế nào, có giải quyết được các task trọng điểm không]\n\n"
        "⏰ **2. ĐỘ CHUYÊN CẦN & CHUẨN XÁC LOGWORK (LOGWORK DILIGENCE):**\n"
        "- [Phân tích tính chuyên cần logwork của dev. Họ có log đều đặn không, có task nào bị thiếu/quên log so với tiến độ thực tế không]\n\n"
        "🛡 **3. ĐÁNH GIÁ TIẾN ĐỘ ĐẾN HIỆN TẠI & RỦI RO TRỄ HẠN (ASSESSMENT TO DATE):**\n"
        "- [Phân tích chi tiết khối lượng công việc còn tồn đọng của các task đang chạy. Chỉ rõ các task có rủi ro trễ deadline (Overdue) kèm cảnh báo 🔴 (rủi ro cao) hoặc ⚠️ (rủi ro vừa) dựa vào Due Date và Remaining Estimate]\n\n"
        "💡 **4. KHUYẾN NGHỊ HÀNH ĐỘNG (ACTIONABLE RECOMMENDATIONS):**\n"
        "- [Gợi ý 2-3 hành động cụ thể để dev tối ưu hóa tiến độ làm việc, xử lý rủi ro trễ hạn hoặc cân bằng khối lượng công việc trong tuần kế tiếp]"
    )
 
    return _call(system, prompt)


def generate_architecture_design(requirement_text: str, srs_context: str) -> str:
    """
    Sử dụng LLM đóng vai trò Solution Architect để thiết kế hệ thống và cơ sở dữ liệu chi tiết.
    """
    system = (
        "Bạn là một Solution Architect kiêm Principal Engineer xuất sắc và dày dạn kinh nghiệm. "
        "Nhiệm vụ của bạn là đọc một yêu cầu thiết kế hệ thống mới từ lập trình viên (kèm bối cảnh tài liệu đặc tả SRS liên quan nếu có) "
        "để đưa ra một bản thiết kế giải pháp kỹ thuật, cấu trúc database và đặc tả API toàn diện, tối ưu và chuẩn mực nhất.\n\n"
        "YÊU CẦU QUAN TRỌNG VỀ TƯ DUY KIẾN TRÚC:\n"
        "1. Phân tích nghiệp vụ sâu sắc, phát hiện các điểm nghẽn về hiệu năng kỹ thuật ngay lập tức. "
        "Ví dụ, nếu yêu cầu đếm số lượng thông báo/nhắc việc chưa xử lý của 10 module khác nhau trên trang chủ (Home Page), "
        "chỉ rõ rằng việc chạy 10 câu truy vấn COUNT phức tạp trực tiếp trên database PostgreSQL/MySQL mỗi lần tải trang chủ sẽ làm thắt nút cổ chai hiệu năng của hệ thống. "
        "Đề xuất ngay giải pháp tối ưu: Xây dựng bảng tích lũy Badge (NotificationBadge) hoặc sử dụng Redis Hash Cache để lưu trữ số lượng badge hiện tại, "
        "và cập nhật số liệu này theo cơ chế Hướng sự kiện (Event-Driven) thông qua Message Queue (RabbitMQ/Kafka) hoặc gọi Webhook/Event Listener bất cứ khi nào có thay đổi trạng thái của module con.\n"
        "2. Thiết kế Database Schema chi tiết: Tên bảng, tên cột, kiểu dữ liệu, các ràng buộc (Primary Key, Foreign Key, Nullable), các Index khuyên dùng để tăng tốc độ truy vấn.\n"
        "3. Thiết kế REST API cụ thể: Method, Path, Header, Request Payload, Response Payload.\n"
        "4. Cung cấp sơ đồ Sequence Diagram hoặc Flowchart trực quan bằng mã Mermaid code block.\n"
        "Luôn phản hồi bằng tiếng Việt chuyên nghiệp, súc tích và sử dụng định dạng Markdown Telegram cao cấp."
    )

    prompt = (
        f"=== TÀI LIỆU ĐẶC TẢ SRS THAM KHẢO LIÊN QUAN ===\n"
        f"{srs_context or '(Không tìm thấy đặc tả SRS phù hợp trong bộ nhớ)'}\n"
        f"================================================\n\n"
        f"=== THÔNG TIN YÊU CẦU THIẾT KẾ MỚI ===\n"
        f"{requirement_text}\n"
        f"======================================\n\n"
        "Hãy tiến hành phân tích và xuất tài liệu thiết kế giải pháp kiến trúc hệ thống theo đúng cấu trúc định dạng sau:\n\n"
        "🏗️ **ARCHITECTURAL & SYSTEM DESIGN REPORT**\n"
        "🎫 **Chức năng:** [Tên chức năng / module được thiết kế]\n\n"
        "📐 **1. ĐÁNH GIÁ NGHIỆP VỤ & PHÂN TÍCH KIẾN TRÚC (ARCHITECTURAL ANALYSIS):**\n"
        "- **Phân tích nghiệp vụ**: [Phân tích ngắn gọn luồng xử lý và các chức năng con cần nhắc việc]\n"
        "- **🔴 Cảnh báo Hiệu năng & Giải pháp**: [Đặc biệt chỉ rõ điểm nghẽn hiệu năng khi truy vấn đếm badge thời gian thực từ 10 module con và giải pháp tối ưu bằng cách dùng bảng tập trung (Notification Badge table) + Redis Cache kết hợp Event-Driven (Pub/Sub hoặc Event Listeners) để cập nhật số đếm]\n\n"
        "🗄️ **2. THIẾT KẾ CƠ SỞ DỮ LIỆU (DATABASE SCHEMA DESIGN):**\n"
        "(Liệt kê cấu trúc bảng biểu chi tiết, ví dụ bảng `user_notification_badges`, các bảng liên quan)\n"
        "```sql\n"
        "-- [Mã SQL DDL hoặc mô tả cấu trúc bảng, cột, kiểu dữ liệu, index cụ thể]\n"
        "```\n\n"
        "🔌 **3. ĐẶC TẢ REST API ENDPOINTS (API SPECIFICATION):**\n"
        "• **API 1: [Tên API, ví dụ: Lấy danh sách số đếm chuông thông báo]**\n"
        "  - **Method / Path:** `GET /api/v1/notification-badges`\n"
        "  - **Request Header:** `Authorization: Bearer <token>`\n"
        "  - **Response Payload (JSON):**\n"
        "```json\n"
        "// [JSON mẫu]\n"
        "```\n"
        "• **API 2: [Tên API, ví dụ: Đánh dấu đã đọc/xử lý một sự kiện]**\n"
        "  - **Method / Path:** ...\n\n"
        "🔄 **4. SƠ ĐỒ LUỒNG DỮ LIỆU (DATA FLOW & SEQUENCE DIAGRAM):**\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "  [Mã sơ đồ Sequence Diagram hoặc Flowchart thể hiện luồng cập nhật Badge khi một module thay đổi trạng thái và client fetch dữ liệu Home Page]\n"
        "```\n\n"
        "💡 **5. ĐỀ XUẤT CÔNG NGHỆ & CHIẾN LƯỢC TRIỂN KHAI:**\n"
        "- **Tech Stack**: [Đề xuất các công cụ, ví dụ: PostgreSQL, Redis, Event-driven listener]\n"
        "- **Chiến lược kiểm thử & Rollout**: [Các trường hợp kiểm thử biên (edge cases) và kế hoạch rollout an toàn]"
    )

    return _call(system, prompt)