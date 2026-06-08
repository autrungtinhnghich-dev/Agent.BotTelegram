import logging
from datetime import datetime, time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import pytz
import aiosqlite
from telegram.ext import ContextTypes
import config
from services.journal_db import has_answered_today, get_user, get_or_create_daily_vocab
from questions.bank import get_daily_question
from services.markdown import escape, bold, italic, build
from services.telegram_utils import send_message_safe
from services.journal_quiz import generate_vocab_quiz

logger = logging.getLogger(__name__)
TZ = pytz.timezone(config.JOURNAL_TZ)

async def daily_question_job(context: ContextTypes.DEFAULT_TYPE):
    """Gửi câu hỏi hàng ngày cho user dựa trên notify_hour."""
    now = datetime.now(TZ)
    current_hour = now.hour
    current_minute = now.minute
    
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, username FROM journal_users WHERE notify_hour = ? AND notify_minute = ?", 
            (current_hour, current_minute)
        ) as cursor:
            users = await cursor.fetchall()
            
    if not users:
        return

    # Lấy hoặc tạo từ vựng cho hôm nay (dùng chung cho mọi user trong đợt quét này)
    vocab = await get_or_create_daily_vocab()

    for user in users:
        user_id = user['user_id']
        answered = await has_answered_today(user_id)
        
        parts = []
        if not answered:
            # Nếu chưa trả lời nhật ký: Gửi cả Câu hỏi và Từ vựng
            question = get_daily_question()
            parts.extend([
                bold("📔 Micro-Journal"),
                "",
                f"❓ {escape(question)}",
                ""
            ])
            
            if vocab:
                date_str = vocab.get('date') or datetime.now(TZ).strftime("%Y-%m-%d")
                parts.extend([
                    bold("🌍 Giao tiếp mỗi ngày"),
                    f"🇬🇧 {bold('EN')}: {escape(vocab.get('word_en', ''))}",
                    f"🇨🇳 {bold('ZH')}: {escape(vocab.get('word_zh', ''))}",
                    f"🇯🇵 {bold('JA')}: {escape(vocab.get('word_ja', ''))}",
                    f"🇻🇳 {bold('VI')}: {escape(vocab.get('meaning_vi', ''))}",
                    ""
                ])
            
            parts.append(italic(escape("(Dùng /journal để trả lời hoặc chỉ cần nhắn trực tiếp vào đây.)")))
        else:
            # Nếu đã trả lời rồi: Chỉ gửi Từ vựng
            if vocab:
                date_str = vocab.get('date') or datetime.now(TZ).strftime("%Y-%m-%d")
                parts.extend([
                    bold("🌍 Giao tiếp mỗi ngày"),
                    italic("(Hôm nay bạn đã hoàn thành nhật ký rồi! ✨)"),
                    "",
                    f"🇬🇧 {bold('EN')}: {escape(vocab.get('word_en', ''))}",
                    f"🇨🇳 {bold('ZH')}: {escape(vocab.get('word_zh', ''))}",
                    f"🇯🇵 {bold('JA')}: {escape(vocab.get('word_ja', ''))}",
                    f"🇻🇳 {bold('VI')}: {escape(vocab.get('meaning_vi', ''))}",
                    ""
                ])
        
        if parts:
            msg = build(*parts)
            
            keyboard = []
            if vocab:
                date_str = vocab.get('date') or datetime.now(TZ).strftime("%Y-%m-%d")
                row = []
                if vocab.get('word_en'):
                    row.append(InlineKeyboardButton("🔊 EN", callback_data=f"tts:en:{date_str}"))
                if vocab.get('word_zh'):
                    row.append(InlineKeyboardButton("🔊 ZH", callback_data=f"tts:zh-CN:{date_str}"))
                if vocab.get('word_ja'):
                    row.append(InlineKeyboardButton("🔊 JA", callback_data=f"tts:ja:{date_str}"))
                if row:
                    keyboard.append(row)
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            try:
                await send_message_safe(
                    bot=context.bot,
                    chat_id=user_id, 
                    text=msg, 
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
                logger.info(f"Đã gửi thông báo hàng ngày (vocab + journal) cho {user_id}")
            except Exception as e:
                logger.error(f"Lỗi khi gửi thông báo cho {user_id}: {e}")

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Nhắc nhở lúc 21:00 nếu chưa ghi nhật ký."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM journal_users") as cursor:
            users = await cursor.fetchall()
            
    for user in users:
        user_id = user['user_id']
        if not await has_answered_today(user_id):
            msg = "📝 Bạn ơi, hôm nay chưa ghi nhật ký! Chỉ cần 1-2 câu thôi để duy trì streak nhé. 😊"
            try:
                # Reminder dùng plain text cho an toàn vì không có format phức tạp
                await send_message_safe(bot=context.bot, chat_id=user_id, text=msg)
            except Exception as e:
                logger.error(f"Lỗi khi gửi nhắc nhở cho {user_id}: {e}")

