import logging
import re
from datetime import datetime
import aiosqlite
import pytz
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    filters,
    CallbackQueryHandler
)
import config
from services.journal_db import add_entry, has_answered_today, get_user, upsert_user, get_recent_entries, update_entry_ai, get_or_create_daily_vocab, get_recent_vocabs
from services.journal_ai import analyze_journal_entry
from questions.bank import get_daily_question
from config import ALLOWED_USER_IDS
from services.markdown import escape, bold, italic, code, build
from services.telegram_utils import send_message_safe, edit_message_safe
from services.journal_quiz import generate_vocab_quiz

logger = logging.getLogger(__name__)

# States for ConversationHandler
WAITING_JOURNAL_ANSWER = 1
WAITING_RESTORE_ANSWER = 2

def require_auth(fn):
    """Decorator để kiểm tra quyền truy cập."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            logger.warning(f"User {user_id} không có trong whitelist")
            msg = update.effective_message
            if msg:
                await msg.reply_text("Bạn không có quyền sử dụng tính năng này.")
            return ConversationHandler.END
        return await fn(update, context)
    return wrapper

@require_auth
async def cmd_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu ghi nhật ký hàng ngày hoặc ghi nhật ký nhanh nếu có tham số."""
    user_id = update.effective_user.id
    username = update.effective_user.username
    if update.callback_query:
        await update.callback_query.answer()

    try:
        # Đảm bảo user tồn tại trong DB
        await upsert_user(user_id, username)
        
        # Kiểm tra xem hôm nay đã trả lời chưa
        if await has_answered_today(user_id):
            logger.info(f"User {user_id} đã ghi nhật ký hôm nay rồi.")
            await update.effective_message.reply_text(
                escape("Hôm nay bạn đã ghi nhật ký rồi! Hẹn gặp lại vào ngày mai nhé. 😊"),
                parse_mode="HTML"
            )
            return ConversationHandler.END
        
        # Kiểm tra xem có truyền tham số ghi nhật ký nhanh không
        quick_text = " ".join(context.args).strip() if (context.args is not None) else ""
        if quick_text:
            if len(quick_text) < 2:
                await update.effective_message.reply_text("Câu trả lời hơi ngắn, bạn kể thêm chút được không?")
                return ConversationHandler.END
            
            question = get_daily_question()
            
            # Lưu vào DB
            entry_id, streak = await add_entry(user_id, question, quick_text)
            logger.info(f"Đã lưu quick entry {entry_id} cho user {user_id}, streak: {streak}")
            
            # Gọi AI phân tích
            ai_result = await analyze_journal_entry(question, quick_text)
            
            sentiment_str = ""
            topics_str = ""
            reply_msg = "Cảm ơn bạn đã chia sẻ. Chúc bạn một ngày tốt lành! ✨"
            
            if ai_result:
                sentiment = ai_result.get('sentiment', 'Trung tính')
                topics = ai_result.get('topics', [])
                score = ai_result.get('score', 0.0)
                reply_msg = ai_result.get('reply', reply_msg)
                
                # Cập nhật DB với kết quả AI
                await update_entry_ai(entry_id, sentiment, topics, score)
                
                sentiment_str = f"😊 {escape('Tâm trạng')}: {escape(sentiment)}\n"
                if topics:
                    topics_str = f"🏷️ {escape('Chủ đề')}: {escape(' '.join(['#' + t for t in topics]))}\n"

            streak_msg = f"🔥 Streak: {streak} {escape('ngày liên tiếp!')}" if streak > 1 else f"🌟 {escape('Bắt đầu chuỗi ngày mới!')}"
            
            response = build(
                "✅ " + bold("Đã ghi lại nhật ký hôm nay!"),
                "",
                f"💬 {italic(escape(reply_msg))}",
                "",
                sentiment_str + topics_str + streak_msg
            )
            
            await send_message_safe(bot=context.bot, chat_id=update.effective_chat.id, text=response, parse_mode="HTML")
            logger.info(f"Đã gửi phản hồi nhật ký nhanh cho {user_id}")
            return ConversationHandler.END

        # Luồng hội thoại bình thường
        question = get_daily_question()
        context.user_data['journal_question'] = question
        
        tz = pytz.timezone(config.JOURNAL_TZ)
        local_date_str = datetime.now(tz).strftime('%d/%m/%Y')
        
        msg = build(
            bold("📔 Nhật ký hôm nay"),
            f"_{escape(local_date_str)}_",
            "",
            f"❓ {escape(question)}",
            "",
            italic(escape("(Nhắn câu trả lời của bạn vào đây, vài từ cũng được!)"))
        )
        
        await update.effective_message.reply_text(msg, parse_mode="HTML")
        logger.info(f"Đã gửi câu hỏi nhật ký cho {user_id}")
        return WAITING_JOURNAL_ANSWER
    except Exception as e:
        logger.error(f"Lỗi trong cmd_journal: {e}")
        await update.effective_message.reply_text("Có lỗi xảy ra khi bắt đầu nhật ký. Vui lòng thử lại sau.")
        return ConversationHandler.END

