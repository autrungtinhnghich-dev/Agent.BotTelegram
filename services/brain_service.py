import logging
import json
import pypdf
import os
import base64
import requests
import asyncio
from services.journal_db import add_knowledge, search_knowledge, search_srs_knowledge
import services.summarizer as summarizer
from config import LLM_API_URL, LLM_API_KEY, LLM_MODEL

logger = logging.getLogger(__name__)

async def process_and_save_text(user_id: int, text: str, source: str = "message"):
    """Phân tích text, trích xuất tag và lưu vào DB."""
    if not text or len(text.strip()) < 10:
        return None
    
    # AI trích xuất tag hoặc tóm tắt ngắn (tùy chọn)
    # Ở đây ta đơn giản là lưu toàn bộ, AI sẽ xử lý khi query
    tags = ""
    try:
        # Giả sử ta có một hàm trích xuất tag đơn giản từ summarizer
        # tags = await summarizer.extract_tags(text)
        pass
    except Exception:
        pass
        
    kb_id = await add_knowledge(user_id, text, source, tags)
    return kb_id

async def process_pdf_file(user_id: int, file_path: str, file_name: str):
    """Đọc file PDF dùng pypdf, chia nhỏ nội dung và lưu vào DB."""
    try:
        reader = pypdf.PdfReader(file_path)
        full_text = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
        
        if not full_text.strip():
            return 0
            
        # Chia nhỏ text theo đoạn (ví dụ mỗi 1000 ký tự) để search hiệu quả hơn
        chunk_size = 1500
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        saved_count = 0
        for chunk in chunks:
            if len(chunk.strip()) > 50:
                await add_knowledge(user_id, chunk, source=f"file: {file_name}")
                saved_count += 1
                
        return saved_count
    except Exception as e:
        logger.error(f"Lỗi khi xử lý PDF: {e}")
        return -1

def extract_text_from_docx(file_path: str) -> str:
    """Trích xuất văn bản thô từ file DOCX bằng cách đọc trực tiếp xml từ file zip."""
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        with zipfile.ZipFile(file_path) as z:
            doc_xml = z.read("word/document.xml")
            root = ET.fromstring(doc_xml)
            # Namespace mapping của OpenXML Word Document
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = []
            for p in root.findall('.//w:p', namespaces):
                texts = [t.text for t in p.findall('.//w:t', namespaces) if t.text]
                if texts:
                    paragraphs.append("".join(texts))
            return "\n".join(paragraphs)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file DOCX {file_path}: {e}")
        return ""