async def weekly_summary_job(context: ContextTypes.DEFAULT_TYPE):
    """Tổng kết tuần vào tối Chủ Nhật."""
    pass

async def daily_quiz_job(context: ContextTypes.DEFAULT_TYPE):
    """Gửi Quiz từ vựng cho tất cả user vào buổi tối."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id FROM journal_users") as cursor:
            users = await cursor.fetchall()
            
    if not users:
        return

    # Tạo quiz một lần cho đợt gửi này
    question, markup, _ = await generate_vocab_quiz()
    if not question:
        return

    for user in users:
        user_id = user['user_id']
        try:
            await send_message_safe(
                bot=context.bot,
                chat_id=user_id,
                text=question,
                parse_mode="HTML",
                reply_markup=markup
            )
            logger.info(f"Đã gửi Quiz từ vựng cho {user_id}")
        except Exception as e:
            logger.error(f"Lỗi khi gửi quiz cho {user_id}: {e}")

async def jira_due_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Quét các task Jira và gửi thông báo nếu sắp đến hạn (due date) trước 1 day hoặc 0.5 day."""
    if not config.ALLOWED_USER_IDS:
        return
    
    owner_id = config.ALLOWED_USER_IDS[0]
    
    from services.jira_api import get_upcoming_due_issues
    from services.journal_db import is_jira_due_notified, mark_jira_due_notified
    from services.markdown import link, code
    
    issues = await get_upcoming_due_issues()
    if not issues:
        return
        
    now = datetime.now(TZ)
    
    for issue in issues:
        duedate_str = issue.get("duedate")
        if not duedate_str:
            continue
            
        try:
            # Parse YYYY-MM-DD
            due_date = datetime.strptime(duedate_str, "%Y-%m-%d")
            # Quy ước hạn chót là 18:00 của ngày due (cuối ngày làm việc)
            due_datetime = TZ.localize(datetime.combine(due_date.date(), time(18, 0, 0)))
            
            time_left = due_datetime - now
            hours_left = time_left.total_seconds() / 3600.0
            
            # Check thresholds
            # 1. Khẩn cấp: due in <= 12 hours (0.5 day)
            if 0 < hours_left <= 12:
                # Check if 0.5 level has been notified
                if not await is_jira_due_notified(issue["key"], 0.5):
                    # Notify
                    issue_link = f"{config.JIRA_BASE_URL}/browse/{issue['key']}"
                    msg = build(
                        f"⚠️ {bold('TASK JIRA SẮP HẾT HẠN (CÒN DƯỚI 12 GIỜ)')}",
                        "",
                        f"🎫 {link(issue['key'], issue_link)}: {escape(issue['summary'])}",
                        f"📊 Trạng thái: {italic(issue['status'])}",
                        f"🕒 Hạn chót: {code(due_datetime.strftime('%H:%M %d/%m/%Y'))}",
                        f"⏳ Còn lại: {bold(f'{hours_left:.1f} giờ')}",
                        "",
                        f"👉 Hãy khẩn trương hoàn thành nhé!"
                    )
                    await send_message_safe(bot=context.bot, chat_id=owner_id, text=msg, parse_mode="HTML")
                    # Mark both 0.5 and 1.0 as notified to prevent double alerts
                    await mark_jira_due_notified(issue["key"], 0.5)
                    await mark_jira_due_notified(issue["key"], 1.0)
                    logger.info(f"Đã gửi thông báo do-0.5 cho task {issue['key']}")
                    
            # 2. Nhắc nhở: due in <= 24 hours (1.0 day)
            elif 12 < hours_left <= 24:
                if not await is_jira_due_notified(issue["key"], 1.0):
                    issue_link = f"{config.JIRA_BASE_URL}/browse/{issue['key']}"
                    msg = build(
                        f"🔔 {bold('TASK JIRA SẮP ĐẾN HẠN (CÒN DƯỚI 24 GIỜ)')}",
                        "",
                        f"🎫 {link(issue['key'], issue_link)}: {escape(issue['summary'])}",
                        f"📊 Trạng thái: {italic(issue['status'])}",
                        f"🕒 Hạn chót: {code(due_datetime.strftime('%H:%M %d/%m/%Y'))}",
                        f"⏳ Còn lại: {bold(f'{hours_left:.1f} giờ')}",
                        "",
                        f"👉 Sắp xếp thời gian hoàn thành task nhé!"
                    )
                    await send_message_safe(bot=context.bot, chat_id=owner_id, text=msg, parse_mode="HTML")
                    await mark_jira_due_notified(issue["key"], 1.0)
                    logger.info(f"Đã gửi thông báo do-1.0 cho task {issue['key']}")
                    
        except Exception as e:
            logger.error(f"Lỗi khi xử lý hạn chót cho task {issue.get('key')}: {e}", exc_info=True)


