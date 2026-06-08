import logging
import uuid
import asyncio
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from config import ALLOWED_USER_IDS
from services.markdown import escape, bold, code, build, italic, ai_to_mdv2
from services.telegram_utils import send_message_safe
from services.search_service import search_duckduckgo
from services.scraper_service import scrape_web_link
from services.summarizer import _call
from services.journal_db import create_delegate_task, update_delegate_task, get_delegate_tasks, add_knowledge

logger = logging.getLogger(__name__)

def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized delegate access attempt: {user_id}")
            return
        return await fn(update, context)
    return wrapper

@require_auth
async def cmd_delegate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu một nhiệm vụ nghiên cứu chạy ngầm mới."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = " ".join(context.args) if context.args else ""
    
    if not text:
        await send_message_safe(
            context.bot,
            chat_id,
            build(
                bold("🤖 Trợ Lý Nghiên Cứu Chạy Ngầm (AI Task Delegator)"),
                "",
                bold("Cú pháp:"),
                code("/delegate <chủ đề cần nghiên cứu>"),
                "",
                "Ví dụ: `/delegate Hướng dẫn thiết lập Redis Sentinel chi tiết`"
            ),
            parse_mode="HTML"
        )
        return

    topic = text.strip()
    task_id = uuid.uuid4().hex[:8]
    
    try:
        # 1. Lưu task vào DB với trạng thái 'running'
        await create_delegate_task(task_id, user_id, topic)
        
        # 2. Phản hồi nhanh cho người dùng
        await send_message_safe(
            context.bot,
            chat_id,
            build(
                f"🚀 {bold('Đã nhận nhiệm vụ nghiên cứu chạy ngầm!')}",
                f"📍 ID nhiệm vụ: {code(task_id)}",
                f"📝 Chủ đề: {italic(escape(topic))}",
                "",
                "Tôi đang tìm kiếm tài liệu từ Internet và tổng hợp báo cáo. Quá trình này có thể mất 1-3 phút. Bạn sẽ nhận được báo cáo ngay sau khi hoàn thành!"
            ),
            parse_mode="HTML"
        )
        
        # 3. Kích hoạt task chạy ngầm
        asyncio.create_task(run_research_task(chat_id, task_id, user_id, topic, context.bot))
        
    except Exception as e:
        logger.error(f"Lỗi khi khởi tạo task delegate: {e}", exc_info=True)
        await send_message_safe(context.bot, chat_id, f"❌ Không thể tạo nhiệm vụ nghiên cứu: {e}")