async def process_single_srs_file(user_id: int, file_path: str, file_name: str) -> int:
    """Đọc một file đặc tả SRS riêng lẻ (PDF, DOCX hoặc Text) và lưu vào database."""
    try:
        ext = os.path.splitext(file_name.lower())[1]
        full_text = ""
        
        if ext == ".pdf":
            reader = pypdf.PdfReader(file_path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        elif ext == ".docx":
            full_text = extract_text_from_docx(file_path)
        else:
            # Xử lý các file văn bản thường (.txt, .md, v.v.)
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                full_text = f.read()
                
        if not full_text.strip():
            return 0
            
        # Chia nhỏ text
        chunk_size = 1500
        chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        saved_count = 0
        for chunk in chunks:
            if len(chunk.strip()) > 50:
                await add_knowledge(user_id, chunk, source=f"srs:{file_name}", tags="srs")
                saved_count += 1
                
        return saved_count
    except Exception as e:
        logger.error(f"Lỗi khi xử lý file đặc tả {file_name}: {e}")
        return 0

async def process_srs_file(user_id: int, file_path: str, file_name: str) -> int:
    """Đọc file đặc tả SRS (PDF, DOCX, Text hoặc ZIP tự động giải nén) và lưu vào DB."""
    import zipfile
    import shutil
    import tempfile
    
    ext = os.path.splitext(file_name.lower())[1]
    
    if ext == ".zip":
        saved_count = 0
        temp_dir = tempfile.mkdtemp(dir="scratch")
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
                
            # Duyệt đệ quy tất cả các file trong folder giải nén
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    sub_file_path = os.path.join(root, f)
                    sub_file_name = f
                    sub_ext = os.path.splitext(f.lower())[1]
                    # Chỉ xử lý các định dạng tài liệu được hỗ trợ
                    if sub_ext in (".pdf", ".txt", ".md", ".docx"):
                        count = await process_single_srs_file(user_id, sub_file_path, f"{file_name}/{sub_file_name}")
                        if count > 0:
                            saved_count += count
            return saved_count
        except Exception as e:
            logger.error(f"Lỗi giải nén ZIP SRS: {e}")
            return -1
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        return await process_single_srs_file(user_id, file_path, file_name)

async def process_image_file(user_id: int, file_path: str, file_name: str):
    """Đọc file ảnh, sử dụng LLM Vision API để trích xuất text/mô tả nội dung và lưu vào DB."""
    try:
        # 1. Đọc file ảnh và chuyển sang base64
        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            
        # Xác định mime type
        ext = os.path.splitext(file_name.lower())[1]
        mime_type = "image/jpeg"
        if ext == ".png":
            mime_type = "image/png"
        elif ext == ".webp":
            mime_type = "image/webp"
        elif ext == ".gif":
            mime_type = "image/gif"

        # 2. Chuẩn bị payload gửi lên LLM
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        
        system_prompt = (
            "Bạn là một trợ lý phân tích hình ảnh chuyên sâu và cực kỳ tỉ mỉ. "
            "Nhiệm vụ của bạn là trích xuất và phân tích toàn bộ thông tin trong hình ảnh được cung cấp một cách ĐẦY ĐỦ, CHI TIẾT và TOÀN DIỆN nhất có thể để lưu trữ vào bộ nhớ dài hạn của hệ thống. "
            "Tuyệt đối không được tóm tắt sơ sài, không được bỏ qua bất kỳ chi tiết hay chữ nào trong ảnh. "
            "Hãy trình bày thông tin theo các nguyên tắc sau bằng tiếng Việt:\n"
            "1. TRÍCH XUẤT VĂN BẢN (OCR): Trích xuất chính xác từng từ, từng câu, từng con số xuất hiện trên ảnh (kể cả chữ nhỏ, nhãn biểu đồ, thông tin bản quyền, tiêu đề phụ). Giữ nguyên định dạng hoặc ghi lại chi tiết.\n"
            "2. PHÂN TÍCH CẤU TRÚC & SƠ ĐỒ: Nếu ảnh là sơ đồ, quy trình, bản đồ kiến trúc hệ thống, hãy mô tả chi tiết từng thực thể, mối liên kết, hướng mũi tên và toàn bộ luồng xử lý từ đầu đến cuối.\n"
            "3. BẢNG BIỂU & DỮ LIỆU: Nếu có bảng số liệu hoặc biểu đồ, hãy liệt kê đầy đủ toàn bộ các hàng, cột, nhãn trục và giá trị của từng điểm dữ liệu cụ thể để tránh mất mát dữ liệu.\n"
            "4. ẢNH CHỤP MÀN HÌNH / GIAO DIỆN / CODE: Mô tả chi tiết giao diện, các nút chức năng, trạng thái hiển thị, các đoạn mã code xuất hiện (nếu có) hoặc thông tin hội thoại.\n"
            "Hãy trình bày một cách khoa học, mạch lạc bằng Markdown để bộ nhớ RAG có thể tìm kiếm và tái hiện thông tin chính xác nhất sau này."
        )
        
        user_content = [
            {
                "type": "text",
                "text": "Hãy phân tích hình ảnh này thật chi tiết, trích xuất toàn bộ chữ (OCR) chính xác và mô tả đầy đủ toàn bộ nội dung, cấu trúc, số liệu xuất hiện trong ảnh mà không bỏ sót bất kỳ thông tin nào."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{encoded_string}"
                }
            }
        ]
        
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 4096
        }
        
        # Gọi API (chạy trong executor vì requests là blocking)
        loop = asyncio.get_event_loop()
        
        def _call_api():
            response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()
            
        logger.info(f"Đang phân tích hình ảnh {file_name} qua LLM API...")
        data = await loop.run_in_executor(None, _call_api)
        
        # Trích xuất content
        content = ""
        if "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "message" in data:
            content = data["message"]
        elif "content" in data:
            content = data["content"]
        elif "response" in data:
            content = data["response"]
            
        if not content or not content.strip():
            return 0
            
        # 3. Lưu nội dung trích xuất được vào bộ nhớ
        # Chia nhỏ text nếu quá dài
        chunk_size = 1500
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
        
        saved_count = 0
        for chunk in chunks:
            if len(chunk.strip()) > 10:
                await add_knowledge(user_id, chunk, source=f"ảnh: {file_name}")
                saved_count += 1
                
        return saved_count
        
    except Exception as e:
        logger.error(f"Lỗi khi xử lý file ảnh: {e}")
        return -1