async def handle_journal_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý câu trả lời nhật ký của user."""
    user_id = update.effective_user.id
    answer = update.effective_message.text
    logger.info(f"Nhận câu trả lời nhật ký từ {user_id}: {answer[:50]}...")
    
    question = context.user_data.get('journal_question', "Hôm nay bạn thế nào?")
    
    if not answer or len(answer) < 2:
        await update.effective_message.reply_text("Câu trả lời hơi ngắn, bạn kể thêm chút được không?")
        return WAITING_JOURNAL_ANSWER
    
    try:
        # Lưu vào DB
        entry_id, streak = await add_entry(user_id, question, answer)
        logger.info(f"Đã lưu entry {entry_id} cho user {user_id}, streak: {streak}")
        
        # Gọi AI phân tích
        ai_result = await analyze_journal_entry(question, answer)
        
        sentiment_str = ""
        topics_str = ""
        reply_msg = "Cảm ơn bạn đã chia sẻ. Chúc bạn một ngày tốt lành! ✨"
        
        if ai_result:
            sentiment = ai_result.get('sentiment', 'Trung tính')
            topics = ai_result.get('topics', [])
            score = ai_result.get('score', 0.0)
            reply_msg = ai_result.get('reply', reply_msg)
            
            # Cập nhật DB với kết quả AI
            await update_entry_ai(entry_id, sentiment, topics, score)
            
            sentiment_str = f"😊 {escape('Tâm trạng')}: {escape(sentiment)}\n"
            if topics:
                topics_str = f"🏷️ {escape('Chủ đề')}: {escape(' '.join(['#' + t for t in topics]))}\n"

        streak_msg = f"🔥 Streak: {streak} {escape('ngày liên tiếp!')}" if streak > 1 else f"🌟 {escape('Bắt đầu chuỗi ngày mới!')}"
        
        response = build(
            "✅ " + bold("Đã ghi lại nhật ký hôm nay!"),
            "",
            f"💬 {italic(escape(reply_msg))}",
            "",
            sentiment_str + topics_str + streak_msg
        )
        
        await send_message_safe(bot=context.bot, chat_id=update.effective_chat.id, text=response, parse_mode="HTML")
        logger.info(f"Đã gửi phản hồi nhật ký cho {user_id}")
        
        # Clean up
        context.user_data.pop('journal_question', None)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Lỗi trong handle_journal_answer: {e}")
        await update.effective_message.reply_text("Có lỗi xảy ra khi xử lý câu trả lời. Nhưng đừng lo, dữ liệu có thể đã được lưu.")
        return ConversationHandler.END

@require_auth
async def cmd_streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem chuỗi ngày ghi nhật ký hiện tại."""
    user_id = update.effective_user.id
    from services.journal_db import calculate_streaks
    
    info = await calculate_streaks(user_id)
    current_streak = info["current_streak"]
    longest_streak = info["longest_streak"]
    recent_gaps = info["recent_gaps"]
    
    # Check if this query is from a callback button (e.g. refresh or menu)
    is_callback = update.callback_query is not None
    
    if is_callback:
        await update.callback_query.answer()
        
    if longest_streak == 0:
        msg = build(
            "Bạn chưa có chuỗi ngày nào.",
            "",
            bold("Cách bắt đầu:"),
            f"Dùng lệnh {code('/journal')} để ghi lại nhật ký đầu tiên của bạn!"
        )
        if is_callback:
            await edit_message_safe(context.bot, update.effective_chat.id, update.callback_query.message.message_id, msg, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        return
        
    parts = [
        bold("🔥 Chuỗi nhật ký của bạn"),
        "",
        f"• {escape('Streak hiện tại')}: {bold(str(current_streak))} {escape('ngày')}",
        f"• {escape('Streak dài nhất')}: {bold(str(longest_streak))} {escape('ngày')}",
    ]
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = []
    
    # Nếu có khoảng trống có thể bù
    if recent_gaps:
        parts.append("")
        parts.append(bold("⚠️ Chuỗi của bạn bị đứt:"))
        parts.append(escape("Bạn đã bỏ lỡ ghi nhật ký vào các ngày sau. Hãy ghi bù để phục hồi streak của mình!"))
        
        # Chỉ hiển thị tối đa 3 nút phục hồi để tránh quá dài
        gap_buttons = []
        for gap in recent_gaps[:3]:
            # Định dạng dd/mm
            try:
                date_dt = datetime.strptime(gap, "%Y-%m-%d")
                btn_label = f"📝 Phục hồi {date_dt.strftime('%d/%m')}"
            except Exception:
                btn_label = f"📝 Phục hồi {gap}"
            gap_buttons.append(InlineKeyboardButton(btn_label, callback_data=f"streak:restore:{gap}"))
        keyboard.append(gap_buttons)
        
    # Thêm nút tóm tắt streak nếu có bài viết
    summary_buttons = []
    summary_buttons.append(InlineKeyboardButton("📊 Tóm tắt chuỗi Streak", callback_data="streak:summary"))
    
    # Nút cập nhật/làm mới
    summary_buttons.append(InlineKeyboardButton("🔄 Cập nhật", callback_data="streak:refresh"))
    
    keyboard.append(summary_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = build(*parts)
    
    if is_callback:
        await edit_message_safe(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            message_id=update.callback_query.message.message_id,
            text=msg_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text(msg_text, reply_markup=reply_markup, parse_mode="HTML")

@require_auth
async def cmd_streak_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu quá trình ghi nhật ký bù để phục hồi streak."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not query:
        # Nếu được gọi trực tiếp bằng lệnh (ví dụ: /restore_streak)
        from services.journal_db import calculate_streaks
        info = await calculate_streaks(user_id)
        gaps = info["recent_gaps"]
        if not gaps:
            await update.effective_message.reply_text("Tuyệt vời! Bạn không có khoảng trống nào cần phục hồi gần đây.")
            return ConversationHandler.END
        date_str = gaps[0]
    else:
        await query.answer()
        # Callback data format: "streak:restore:YYYY-MM-DD"
        data_parts = query.data.split(":")
        if len(data_parts) < 3:
            return ConversationHandler.END
        date_str = data_parts[2]
        
    # Đảm bảo chưa ghi nhật ký cho ngày này
    from services.journal_db import has_answered_today
    if await has_answered_today(user_id, date_str):
        msg = f"Bạn đã ghi nhật ký cho ngày {date_str} rồi."
        if query:
            await query.message.reply_text(msg)
        else:
            await update.effective_message.reply_text(msg)
        return ConversationHandler.END
        
    # Lưu thông tin ngày cần bù vào context
    context.user_data['restore_date'] = date_str
    
    # Lấy câu hỏi cho ngày đó
    from questions.bank import get_daily_question
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        question = get_daily_question(date_obj)
    except Exception:
        question = get_daily_question()
        
    context.user_data['restore_question'] = question
    
    # Định dạng hiển thị ngày
    try:
        date_vn = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        date_vn = date_str
        
    msg = build(
        bold(f"📔 Nhật ký bù ngày {date_vn}"),
        "",
        f"❓ {escape(question)}",
        "",
        italic(escape("(Vui lòng nhắn câu trả lời của bạn vào đây để phục hồi streak!)")),
        "",
        f"Để hủy bỏ, gõ {code('/cancel')}."
    )
    
    if query:
        await query.message.reply_text(msg, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(msg, parse_mode="HTML")
        
    return WAITING_RESTORE_ANSWER

async def handle_streak_restore_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý câu trả lời nhật ký bù và nối lại streak."""
    user_id = update.effective_user.id
    answer = update.effective_message.text
    
    date_str = context.user_data.get('restore_date')
    question = context.user_data.get('restore_question', "Ngày hôm đó thế nào?")
    
    if not date_str:
        await update.effective_message.reply_text("Không tìm thấy thông tin ngày phục hồi. Quá trình đã hết hạn.")
        return ConversationHandler.END
        
    if not answer or len(answer) < 2:
        await update.effective_message.reply_text("Câu trả lời hơi ngắn, bạn kể thêm chút được không?")
        return WAITING_RESTORE_ANSWER
        
    try:
        logger.info(f"Đang ghi nhật ký bù cho {user_id} ngày {date_str}...")
        
        # 1. Lưu vào DB (add_entry tự động recalculate_and_update_user_streak)
        entry_id, streak = await add_entry(user_id, question, answer, date_str=date_str)
        
        # 2. Gọi AI phân tích
        ai_result = await analyze_journal_entry(question, answer)
        sentiment_str = ""
        topics_str = ""
        reply_msg = "Cảm ơn bạn đã viết nhật ký bù. Chúc bạn luôn duy trì được thói quen tốt này! ✨"
        
        if ai_result:
            sentiment = ai_result.get('sentiment', 'Trung tính')
            topics = ai_result.get('topics', [])
            score = ai_result.get('score', 0.0)
            reply_msg = ai_result.get('reply', reply_msg)
            
            await update_entry_ai(entry_id, sentiment, topics, score)
            
            sentiment_str = f"😊 {escape('Tâm trạng')}: {escape(sentiment)}\n"
            if topics:
                topics_str = f"🏷️ {escape('Chủ đề')}: {escape(' '.join(['#' + t for t in topics]))}\n"
                
        # Định dạng ngày hiển thị
        try:
            date_vn = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            date_vn = date_str
            
        response = build(
            "✅ " + bold(f"Đã ghi lại nhật ký bù ngày {date_vn}!"),
            "",
            f"💬 {italic(escape(reply_msg))}",
            "",
            sentiment_str + topics_str + f"🔥 Streak hiện tại của bạn: {bold(str(streak))} {escape('ngày liên tiếp!')}"
        )
        
        await send_message_safe(bot=context.bot, chat_id=update.effective_chat.id, text=response, parse_mode="HTML")
        
        # Clean up
        context.user_data.pop('restore_date', None)
        context.user_data.pop('restore_question', None)
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Lỗi trong handle_streak_restore_answer: {e}", exc_info=True)
        await update.effective_message.reply_text("Có lỗi xảy ra khi lưu nhật ký bù. Vui lòng thử lại sau.")
        return ConversationHandler.END

async def cmd_cancel_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hủy quá trình phục hồi streak."""
    context.user_data.pop('restore_date', None)
    context.user_data.pop('restore_question', None)
    await update.effective_message.reply_text(
        "Đã hủy quá trình phục hồi streak.", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

@require_auth
async def cmd_streak_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yêu cầu AI tổng hợp nhật ký trong chuỗi streak của người dùng."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query:
        await query.answer()
        
    loading_msg = "🔄 Đang phân tích và tổng hợp chuỗi streak của bạn..."
    if query:
        msg = await query.message.reply_text(loading_msg)
    else:
        msg = await update.effective_message.reply_text(loading_msg)
        
    try:
        from services.journal_db import calculate_streaks
        from services.journal_ai import generate_streak_summary
        
        info = await calculate_streaks(user_id)
        streaks = info["streaks"]
        
        if not streaks:
            await edit_message_safe(context.bot, msg.chat_id, msg.message_id, "Bạn chưa có dữ liệu nhật ký nào để tóm tắt.")
            return
            
        target_streak = None
        current_streak_len = info["current_streak"]
        
        if current_streak_len > 0:
            target_streak = streaks[-1]
        else:
            long_streaks = [s for s in streaks if s["length"] >= 2]
            if long_streaks:
                target_streak = long_streaks[-1]
            else:
                target_streak = streaks[-1]
                
        start_date = target_streak["start"]
        end_date = target_streak["end"]
        length = target_streak["length"]
        
        # Lấy tất cả các entries trong khoảng thời gian này
        async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM journal_entries 
                WHERE user_id = ? AND date >= ? AND date <= ?
                ORDER BY date ASC
            """, (user_id, start_date, end_date)) as cursor:
                entries = await cursor.fetchall()
                
        if not entries:
            await edit_message_safe(context.bot, msg.chat_id, msg.message_id, "Không tìm thấy dữ liệu bài viết của chuỗi streak.")
            return
            
        summary = await generate_streak_summary(entries, length)
        
        from services.markdown import ai_to_mdv2
        md_summary = ai_to_mdv2(summary)
        
        try:
            start_vn = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
            end_vn = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            start_vn, end_vn = start_date, end_date
            
        header = f"📊 {bold(f'Tổng kết Chuỗi Streak ({length} ngày)')}\n_{escape(start_vn)} - {escape(end_vn)}_\n\n"
        
        await edit_message_safe(
            bot=context.bot,
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            text=header + md_summary,
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Lỗi trong cmd_streak_summary: {e}", exc_info=True)
        await edit_message_safe(
            bot=context.bot,
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            text="Có lỗi xảy ra khi tạo tổng hợp chuỗi streak. Vui lòng thử lại sau."
        )

streak_restore_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(cmd_streak_restore_start, pattern="^streak:restore:(.+)$"),
        CommandHandler("restore_streak", cmd_streak_restore_start)
    ],
    states={
        WAITING_RESTORE_ANSWER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_streak_restore_answer)
        ]
    },
    fallbacks=[CommandHandler("cancel", cmd_cancel_restore)],
    name="streak_restore_conversation",
    persistent=False
)

@require_auth
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem lại lịch sử nhật ký gần đây."""
    user_id = update.effective_user.id
    limit = 5
    args = context.args
    if args and args[0].isdigit():
        limit = min(int(args[0]), 10)
        
    entries = await get_recent_entries(user_id, limit)
    
    if not entries:
        await update.effective_message.reply_text(build(
            "Bạn chưa có nhật ký nào.",
            "",
            bold("Cách bắt đầu:"),
            f"Dùng lệnh {code('/journal')} để ghi lại nhật ký đầu tiên!"
        ), parse_mode="HTML")
        return
        
    lines = [bold(f"📅 {limit} nhật ký gần nhất:"), ""]
    for e in entries:
        sentiment_icon = "😊" if e['sentiment'] == "Tích cực" else "😐" if e['sentiment'] == "Trung tính" else "😔"
        # Escape các ký tự đặc biệt như . và :
        date_str = escape(e['date'])
        answer_preview = escape(e['answer'][:100])
        lines.append(f"• {bold(date_str)}{escape(':')} {sentiment_icon} {answer_preview}{escape('...')}")
        
    lines.append("")
    lines.append(italic(escape(f"Dùng /history <số> để xem nhiều hơn (tối đa 10).")))
    
    await update.effective_message.reply_text(build(*lines), parse_mode="HTML")

@require_auth
async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cài đặt giờ nhận câu hỏi hàng ngày."""
    args = context.args
    if not args:
        await update.effective_message.reply_text(build(
            bold("Cú pháp:"),
            code("/settime HH:mm"),
            "",
            bold("Ví dụ:"),
            f"{code('/settime 08:30')} (nhắc nhở lúc 8h30 sáng)",
            f"{code('/settime 21:00')} (nhắc nhở lúc 9h tối)",
            "",
            italic("Định dạng: Giờ (0-23) và Phút (0-59).")
        ), parse_mode="HTML")
        return
        
    time_str = args[0]
    try:
        if ":" in time_str:
            hour_str, minute_str = time_str.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
        else:
            hour = int(time_str)
            minute = 0
            
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("Thời gian không hợp lệ. Vui lòng dùng định dạng HH:mm (ví dụ 08:30).")
        return
        
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        # Đảm bảo user tồn tại trước khi UPDATE
        await db.execute("""
            INSERT INTO journal_users (user_id, username, joined_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = COALESCE(?, username)
        """, (user_id, username, datetime.now().isoformat(), username))
        
        await db.execute(
            "UPDATE journal_users SET notify_hour = ?, notify_minute = ? WHERE user_id = ?", 
            (hour, minute, user_id)
        )
        await db.commit()
        
    await update.effective_message.reply_text(
        build(
            f"✅ {bold('Đã cài đặt!')}",
            f"Bot sẽ gửi câu hỏi cho bạn vào lúc {bold(f'{hour:02d}:{minute:02d}')} mỗi ngày\\."
        ), 
        parse_mode="HTML"
    )

@require_auth
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yêu cầu AI tổng hợp nhật ký tuần này."""
    from services.journal_ai import generate_journal_summary
    user_id = update.effective_user.id
    
    # Lấy entries trong 7 ngày qua
    entries = await get_recent_entries(user_id, 7)
    if not entries:
        await update.effective_message.reply_text("Bạn cần ghi nhật ký ít nhất vài ngày để tôi có thể tổng hợp.")
        return
        
    msg = await update.effective_message.reply_text("🔄 Đang phân tích và tổng hợp nhật ký tuần của bạn...")
    
    summary = await generate_journal_summary(entries, "tuần")
    
    from services.markdown import ai_to_mdv2
    md_summary = ai_to_mdv2(summary)
    
    await edit_message_safe(
        bot=context.bot,
        chat_id=msg.chat_id,
        message_id=msg.message_id,
        text=md_summary,
        parse_mode="HTML"
    )

@require_auth
async def cmd_vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem đoạn giao tiếp của ngày hôm nay."""
    vocab = await get_or_create_daily_vocab()
    
    parts = [bold("🌍 Giao tiếp hàng ngày"), ""]
    
    keyboard = []
    if vocab:
        date_str = vocab.get('date') or datetime.now(pytz.timezone(config.JOURNAL_TZ)).strftime("%Y-%m-%d")
        parts.extend([
            f"🇬🇧 {bold('EN')}: {escape(vocab.get('word_en', ''))}",
            f"🇨🇳 {bold('ZH')}: {escape(vocab.get('word_zh', ''))}",
            f"🇯🇵 {bold('JA')}: {escape(vocab.get('word_ja', ''))}",
            f"🇻🇳 {bold('VI')}: {escape(vocab.get('meaning_vi', ''))}",
            ""
        ])
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        row = []
        if vocab.get('word_en'):
            row.append(InlineKeyboardButton("🔊 EN", callback_data=f"tts:en:{date_str}"))
        if vocab.get('word_zh'):
            row.append(InlineKeyboardButton("🔊 ZH", callback_data=f"tts:zh-CN:{date_str}"))
        if vocab.get('word_ja'):
            row.append(InlineKeyboardButton("🔊 JA", callback_data=f"tts:ja:{date_str}"))
        if row:
            keyboard.append(row)
            
        # Thêm nút xem lịch sử
        keyboard.append([InlineKeyboardButton("📚 Xem lịch sử", callback_data="vocab_history")])
    else:
        parts.extend([italic(escape("Hôm nay chưa có nội dung nào.")), ""])
        
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.effective_message.reply_text(build(*parts), parse_mode="HTML", reply_markup=reply_markup)

async def handle_vocab_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị lịch sử vựng khi nhấn nút."""
    query = update.callback_query
    await query.answer()
    
    # Lấy text hiện tại
    current_text = query.message.text_markdown_v2
    if "📚 Lịch sử gần đây" in current_text:
        return

    recent = await get_recent_vocabs(limit=6)
    today_date = datetime.now(pytz.timezone(config.JOURNAL_TZ)).strftime("%Y-%m-%d")
    recent_filtered = [r for r in recent if r['date'] != today_date][:5]
    
    if not recent_filtered:
        await query.answer("Chưa có lịch sử nào.")
        return

    history_parts = ["", bold("📚 Lịch sử gần đây:")]
    for r in recent_filtered:
        en_preview = r['word_en'][:30] + ("..." if len(r['word_en']) > 30 else "")
        history_parts.append(f"• {escape(r['date'])}: {bold(escape(en_preview))} \\- {escape(r['meaning_vi'])}")
    
    new_text = current_text + "\n" + "\n".join(history_parts)
    
    # Cập nhật keyboard (loại bỏ nút Xem lịch sử)
    from telegram import InlineKeyboardMarkup
    new_keyboard = []
    for row in query.message.reply_markup.inline_keyboard:
        new_row = [btn for btn in row if btn.callback_data != "vocab_history"]
        if new_row:
            new_keyboard.append(new_row)
            
    await query.edit_message_text(
        text=new_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(new_keyboard)
    )

async def handle_tts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi nhấn vào nút loa để nghe phát âm."""
    query = update.callback_query
    await query.answer()
    
    try:
        # data format: "tts:lang:date_str"
        parts = query.data.split(':', 2)
        if len(parts) < 3:
            return
            
        lang = parts[1]
        date_str = parts[2]
        
        from services.journal_db import get_daily_vocab
        vocab = await get_daily_vocab(date_str)
        if not vocab:
            return
            
        text = ""
        if lang == 'en':
            text = vocab['word_en']
        elif lang == 'zh-CN':
            # Loại bỏ Pinyin trong ngoặc (...) nhưng giữ lại toàn bộ text (bao gồm phần B)
            text = re.sub(r'\(.*?\)', '', vocab['word_zh']).strip()
        elif lang == 'ja':
            # Loại bỏ Romaji trong ngoặc (...) nhưng giữ lại toàn bộ text (bao gồm phần B)
            text = re.sub(r'\(.*?\)', '', vocab['word_ja']).strip()
            
        if not text:
            return

        from services.tts import get_tts_voice
        voice_fp = get_tts_voice(text, lang)
        
        if voice_fp:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=voice_fp,
                title=f"Phát âm: {text[:20]}...",
                filename=f"tts_{lang}.mp3"
            )
        else:
            await query.message.reply_text("Không thể tạo giọng nói lúc này. Thử lại sau nhé!")
    except Exception as e:
        logger.error(f"Lỗi trong handle_tts_callback: {e}")

@require_auth
async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu một bài quiz từ vựng."""
    question, markup, _ = await generate_vocab_quiz()
    if not question:
        await update.effective_message.reply_text(
            "Bạn cần học thêm ít nhất 2-3 từ vựng (/vocab) để có thể làm quiz nhé!"
        )
        return
    
    await update.effective_message.reply_text(
        question, 
        parse_mode="HTML", 
        reply_markup=markup
    )

async def handle_quiz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi user chọn đáp án quiz."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(':')
    # quiz:is_correct:vocab_id:index
    is_correct = data[1] == "1"
    vocab_id = int(data[2])
    
    from services.journal_db import get_daily_vocab # though we might need a general get_vocab_by_id
    # Let's use a simpler way: just check is_correct
    
    if is_correct:
        result_text = build(
            bold("✅ Chính xác!"),
            "",
            query.message.text_markdown_v2,
            "",
            f"🎉 {italic('Chúc mừng bạn đã nhớ từ này!')}"
        )
    else:
        # Lấy đáp án đúng (tạm thời fetch lại hoặc lưu trong context nếu cần, 
        # nhưng ở đây ta có thể đơn giản hóa bằng cách thông báo sai)
        result_text = build(
            bold("❌ Chưa đúng rồi..."),
            "",
            query.message.text_markdown_v2,
            "",
            italic("Đừng buồn, hãy cố gắng ôn lại nhé! 💪")
        )

    await query.edit_message_text(
        text=result_text,
        parse_mode="HTML"
    )

async def cmd_cancel_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hủy quá trình ghi nhật ký."""
    await update.effective_message.reply_text(
        "Đã hủy ghi nhật ký. Hẹn gặp lại bạn sau!", 
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END
    
@require_auth
async def cmd_check_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiểm tra trạng thái các jobs tự động và cấu hình cá nhân."""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    job_queue = context.job_queue
    if not job_queue:
        await update.effective_message.reply_text("JobQueue không khả dụng.")
        return
        
    jobs = job_queue.jobs()
    
    lines = [bold("🕒 Trạng thái Hệ thống Job:"), ""]
    if not jobs:
        lines.append(italic("Không có job nào đang chạy."))
    else:
        for job in jobs:
            next_t = job.next_t
            if next_t:
                next_t_vn = next_t.astimezone(pytz.timezone(config.JOURNAL_TZ))
                time_str = next_t_vn.strftime("%H:%M:%S %d/%m/%Y")
            else:
                time_str = "N/A"
            lines.append(f"• {bold(escape(job.name))}: {escape(time_str)}")
    
    lines.append("")
    lines.append(bold("👤 Cấu hình của bạn:"))
    if user:
        h = user['notify_hour']
        m = user['notify_minute']
        lines.append(f"• Giờ nhận câu hỏi: {bold(f'{h:02d}:{m:02d}')}")
        lines.append(f"• Streak hiện tại: {bold(str(user['streak_count']))} ngày")
    else:
        lines.append(italic("Bạn chưa có dữ liệu cấu hình."))
        
    await update.effective_message.reply_text(build(*lines), parse_mode="HTML")

# Định nghĩa ConversationHandler
journal_handler = ConversationHandler(
    entry_points=[
        CommandHandler("journal", cmd_journal),
        CallbackQueryHandler(cmd_journal, pattern="^cmd:journal$")
    ],
    states={
        WAITING_JOURNAL_ANSWER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_journal_answer)
        ]
    },
    fallbacks=[CommandHandler("cancel", cmd_cancel_journal)],
    name="journal_conversation",
    persistent=False
)

def register_journal_handlers(app):
    """Đăng ký các handlers vào bot application."""
    app.add_handler(streak_restore_handler)
    app.add_handler(journal_handler)
    app.add_handler(CommandHandler("streak", cmd_streak))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("setjob", cmd_settime))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("streak_summary", cmd_streak_summary))
    app.add_handler(CommandHandler("restore_streak", cmd_streak_restore_start))
    app.add_handler(CommandHandler("checkjobs", cmd_check_jobs))
    app.add_handler(CommandHandler("vocab", cmd_vocab))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CallbackQueryHandler(handle_tts_callback, pattern="^tts:"))
    app.add_handler(CallbackQueryHandler(handle_vocab_history, pattern="^vocab_history$"))
    app.add_handler(CallbackQueryHandler(handle_quiz_callback, pattern="^quiz:"))
    app.add_handler(CallbackQueryHandler(cmd_quiz, pattern="^cmd:quiz$"))
    app.add_handler(CallbackQueryHandler(cmd_streak_summary, pattern="^streak:summary$"))
    app.add_handler(CallbackQueryHandler(cmd_streak, pattern="^streak:refresh$"))
    logger.info("Đã đăng ký Journal handlers")