async def run_research_task(chat_id: int, task_id: str, user_id: int, topic: str, bot):
    """Hàm chạy ngầm thực hiện tìm kiếm, cào web và tổng hợp báo cáo."""
    logger.info(f"Khởi chạy Task nghiên cứu ngầm: ID={task_id}, Topic={topic}")
    
    try:
        # Bước 1: Tìm kiếm link qua DuckDuckGo
        search_results = search_duckduckgo(topic, limit=4)
        if not search_results:
            # Thử tìm lại với câu ngắn hơn
            keywords = " ".join(topic.split()[:5])
            search_results = search_duckduckgo(keywords, limit=4)
            
        if not search_results:
            raise RuntimeError("Không tìm thấy kết quả tìm kiếm nào liên quan trên internet.")
            
        # Bước 2: Cào nội dung từ các link
        scraped_data = []
        source_links = []
        
        for idx, res in enumerate(search_results):
            url = res["url"]
            title = res["title"]
            logger.info(f"Đang cào link [{idx+1}]: {url}")
            try:
                # Cào content
                _, content = scrape_web_link(url)
                if content and len(content.strip()) > 200:
                    scraped_data.append(f"--- Nguồn {idx+1}: {title} ({url}) ---\n{content[:4000]}")
                    source_links.append(f"- [{title}]({url})")
            except Exception as scrape_err:
                logger.warning(f"Lỗi khi cào link {url}: {scrape_err}")
                
        if not scraped_data:
            raise RuntimeError("Không thể cào hoặc đọc được nội dung từ các đường link tìm thấy.")
            
        # Bước 3: Tổng hợp tài liệu thô thành ngữ cảnh
        context_text = "\n\n".join(scraped_data)
        
        # Bước 4: Gọi LLM tổng hợp báo cáo chi tiết
        system_prompt = (
            "Bạn là một trợ lý nghiên cứu và chuyên gia công nghệ chuyên sâu. "
            "Nhiệm vụ của bạn là đọc các nội dung tài liệu cào được từ Internet và viết một BÁO CÁO NGHIÊN CỨU CHI TIẾT, ĐẦY ĐỦ, TOÀN DIỆN nhất có thể về chủ đề được yêu cầu. "
            "Bản báo cáo phải được viết bằng tiếng Việt, cấu trúc rõ ràng bằng Markdown."
        )
        
        user_prompt = (
            f"Chủ đề nghiên cứu: {topic}\n\n"
            f"Dưới đây là các tài liệu thu thập được từ Internet:\n\n"
            f"{context_text}\n\n"
            f"Hãy viết một bản báo cáo nghiên cứu chi tiết theo cấu trúc chính xác sau:\n"
            f"1. 📝 TIÊU ĐỀ BÁO CÁO (Nêu rõ chủ đề)\n"
            f"2. 📌 TỔNG QUAN (TL;DR) (Tóm tắt cực gọn trong 3-4 câu)\n"
            f"3. 🔑 CÁC KHÁI NIỆM & KIẾN THỨC CỐT LÕI (Giải thích cặn kẽ các thuật ngữ, nguyên lý hoạt động)\n"
            f"4. 🛠️ HƯỚNG DẪN CÀI ĐẶT / TRIỂN KHAI / THIẾT LẬP (Từng bước chi tiết, có ví dụ cấu hình hoặc mã nguồn mẫu thực tế nếu có)\n"
            f"5. ⚖️ ƯU ĐIỂM, NHƯỢC ĐIỂM & ĐÁNH GIÁ (So sánh với giải pháp khác nếu có)\n"
            f"6. 🔗 NGUỒN THAM KHẢO (Liệt kê chính xác danh sách các link nguồn đã dùng)\n\n"
            f"Hãy trình bày chuyên nghiệp, khoa học và giàu thông tin."
        )
        
        logger.info(f"Đang gửi dữ liệu cào được lên LLM để viết báo cáo...")
        report_content = _call(system_prompt, user_prompt)
        
        if not report_content or len(report_content.strip()) < 100:
            raise RuntimeError("LLM trả về kết quả quá ngắn hoặc rỗng.")
            
        # Bước 5: Tạo tóm tắt ngắn từ báo cáo để gửi qua chat Telegram
        summary_prompt = (
            f"Dưới đây là báo cáo nghiên cứu về chủ đề '{topic}':\n\n{report_content[:3000]}\n\n"
            f"Hãy viết một bản tóm tắt cực ngắn (dưới 600 ký tự) liệt kê 3-4 điểm mấu chốt quan trọng nhất của báo cáo này."
        )
        logger.info("Đang tạo tóm tắt ngắn...")
        short_summary = _call("Bạn là trợ lý tóm tắt.", summary_prompt)
        
        # Bước 6: Lưu báo cáo vào Database Kiến thức cá nhân (Personal Brain)
        kb_source = f"delegate:{task_id}:{topic}"
        await add_knowledge(user_id, report_content, source=kb_source, tags="research," + ",".join(topic.lower().split()))
        
        # Bước 7: Lưu báo cáo vào tệp tin Markdown (.md) tạm thời
        os.makedirs("scratch", exist_ok=True)
        file_path = f"scratch/research_{task_id}.md"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# BÁO CÁO NGHIÊN CỨU: {topic.upper()}\n")
            f.write(f"ID Nhiệm vụ: {task_id}\n")
            f.write(f"Thời gian: {os.popen('date').read().strip()}\n\n")
            f.write(report_content)
            
        # Bước 8: Cập nhật trạng thái 'completed' vào DB
        await update_delegate_task(task_id, "completed", result_summary=short_summary, result_file_path=file_path)
        
        # Bước 9: Gửi thông báo và tệp tin báo cáo cho người dùng
        # 9.1 Gửi tin nhắn tóm tắt
        success_msg = build(
            f"✅ {bold('Nhiệm vụ nghiên cứu hoàn thành!')}",
            f"📍 ID: {code(task_id)}",
            f"📝 Chủ đề: {italic(escape(topic))}",
            "",
            f"💡 {bold('Tóm tắt kết quả nghiên cứu:')}",
            ai_to_mdv2(short_summary),
            "",
            "📄 Báo cáo chi tiết dạng Markdown (.md) đã được gửi đính kèm bên dưới và tự động lưu vào bộ nhớ Brain.",
            f"Bạn có thể dùng lệnh {code('/ask')} để hỏi đáp thêm về chủ đề này bất cứ lúc nào!"
        )
        await send_message_safe(bot, chat_id, success_msg, parse_mode="HTML")
        
        # 9.2 Gửi file tài liệu đính kèm
        if os.path.exists(file_path):
            with open(file_path, "rb") as doc_file:
                await bot.send_document(
                    chat_id=chat_id,
                    document=doc_file,
                    filename=f"research_{task_id}.md",
                    caption=f"Báo cáo chi tiết: {topic}"
                )
            # Xóa file tạm
            os.remove(file_path)
            
    except Exception as err:
        logger.error(f"Lỗi trong quá trình chạy task nghiên cứu ngầm {task_id}: {err}", exc_info=True)
        # Cập nhật trạng thái 'failed' vào DB
        await update_delegate_task(task_id, "failed", result_summary=str(err))
        # Thông báo cho người dùng
        err_msg = build(
            f"❌ {bold('Nhiệm vụ nghiên cứu thất bại!')}",
            f"📍 ID: {code(task_id)}",
            f"📝 Chủ đề: {italic(escape(topic))}",
            "",
            f"Lỗi: {escape(str(err))}"
        )
        await send_message_safe(bot, chat_id, err_msg, parse_mode="HTML")