async def ask_brain(user_id: int, question: str):
    """Tìm kiếm kiến thức liên quan và trả lời câu hỏi."""
    # 1. Tìm từ khóa từ câu hỏi (AI có thể giúp trích xuất keyword tốt hơn)
    # Ở đây ta dùng query trực tiếp từ user
    results = await search_knowledge(question, limit=5)
    
    if not results:
        # Thử tìm kiếm lỏng lẻo hơn bằng cách tách từ (nếu cần)
        keywords = question.split()
        if len(keywords) > 1:
            results = await search_knowledge(keywords[0], limit=3)
            
    if not results:
        return "Xin lỗi, mình không tìm thấy thông tin nào liên quan trong bộ nhớ của bạn."

    # 2. Xây dựng context cho LLM
    context_parts = []
    for r in results:
        context_parts.append(f"--- Nguồn: {r['source']} ({r['created_at']}) ---\n{r['content']}")
    
    context_text = "\n\n".join(context_parts)
    
    # 3. Gọi AI để tổng hợp câu trả lời
    try:
        answer = summarizer.answer_from_brain(context_text, question)
        return answer
    except Exception as e:
        logger.error(f"Lỗi khi gọi AI trả lời từ brain: {e}")
        return f"Mình tìm thấy một số thông tin nhưng gặp lỗi khi tổng hợp: \n\n{results[0]['content'][:200]}..."


async def ask_brain_with_history(user_id: int, question: str, history: list[dict]):
    """Tìm kiếm kiến thức liên quan và trả lời câu hỏi kèm lịch sử hội thoại."""
    # 1. Tìm từ khóa từ câu hỏi hiện tại
    results = await search_knowledge(question, limit=5)
    
    if not results:
        keywords = question.split()
        if len(keywords) > 1:
            results = await search_knowledge(keywords[0], limit=3)
            
    # 2. Xây dựng context cho LLM
    context_parts = []
    if results:
        for r in results:
            context_parts.append(f"--- Nguồn: {r['source']} ({r['created_at']}) ---\n{r['content']}")
            
    context_text = "\n\n".join(context_parts) if context_parts else "Không tìm thấy thông tin nào liên quan trực tiếp trong bộ nhớ."
    
    # 3. Gọi AI để tổng hợp câu trả lời kèm history
    try:
        from services.summarizer import answer_from_brain_with_history
        answer = answer_from_brain_with_history(history, context_text, question)
        return answer
    except Exception as e:
        logger.error(f"Lỗi khi gọi AI trả lời từ brain với history: {e}")
        if results:
            return f"Mình tìm thấy thông tin liên quan nhưng gặp lỗi tổng hợp: \n\n{results[0]['content'][:200]}..."
        return "Mình gặp lỗi khi truy vấn bộ não."

