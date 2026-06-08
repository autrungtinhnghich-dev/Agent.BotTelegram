import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from services.brain_service import process_and_save_text, process_pdf_file, ask_brain, process_srs_file
from services.markdown import escape, bold, italic, code, build
from services.telegram_utils import send_message_safe, edit_message_safe
from config import ALLOWED_USER_IDS
from services.journal_db import check_srs_file_exists

logger = logging.getLogger(__name__)

# States
WAITING_BRAIN_QUESTION = 1

def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            return
        return await fn(update, context)
    return wrapper

@require_auth
async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lưu kiến thức từ text."""
    text = " ".join(context.args) if context.args else ""
    if not text:
        # Kiểm tra nếu là reply
        if update.effective_message.reply_to_message and update.effective_message.reply_to_message.text:
            text = update.effective_message.reply_to_message.text
        else:
            await send_message_safe(
                bot=context.bot,
                chat_id=update.effective_chat.id,
                text=build(
                    bold("Cú pháp:"),
                    code("/save <nội dung>"),
                    "Hoặc reply vào một tin nhắn và gõ /save"
                ),
                parse_mode="HTML",
                reply_to_message_id=update.effective_message.message_id
            )
            return

    kb_id = await process_and_save_text(update.effective_user.id, text)
    if kb_id:
        await send_message_safe(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            text=f"✅ {bold('Đã lưu vào bộ nhớ!')}\nID: {code(str(kb_id))}",
            parse_mode="HTML",
            reply_to_message_id=update.effective_message.message_id
        )
    else:
        await send_message_safe(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            text="Nội dung quá ngắn hoặc có lỗi khi lưu.",
            reply_to_message_id=update.effective_message.message_id
        )

@require_auth
async def ask_brain_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu quy trình hỏi bộ não cá nhân (phiên chat nhiều lượt)."""
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.effective_message

    # Reset lịch sử chat bộ não
    context.user_data["brain_chat_history"] = []
    context.user_data["in_brain_ask"] = True

    keyboard = [[InlineKeyboardButton("🛑 Kết thúc chat", callback_data="brain:ask_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.reply_text(
        build(
            bold("🧠 Trò chuyện với Bộ não Cá nhân"),
            "",
            "Hãy đặt câu hỏi. Mình sẽ tìm kiếm thông tin liên quan trong bộ nhớ của bạn để trả lời và duy trì ngữ cảnh trò chuyện.",
            "",
            italic("(Bấm nút bên dưới hoặc gõ /cancel để kết thúc bất kỳ lúc nào)")
        ),
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    return WAITING_BRAIN_QUESTION


async def ask_brain_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tiếp tục trò chuyện sau khi hỏi đơn lẻ bằng lệnh /ask."""
    query = update.callback_query
    await query.answer()

    last_q = context.user_data.get("last_ask_q")
    last_a = context.user_data.get("last_ask_a")

    context.user_data["brain_chat_history"] = []
    context.user_data["in_brain_ask"] = True
    if last_q and last_a:
        context.user_data["brain_chat_history"] = [
            {"role": "user", "content": last_q},
            {"role": "assistant", "content": last_a}
        ]

    keyboard = [[InlineKeyboardButton("🛑 Kết thúc chat", callback_data="brain:ask_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        build(
            bold("💬 Đang vào chế độ trò chuyện liên tục..."),
            "Bạn có thể đặt câu hỏi tiếp theo về nội dung vừa rồi hoặc các chủ đề khác trong bộ não.",
            "",
            italic("(Bấm nút bên dưới hoặc gõ /cancel để thoát)")
        ),
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    return WAITING_BRAIN_QUESTION


async def handle_brain_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý câu hỏi user nhập vào trong chế độ conversation (Multi-turn RAG)."""
    question = update.effective_message.text.strip()
    user_id = update.effective_user.id

    if not question or len(question) < 2:
        await update.effective_message.reply_text("Câu hỏi hơi ngắn, bạn nhập rõ hơn chút nhé.")
        return WAITING_BRAIN_QUESTION

    msg = await update.effective_message.reply_text("🔍 Đang lục lại trí nhớ...")
    
    # Lấy lịch sử chat
    history = context.user_data.get("brain_chat_history", [])
    
    from services.brain_service import ask_brain_with_history
    answer = await ask_brain_with_history(user_id, question, history)
    
    # Cập nhật lịch sử
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    
    # Giới hạn lịch sử
    max_history = 10
    if len(history) > max_history * 2:
        history = history[-(max_history * 2):]
    context.user_data["brain_chat_history"] = history
    
    from services.markdown import ai_to_mdv2
    md_answer = ai_to_mdv2(answer)
    
    keyboard = [[InlineKeyboardButton("🛑 Kết thúc chat", callback_data="brain:ask_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await edit_message_safe(
        bot=context.bot,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        text=md_answer,
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    return WAITING_BRAIN_QUESTION


async def cancel_brain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hủy quy trình hỏi và xóa lịch sử phiên chat."""
    context.user_data.pop("brain_chat_history", None)
    context.user_data.pop("in_brain_ask", None)
    
    msg_text = "✅ Đã kết thúc cuộc trò chuyện với bộ não."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=None)
    else:
        await update.effective_message.reply_text(msg_text)
        
    return ConversationHandler.END


@require_auth
async def cmd_ask_brain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /ask truyền thống (vẫn giữ nếu muốn dùng nhanh hoặc có tham số)."""
    question = " ".join(context.args) if context.args else ""
    if not question:
        # Nếu không truyền tham số, bật chế độ trò chuyện liên tục
        return await ask_brain_start(update, context)

    msg = await update.effective_message.reply_text("🔍 Đang lục lại trí nhớ...")
    
    answer = await ask_brain(update.effective_user.id, question)
    
    # Lưu trữ cho luồng "Trò chuyện tiếp"
    context.user_data["last_ask_q"] = question
    context.user_data["last_ask_a"] = answer
    
    from services.markdown import ai_to_mdv2
    md_answer = ai_to_mdv2(answer)
    
    keyboard = [[InlineKeyboardButton("💬 Trò chuyện tiếp", callback_data="brain:chat_continue")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await edit_message_safe(
        bot=context.bot,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        text=md_answer,
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def download_srs_document(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, dest_path: str, file_name: str = None):
    """Tải tệp tin bằng Bot API hoặc Telethon (nếu tệp tin lớn hơn 20MB)."""
    try:
        # Thử tải qua Bot API
        new_file = await context.bot.get_file(file_id)
        await new_file.download_to_drive(dest_path)
    except Exception as bot_err:
        from handlers.commands import _telethon
        if _telethon:
            logger.info(f"Bot API download failed: {bot_err}. Attempting download via Telethon...")
            chat_id = update.effective_chat.id
            
            # Đối với chat riêng, đối tác hội thoại của Telethon (User) là Bot
            if update.effective_chat.type == "private":
                try:
                    bot_username = context.bot.username
                    if not bot_username:
                        raise ValueError("Username is empty")
                    entity_id = f"@{bot_username}"
                except Exception:
                    try:
                        bot_me = await context.bot.get_me()
                        entity_id = f"@{bot_me.username}"
                    except Exception as err:
                        logger.warning(f"Could not resolve bot username: {err}")
                        try:
                            entity_id = int(context.bot.token.split(':')[0])
                        except Exception:
                            entity_id = context.bot.id
            else:
                entity_id = chat_id
                
            logger.info(f"Telethon download config: chat_type={update.effective_chat.type}, entity_id={entity_id} ({type(entity_id).__name__}), file_name={file_name}")
            try:
                message = None
                
                # Quét lịch sử tin nhắn gần đây để tìm tệp tin theo tên
                if file_name:
                    logger.info(f"Searching for message with media filename '{file_name}' in Telethon history...")
                    async for msg in _telethon.iter_messages(entity_id, limit=20):
                        if msg.media and hasattr(msg, 'file') and msg.file and msg.file.name == file_name:
                            message = msg
                            logger.info(f"Found precise match in Telethon history: id={msg.id}, size={msg.file.size}")
                            break
                            
                # Nếu không khớp hoặc không truyền tên file, lấy tin nhắn chứa media gần nhất
                if not message:
                    logger.info("Precise file name match not found. Falling back to most recent media message...")
                    async for msg in _telethon.iter_messages(entity_id, limit=10):
                        if msg.media and hasattr(msg, 'file') and msg.file:
                            message = msg
                            logger.info(f"Fallback matched message: id={msg.id}, filename={msg.file.name}")
                            break
                
                if message and message.media:
                    await _telethon.download_media(message, file=dest_path)
                    logger.info(f"Successfully downloaded file via Telethon to {dest_path}")
                else:
                    raise RuntimeError(f"Không tìm thấy tin nhắn chứa media phù hợp với '{file_name}' qua Telethon.")
            except Exception as telethon_err:
                logger.error(f"Telethon download failed for entity_id={entity_id}, file_name={file_name}: {telethon_err}", exc_info=True)
                raise RuntimeError(f"Không thể tải file lớn (>20MB) qua cả Bot API và Telethon. Lỗi Telethon: {telethon_err}")
        else:
            raise RuntimeError(f"File quá lớn (Bot API giới hạn 20MB) và chưa cấu hình Telethon: {bot_err}")


async def handle_jira_srs_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tải và lưu file đặc tả SRS dự án (Hỗ trợ nhiều file liên tiếp & check trùng tên)."""
    msg = update.effective_message
    doc = msg.document
    
    if not doc:
        await msg.reply_text("❌ Lỗi: Vui lòng gửi tài liệu đặc tả dưới dạng file đính kèm.")
        return
        
    file_name = doc.file_name or "srs_document"
    file_id = doc.file_id
    ext = os.path.splitext(file_name.lower())[1]
    
    # Kiểm tra phần mở rộng được hỗ trợ
    if ext not in (".pdf", ".docx", ".txt", ".md", ".zip"):
        await msg.reply_text(f"❌ Định dạng file {code(ext)} không được hỗ trợ. Vui lòng gửi file PDF, DOCX, TXT, MD hoặc ZIP.")
        return
    
    # Kiểm tra xem file đã tồn tại hay chưa
    exists = await check_srs_file_exists(file_name)
    
    if exists:
        status_msg = await msg.reply_text(f"⏳ Đang tải file {code(file_name)} để chờ bạn xác nhận ghi đè...")
        try:
            os.makedirs("scratch", exist_ok=True)
            temp_file_path = f"scratch/temp_srs_pending_{doc.file_unique_id}{ext}"
            await download_srs_document(update, context, file_id, temp_file_path, file_name)
            
            # Lưu tạm thông tin file vào context
            context.user_data["srs_pending_confirm"] = {
                "file_name": file_name,
                "temp_file_path": temp_file_path,
                "file_unique_id": doc.file_unique_id
            }
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Ghi đè (Overwrite)", callback_data=f"jira_srs:overwrite:{doc.file_unique_id}"),
                    InlineKeyboardButton("❌ Bỏ qua (Skip)", callback_data=f"jira_srs:skip:{doc.file_unique_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_msg.edit_text(
                build(
                    "⚠️ " + bold("Tài liệu đặc tả đã tồn tại!"),
                    f"Phát hiện tài liệu đặc tả cùng tên hoặc chứa tên {code(file_name)} đã có trong cơ sở dữ liệu.",
                    "",
                    "Bạn có muốn ghi đè lên dữ liệu cũ hay bỏ qua tệp này?"
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            return
        except Exception as err:
            logger.error(f"Lỗi khi xử lý file trùng lặp: {err}", exc_info=True)
            await status_msg.edit_text(f"❌ Lỗi: {err}")
            return
            
    # Tiến hành xử lý ngay nếu chưa tồn tại
    status_msg = await msg.reply_text(f"⏳ Đang tải và lập chỉ mục đặc tả SRS từ: {code(file_name)}...")
    
    try:
        os.makedirs("scratch", exist_ok=True)
        temp_file_path = f"scratch/temp_srs_{doc.file_unique_id}{ext}"
        await download_srs_document(update, context, file_id, temp_file_path, file_name)
        
        # Xử lý file (giải nén ZIP hoặc đọc DOCX)
        count = await process_srs_file(update.effective_user.id, temp_file_path, file_name)
        
        # Xóa file tạm
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            
        if count >= 0:
            current_total = context.user_data.get("srs_uploaded_files_count", 0) + count
            context.user_data["srs_uploaded_files_count"] = current_total
            
            keyboard = [[InlineKeyboardButton("✅ Hoàn thành tải lên", callback_data="jira_srs:done")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = build(
                "📥 " + bold("Tiến trình tải lên tài liệu SRS:"),
                f"• Đã xử lý xong file: {code(file_name)}",
                f"• Số mẩu nghiệp vụ vừa lưu: {bold(str(count))}",
                f"• Tổng số mẩu đã lưu trong phiên này: {bold(str(current_total))}",
                "",
                italic("Bạn có thể tiếp tục gửi thêm file SRS khác (PDF, DOCX, TXT, ZIP...) hoặc bấm nút dưới đây để kết thúc phiên tải lên.")
            )
            await status_msg.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await status_msg.edit_text("❌ Có lỗi xảy ra trong quá trình xử lý đặc tả SRS.")
            
    except Exception as e:
        logger.error(f"Lỗi khi lưu SRS document: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Có lỗi xảy ra khi xử lý tệp: {e}")


@require_auth
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhận được file PDF hoặc hình ảnh để gợi ý lưu vào bộ nhớ."""
    if context.user_data.get("waiting_jira_srs_upload"):
        await handle_jira_srs_document_upload(update, context)
        return

    msg = update.effective_message
    doc = msg.document
    photo = msg.photo
    
    file_id = None
    file_unique_id = None
    file_name = None
    file_type = None  # 'pdf' or 'image'
    
    if doc:
        name_lower = doc.file_name.lower() if doc.file_name else ""
        if name_lower.endswith('.pdf'):
            file_id = doc.file_id
            file_unique_id = doc.file_unique_id
            file_name = doc.file_name
            file_type = 'pdf'
        elif name_lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif')):
            file_id = doc.file_id
            file_unique_id = doc.file_unique_id
            file_name = doc.file_name
            file_type = 'image'
        else:
            return  # Không hỗ trợ định dạng khác
    elif photo:
        # Lấy ảnh kích thước lớn nhất
        largest_photo = photo[-1]
        file_id = largest_photo.file_id
        file_unique_id = largest_photo.file_unique_id
        file_name = f"photo_{file_unique_id}.jpg"
        file_type = 'image'
    else:
        return
        
    # Lưu thông tin file vào user_data (sử dụng cấu trúc mới lưu trữ chi tiết tệp)
    context.user_data[f"brain_file_{file_unique_id}"] = {
        "file_id": file_id,
        "file_name": file_name,
        "file_type": file_type
    }
    
    keyboard = [
        [
            InlineKeyboardButton("🧠 Học file này", callback_data=f"brain:learn:{file_unique_id}"),
            InlineKeyboardButton("❌ Bỏ qua", callback_data="brain:cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    emoji = "📄" if file_type == "pdf" else "🖼️"
    type_label = "PDF" if file_type == "pdf" else "ảnh"
    
    await msg.reply_text(
        escape(f"{emoji} Mình thấy file {type_label}: ") + bold(escape(file_name)) + escape("\nBạn có muốn mình lưu nội dung này vào bộ nhớ không?"),
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def cb_learn_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback xử lý việc học file (hỗ trợ cả PDF và hình ảnh)."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(':')
    if data[1] == "cancel":
        await query.message.delete()
        return
        
    file_unique_id = data[2]
    
    # 1. Thử lấy theo format mới
    file_info = context.user_data.get(f"brain_file_{file_unique_id}")
    
    if file_info:
        file_id = file_info["file_id"]
        file_name = file_info["file_name"]
        file_type = file_info["file_type"]
    else:
        # 2. Dự phòng format cũ (chỉ dành cho PDF)
        file_id = context.user_data.get(f"pdf_{file_unique_id}")
        file_name = f"temp_{file_unique_id}.pdf"
        file_type = "pdf"
        
    if not file_id:
        await query.edit_message_text("❌ Lỗi: Phiên xử lý file đã hết hạn hoặc không tìm thấy file.")
        return
        
    await query.edit_message_text("⏳ Đang tải và phân tích file...")
    
    try:
        new_file = await context.bot.get_file(file_id)
        # Lấy phần mở rộng từ tên tệp gốc hoặc mặc định theo loại tệp
        ext = os.path.splitext(file_name.lower())[1]
        if not ext:
            ext = ".pdf" if file_type == "pdf" else ".jpg"
            
        temp_file_path = f"temp_{file_unique_id}{ext}"
        await new_file.download_to_drive(temp_file_path)
        
        if file_type == "pdf":
            count = await process_pdf_file(update.effective_user.id, temp_file_path, file_name)
        else:
            from services.brain_service import process_image_file
            count = await process_image_file(update.effective_user.id, temp_file_path, file_name)
            
        # Xóa file tạm
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            
        if count > 0:
            await query.edit_message_text(escape("✅ Đã học xong! Lưu được ") + bold(str(count)) + escape(" đoạn kiến thức từ file."), parse_mode="HTML")
        elif count == 0:
            await query.edit_message_text("❌ File không có nội dung văn bản hoặc không thể trích xuất thông tin để học.")
        else:
            await query.edit_message_text("❌ Lỗi trong quá trình phân tích file.")
            
        # Xóa dữ liệu cache
        context.user_data.pop(f"brain_file_{file_unique_id}", None)
        context.user_data.pop(f"pdf_{file_unique_id}", None)
    except Exception as e:
        logger.error(f"Lỗi callback learn_file: {e}")
        await query.edit_message_text(f"Lỗi: {e}")

def register_brain_handlers(app):
    # Conversation handler cho việc hỏi (giúp bấm nút hiện form nhập)
    brain_ask_handler = ConversationHandler(
        entry_points=[
            CommandHandler("ask", ask_brain_start),
            CommandHandler("brain", ask_brain_start),
            CallbackQueryHandler(ask_brain_start, pattern="^cmd:ask$"),
            CallbackQueryHandler(ask_brain_continue, pattern="^brain:chat_continue$")
        ],
        states={
            WAITING_BRAIN_QUESTION: [
                CallbackQueryHandler(cancel_brain, pattern="^brain:ask_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_brain_question)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_brain),
            CommandHandler("endchat", cancel_brain),
            CallbackQueryHandler(cancel_brain, pattern="^brain:ask_cancel$")
        ],
        name="brain_ask_conversation",
        persistent=False
    )
    
    app.add_handler(brain_ask_handler)
    app.add_handler(CommandHandler("save", cmd_save))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(CallbackQueryHandler(cb_learn_file, pattern="^brain:learn:"))
    app.add_handler(CallbackQueryHandler(cb_learn_file, pattern="^brain:cancel$"))
    logger.info("Đã đăng ký Brain handlers")