async def jira_risk_alert_job(context: ContextTypes.DEFAULT_TYPE):
    """Quét các task Jira đang active và gửi cảnh báo rủi ro trễ hạn bằng AI (mức HIGH)."""
    if not config.ALLOWED_USER_IDS:
        return
    
    owner_id = config.ALLOWED_USER_IDS[0]
    
    from services.jira_api import get_active_issues, get_issue_full
    from services.summarizer import analyze_jira_issue_risk
    from services.journal_db import is_jira_risk_notified, mark_jira_risk_notified
    from services.markdown import ai_to_mdv2
    
    logger.info("Bắt đầu quét rủi ro trễ hạn Jira...")
    # 1. Lấy danh sách task chưa hoàn thành
    active_issues = await get_active_issues()
    if not active_issues:
        logger.info("Không có task Jira active nào cần phân tích rủi ro.")
        return
        
    for issue in active_issues:
        issue_key = issue["key"]
        jira_updated_at = issue["updated"]
        
        # 2. Kiểm tra xem đã gửi cảnh báo rủi ro HIGH cho bản cập nhật Jira này chưa
        if await is_jira_risk_notified(issue_key, "HIGH", jira_updated_at):
            continue
            
        # 3. Lấy thông tin chi tiết (comment, changelog) để AI phân tích
        issue_full = await get_issue_full(issue_key)
        if not issue_full:
            continue
            
        # 4. Phân tích qua AI
        analysis = analyze_jira_issue_risk(issue_full)
        risk_level = analysis.get("risk_level", "LOW").upper()
        
        # 5. Nếu rủi ro cao (HIGH), tiến hành cảnh báo và lưu vết
        if risk_level == "HIGH":
            report = analysis.get("markdown_report")
            if report:
                msg = build(
                    f"⚠️ {bold('AI CẢNH BÁO RỦI RO TRỄ HẠN CAO (JIRA)')}",
                    "",
                    report
                )
                try:
                    await send_message_safe(
                        bot=context.bot,
                        chat_id=owner_id,
                        text=msg,
                        parse_mode="HTML"
                    )
                    logger.info(f"Đã gửi cảnh báo rủi ro HIGH cho task {issue_key}")
                    # Lưu vết để không gửi lặp lại
                    await mark_jira_risk_notified(issue_key, "HIGH", jira_updated_at)
                except Exception as e:
                    logger.error(f"Lỗi khi gửi cảnh báo rủi ro cho {owner_id}: {e}")


def setup_scheduler(app, app_jira=None):
    """Cài đặt các jobs vào JobQueue."""
    job_queue = app.job_queue
    if not job_queue:
        logger.error("JobQueue không khả dụng.")
        return

    # Gửi câu hỏi mỗi phút (checker)
    job_queue.run_repeating(
        daily_question_job, 
        interval=60, 
        first=10,
        name="daily_question"
    )
    
    # Nhắc nhở lúc 21:00 hàng ngày
    job_queue.run_daily(
        reminder_job,
        time=time(hour=21, minute=0, second=0, tzinfo=TZ),
        name="daily_reminder"
    )

    # Gửi quiz vào 20:00 hàng ngày
    job_queue.run_daily(
        daily_quiz_job,
        time=time(hour=20, minute=0, second=0, tzinfo=TZ),
        name="daily_quiz"
    )

    # Đăng ký các Job liên quan đến Jira
    jira_job_queue = None
    if app_jira:
        if app_jira.job_queue:
            jira_job_queue = app_jira.job_queue
            logger.info("Đăng ký các Job Jira trên JobQueue của Bot Jira.")
        else:
            logger.error("Bot Jira không có JobQueue, dùng Bot chính thay thế.")
            jira_job_queue = job_queue
    else:
        jira_job_queue = job_queue

    if jira_job_queue:
        # Quét task Jira sắp đến hạn mỗi 1 giờ
        jira_job_queue.run_repeating(
            jira_due_reminder_job,
            interval=3600,
            first=30,
            name="jira_due_reminder"
        )

        # Cảnh báo rủi ro trễ hạn Jira bằng AI lúc 08:00 hàng ngày
        jira_job_queue.run_daily(
            jira_risk_alert_job,
            time=time(hour=8, minute=0, second=0, tzinfo=TZ),
            name="jira_risk_alert_8am"
        )

        # Cảnh báo rủi ro trễ hạn Jira bằng AI lúc 20:00 hàng ngày
        jira_job_queue.run_daily(
            jira_risk_alert_job,
            time=time(hour=20, minute=0, second=0, tzinfo=TZ),
            name="jira_risk_alert_8pm"
        )
    
    logger.info("Đã cài đặt Journal scheduler kèm theo Jira due reminder và AI Risk Alert")


