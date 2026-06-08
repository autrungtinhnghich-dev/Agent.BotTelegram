import logging
import os
import re
import hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from services.scraper_service import extract_youtube_video_id, get_youtube_transcript, scrape_web_link, get_youtube_video_title
from services.summarizer import summarize_youtube_video, summarize_web_article
from services.brain_service import process_and_save_text
from services.markdown import escape, bold, italic, code, build, ai_to_mdv2
from services.telegram_utils import send_message_safe, edit_message_safe
from config import ALLOWED_USER_IDS

logger = logging.getLogger(__name__)

def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            return
        return await fn(update, context)
    return wrapper

# URL regex
URL_REGEX = r"https?://[^\s]+"

@require_auth
async def cmd_sumlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /sumlink để tóm tắt trực tiếp một URL."""
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            build(
                bold("Cú pháp:"),
                code("/sumlink <đường dẫn URL>"),
                "",
                "Hỗ trợ cả link bài viết thông thường và link video YouTube."
            ),
            parse_mode="HTML"
        )
        return

    url = args[0].strip()
    await process_url_summary(update.effective_message, url, context)

async def process_url_summary(message, url: str, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tải và tóm tắt link."""
    status_msg = await message.reply_text("⏳ Đang kết nối và tải nội dung từ đường dẫn...")
    
    try:
        video_id = extract_youtube_video_id(url)
        
        if video_id:
            await status_msg.edit_text("🎥 Phát hiện video YouTube. Đang tải phụ đề...")
            try:
                transcript = get_youtube_transcript(video_id)
                
                if not transcript or len(transcript.strip()) < 50:
                    raise Exception("Không tìm thấy dữ liệu phụ đề.")
                    
                await status_msg.edit_text("⏳ Đang nhờ AI phân tích và tóm tắt video...")
                summary = summarize_youtube_video(video_id, transcript)
                
                # Lưu trữ dữ liệu tạm để lưu vào Brain nếu user bấm nút
                save_key = f"yt_{video_id}"
                context.user_data[save_key] = {
                    "title": f"YouTube video: {video_id}",
                    "content": transcript,
                    "summary": summary,
                    "url": url
                }
                
                keyboard = [
                    [
                        InlineKeyboardButton("🧠 Lưu phụ đề vào Brain", callback_data=f"scr:save_full:{save_key}"),
                        InlineKeyboardButton("🧠 Lưu tóm tắt vào Brain", callback_data=f"scr:save_sum:{save_key}")
                    ],
                    [InlineKeyboardButton("❌ Bỏ qua", callback_data="scr:cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await edit_message_safe(
                    bot=context.bot,
                    chat_id=status_msg.chat_id,
                    message_id=status_msg.message_id,
                    text=ai_to_mdv2(summary),
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            except Exception as yt_err:
                logger.warning(f"Không thể tải phụ đề YouTube cho {video_id}, chuyển sang chế độ oEmbed fallback: {yt_err}")
                title = get_youtube_video_title(video_id)
                error_msg = str(yt_err)
                
                keyboard = [
                    [InlineKeyboardButton("🧠 Lưu tiêu đề vào Brain", callback_data=f"scr:save_title:{video_id}")],
                    [InlineKeyboardButton("❌ Bỏ qua", callback_data="scr:cancel")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Cache tiêu đề
                save_key = f"yt_title_{video_id}"
                context.user_data[save_key] = {
                    "title": title,
                    "url": url
                }
                
                await edit_message_safe(
                    bot=context.bot,
                    chat_id=status_msg.chat_id,
                    message_id=status_msg.message_id,
                    text=(
                        f"⚠️ *Không tải được phụ đề YouTube*:\n"
                        f"{escape(error_msg)}\n\n"
                        f"📌 *Tiêu đề video*: {escape(title)}\n\n"
                        f"Bạn có muốn lưu liên kết và tiêu đề video này vào bộ nhớ không?"
                    ),
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            
        else:
            await status_msg.edit_text("📄 Phát hiện link bài viết. Đang cào văn bản...")
            title, clean_text = scrape_web_link(url)
            
            if not clean_text or len(clean_text.strip()) < 100:
                await status_msg.edit_text("❌ Không thể trích xuất đủ văn bản nội dung từ trang web này.")
                return
                
            await status_msg.edit_text("⏳ Đang nhờ AI phân tích và tóm tắt bài viết...")
            summary = summarize_web_article(title, clean_text)
            
            # Tạo unique key cho link bài viết
            url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
            save_key = f"web_{url_hash}"
            context.user_data[save_key] = {
                "title": title,
                "content": clean_text,
                "summary": summary,
                "url": url
            }
            
            keyboard = [
                [
                    InlineKeyboardButton("🧠 Lưu bài viết vào Brain", callback_data=f"scr:save_full:{save_key}"),
                    InlineKeyboardButton("🧠 Lưu tóm tắt vào Brain", callback_data=f"scr:save_sum:{save_key}")
                ],
                [InlineKeyboardButton("❌ Bỏ qua", callback_data="scr:cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await edit_message_safe(
                bot=context.bot,
                chat_id=status_msg.chat_id,
                message_id=status_msg.message_id,
                text=ai_to_mdv2(summary),
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Lỗi khi xử lý link {url}: {e}")
        await status_msg.edit_text(f"❌ Đã xảy ra lỗi: {escape(str(e))}")

@require_auth
async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt các tin nhắn dạng text chứa URL trong private chat để gợi ý tóm tắt/học."""
    message = update.effective_message
    
    # Chỉ hoạt động trong chat riêng tư (Direct Message)
    if not update.effective_chat.type == "private":
        return
        
    # Đề phòng đang ở trong chế độ chat liên tục hoặc đang hỏi bộ não
    from handlers.commands import _chat_mode_users
    if update.effective_user.id in _chat_mode_users:
        return
        
    if context.user_data.get("in_brain_ask"):
        return
        
    text = message.text or ""
    urls = re.findall(URL_REGEX, text)
    if not urls:
        return
        
    url = urls[0].strip()
    
    # Lưu URL vào cache để callback sử dụng
    msg_id = message.message_id
    context.user_data[f"detected_url_{msg_id}"] = url
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Tóm tắt nội dung", callback_data=f"scr:action_sum:{msg_id}"),
            InlineKeyboardButton("🧠 Học thẳng vào Brain", callback_data=f"scr:action_learn:{msg_id}")
        ],
        [InlineKeyboardButton("❌ Bỏ qua", callback_data=f"scr:action_ignore:{msg_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        escape("🔗 Mình phát hiện bạn gửi link:\n") + code(escape(url)) + escape("\nBạn muốn mình làm gì với link này?"),
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def cb_scraper_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các callback liên quan đến scraper và lưu trữ."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    action = data[1]
    
    # Hủy/Bỏ qua chung
    if action == "cancel":
        await query.message.delete()
        return
        
    # --- Nhóm 1: Phát hiện link tự động ---
    if action.startswith("action_"):
        msg_id = int(data[2])
        url = context.user_data.get(f"detected_url_{msg_id}")
        
        if not url:
            await query.edit_message_text("❌ Lỗi: Phiên xử lý link đã hết hạn.")
            return
            
        sub_action = action.split("_")[1]
        
        if sub_action == "ignore":
            await query.message.delete()
            context.user_data.pop(f"detected_url_{msg_id}", None)
            return
            
        if sub_action == "sum":
            # Tóm tắt link
            await query.message.delete()
            await process_url_summary(query.message, url, context)
            context.user_data.pop(f"detected_url_{msg_id}", None)
            
        elif sub_action == "learn":
            # Học thẳng vào brain không cần tóm tắt
            await query.edit_message_text("⏳ Đang tải và phân tích dữ liệu để lưu vào bộ não...")
            try:
                video_id = extract_youtube_video_id(url)
                if video_id:
                    transcript = get_youtube_transcript(video_id)
                    if not transcript or len(transcript.strip()) < 50:
                        await query.edit_message_text("❌ Không tìm thấy phụ đề của video để học.")
                        return
                    # Lưu transcript vào brain
                    await process_and_save_text(update.effective_user.id, transcript, source=f"youtube: {url}")
                    await query.edit_message_text(f"✅ Đã tải phụ đề video YouTube và lưu vào bộ nhớ RAG!")
                else:
                    title, clean_text = scrape_web_link(url)
                    if not clean_text or len(clean_text.strip()) < 100:
                        await query.edit_message_text("❌ Không thể cào văn bản từ trang web này để học.")
                        return
                    # Chia nhỏ và lưu tương tự PDF
                    chunk_size = 1500
                    chunks = [clean_text[i:i+chunk_size] for i in range(0, len(clean_text), chunk_size)]
                    
                    saved_count = 0
                    for chunk in chunks:
                        if len(chunk.strip()) > 50:
                            from services.journal_db import add_knowledge
                            await add_knowledge(update.effective_user.id, chunk, source=f"web: {title} ({url})")
                            saved_count += 1
                            
                    await query.edit_message_text(f"✅ Đã học xong bài viết! Lưu được {saved_count} đoạn vào bộ nhớ.")
            except Exception as e:
                logger.error(f"Lỗi khi học nhanh link: {e}")
                await query.edit_message_text(f"❌ Thất bại: {escape(str(e))}")
            
            context.user_data.pop(f"detected_url_{msg_id}", None)
            
    # --- Nhóm 2: Lưu sau khi tóm tắt ---
    elif action == "save_title":
        video_id = data[2]
        save_key = f"yt_title_{video_id}"
        cached_data = context.user_data.get(save_key)
        if not cached_data:
            await query.edit_message_text("❌ Lỗi: Dữ liệu tạm đã hết hạn.")
            return
            
        title = cached_data["title"]
        url = cached_data["url"]
        
        await query.edit_message_text("⏳ Đang lưu vào bộ não...")
        try:
            from services.journal_db import add_knowledge
            content = f"Video YouTube: {title}\nĐường dẫn: {url}"
            await add_knowledge(update.effective_user.id, content, source=f"youtube_link: {title}")
            await query.edit_message_text(f"✅ Đã lưu liên kết video vào bộ nhớ cá nhân:\n* {title}")
            context.user_data.pop(save_key, None)
        except Exception as e:
            logger.error(f"Lỗi khi lưu video link vào db: {e}")
            await query.edit_message_text(f"❌ Có lỗi khi lưu: {escape(str(e))}")
            
    elif action.startswith("save_"):
        sub_action = action.split("_")[1]
        save_key = data[2]
        
        cached_data = context.user_data.get(save_key)
        if not cached_data:
            await query.edit_message_text("❌ Lỗi: Dữ liệu tạm đã hết hạn hoặc không tìm thấy.")
            return
            
        title = cached_data["title"]
        url = cached_data["url"]
        
        await query.edit_message_text("⏳ Đang lưu vào bộ não...")
        
        try:
            if sub_action == "full":
                # Lưu toàn bộ bài viết / transcript
                content = cached_data["content"]
                
                # Chia nhỏ để RAG hiệu quả
                chunk_size = 1500
                chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
                
                saved_count = 0
                for chunk in chunks:
                    if len(chunk.strip()) > 50:
                        from services.journal_db import add_knowledge
                        await add_knowledge(update.effective_user.id, chunk, source=f"link: {title} ({url})")
                        saved_count += 1
                await query.edit_message_text(f"✅ Đã lưu toàn bộ nội dung ({saved_count} đoạn) vào bộ nhớ cá nhân!")
                
            elif sub_action == "sum":
                # Chỉ lưu bản tóm tắt
                summary = cached_data["summary"]
                from services.journal_db import add_knowledge
                await add_knowledge(update.effective_user.id, summary, source=f"tóm tắt: {title} ({url})")
                await query.edit_message_text("✅ Đã lưu bản tóm tắt vào bộ nhớ cá nhân!")
                
            # Xóa cache tạm
            context.user_data.pop(save_key, None)
        except Exception as e:
            logger.error(f"Lỗi khi lưu dữ liệu từ link vào db: {e}")
            await query.edit_message_text(f"❌ Có lỗi khi lưu: {escape(str(e))}")

def register_scraper_handlers(app):
    app.add_handler(CommandHandler("sumlink", cmd_sumlink))
    # Đăng ký MessageHandler trong group 1 để không bị các MessageHandler khác ở group 0 chặn
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_url_message), group=1)
    app.add_handler(CallbackQueryHandler(cb_scraper_handler, pattern="^scr:"))
    logger.info("Đã đăng ký Scraper & URL handlers")