@require_auth
async def cmd_delegates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem danh sách các task nghiên cứu gần đây."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    try:
        tasks = await get_delegate_tasks(user_id, limit=10)
        
        if not tasks:
            await send_message_safe(context.bot, chat_id, "ℹ️ Bạn chưa tạo nhiệm vụ nghiên cứu chạy ngầm nào.")
            return
            
        lines = [bold("📋 Danh sách nhiệm vụ nghiên cứu gần đây:"), ""]
        for t in tasks:
            status_emoji = "⏳" if t["status"] == "running" else "✅" if t["status"] == "completed" else "❌"
            status_text = "Đang chạy" if t["status"] == "running" else "Hoàn thành" if t["status"] == "completed" else "Thất bại"
            
            created_dt = t["created_at"][:16].replace("T", " ")
            lines.append(
                f"{status_emoji} ID: {code(t['id'])} | {bold(escape(t['topic']))}\n"
                f"   Trạng thái: {status_text} | Tạo lúc: {created_dt}"
            )
            
        await send_message_safe(context.bot, chat_id, "\n".join(lines), parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách task delegate: {e}", exc_info=True)
        await send_message_safe(context.bot, chat_id, f"❌ Không thể tải danh sách nhiệm vụ: {e}")

def register_delegate_handlers(app):
    """Đăng ký handlers với Telegram Application."""
    app.add_handler(CommandHandler("delegate", cmd_delegate))
    app.add_handler(CommandHandler("delegates", cmd_delegates))
    logger.info("✅ Đã đăng ký AI Task Delegator handlers (/delegate, /delegates)")
