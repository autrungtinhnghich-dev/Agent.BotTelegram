"""
main.py
Chạy đồng thời:
  1. Telethon client  — đọc tin nhắn, lắng nghe mention
  2. PTB Application  — nhận /commands, trả kết quả

Mention listeners:
  A. Ai @mention BOT trong group → tóm tắt context → gửi về owner
  B. Ai @mention OWNER (bạn) trong group → phân tích tại sao họ tag,
     context đang nói gì, đề xuất cách reply → gửi về bot
"""

import asyncio
import logging
import sys

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram.ext import Application
from telegram import Bot

import config
from handlers.commands import register, register_jira_handlers, set_telethon
import services.fetcher as fetcher
import services.summarizer as summarizer
from services.journal_db import init_db
from handlers.journal import register_journal_handlers
from handlers.brain import register_brain_handlers                      # ← MỚI
from handlers.build import register_build_handlers                      # ← MỚI
from handlers.scraper import register_scraper_handlers                  # ← MỚI
from handlers.computer import register_computer_handlers                # ← MỚI
from handlers.delegate_handler import register_delegate_handlers
from handlers.docker_handler import register_docker_handlers
from handlers.code_search import register_code_search_handlers          # ← MỚI
from handlers.cicd_branch import register_cicd_branch_handlers          # ← MỚI 
from handlers.calculator import register_calculator_handlers
from services.build_db import init_build_db, seed_sample_data           # ← MỚI
from services.journal_scheduler import setup_scheduler
from handlers.agent_bot import register_agent_bot_handlers
from services.telegram_utils import send_message_safe
from services.markdown import escape, bold, build, ai_to_mdv2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def validate():
    missing = []
    if not config.TELEGRAM_API_ID:   missing.append("TELEGRAM_API_ID")
    if not config.TELEGRAM_API_HASH: missing.append("TELEGRAM_API_HASH")
    if not config.SESSION_STRING:    missing.append("SESSION_STRING")
    if not config.BOT_TOKEN:         missing.append("BOT_TOKEN")
    if not config.BOT_JIRA_TOKEN:    missing.append("BOT_JIRA_TOKEN")
    if not config.BOT_AGENT_TOKEN:   missing.append("BOT_AGENT_TOKEN")
    if not config.GEMINI_API_KEY:    missing.append("GEMINI_API_KEY")
    if not config.ALLOWED_USER_IDS:  missing.append("ALLOWED_USER_IDS")
    if not config.BOT_USERNAME:
        logger.warning("BOT_USERNAME chưa set — mention bot listener sẽ tắt")
    if missing:
        for m in missing:
            logger.error(f"  x {m} chưa được set trong .env")
        sys.exit(1)


# ─── A. Listener: ai mention @BOT ────────────────────────────

def setup_bot_mention_listener(telethon: TelegramClient, bot: Bot):
    if not config.BOT_USERNAME:
        return

    trigger = f"@{config.BOT_USERNAME}".lower()
    owner_id = config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None
    if not owner_id:
        return

    @telethon.on(events.NewMessage())
    async def on_bot_mentioned(event):
        if not event.message.text:
            return
        if not (event.is_group or event.is_channel):
            return
        if trigger not in event.message.text.lower():
            return

        try:
            sender_id = event.sender_id
            # Kiểm tra whitelist
            if config.ALLOWED_USER_IDS and sender_id not in config.ALLOWED_USER_IDS:
                logger.info(f"Bot mention ignored: User {sender_id} is not in whitelist {config.ALLOWED_USER_IDS}")
                return

            sender = await event.get_sender()
            if sender:
                trigger_user = getattr(sender, "first_name", "") or getattr(sender, "username", "Someone")
            else:
                trigger_user = "Someone"

            chat = await event.get_chat()
            chat_name = getattr(chat, "title", str(event.chat_id))

            logger.info(f"Bot mention triggered: {trigger_user} in {chat_name}")

            n = config.MENTION_CONTEXT
            result = await fetcher.fetch_last_n(telethon, chat, n + 1)
            # Lọc bỏ chính tin nhắn vừa tag
            result.messages = [m for m in result.messages if trigger not in m.text.lower()][:n]
            result.total_fetched = len(result.messages)

            summary = summarizer.summarize_mention(chat_name, result.messages, trigger_user)

            # 1. Gửi cho Owner (private)
            await send_message_safe(
                bot=bot,
                chat_id=owner_id,
                text=build(
                    f"🤖 {bold('Bot được mention trong nhóm!')}",
                    f"📍 Nhóm: {escape(chat_name)}",
                    f"👤 Người tag: {escape(trigger_user)}",
                    f"📝 Nội dung: {escape(event.message.text[:150])}",
                    "",
                    ai_to_mdv2(summary)
                ),
                parse_mode="HTML"
            )

            # 2. Phản hồi vào Group (public)
            try:
                from services.markdown import ai_to_mdv2, bold
                header = f"✨ {bold(f'Tóm tắt nhanh cho {trigger_user}:')}\n\n"
                body = ai_to_mdv2(summary)

                await send_message_safe(
                    bot=bot,
                    chat_id=event.chat_id,
                    text=header + body,
                    reply_to_message_id=event.message.id,
                    parse_mode="HTML"
                )
                logger.info(f"Sent group summary reply in {chat_name}")
            except Exception as group_err:
                logger.error(f"Failed to send group reply in {chat_name}: {group_err}")
                await send_message_safe(
                    bot=bot,
                    chat_id=owner_id,
                    text=build(
                        f"⚠️ {bold('Không thể trả lời tóm tắt trong nhóm!')}",
                        f"📍 Nhóm: {escape(chat_name)}",
                        f"❌ Lỗi: {escape(str(group_err))}",
                        "",
                        f"👉 Mẹo: Để bot có thể trả lời trực tiếp trong nhóm, hãy đảm bảo bạn đã thêm bot @{config.BOT_USERNAME} vào nhóm đó nhé!"
                    ),
                    parse_mode="HTML"
                )

        except Exception as e:
            logger.error(f"Bot mention handler error: {e}", exc_info=True)

    logger.info(f"Bot mention listener: ON — theo doi '{trigger}'")


# ─── B. Listener: ai mention @OWNER (bạn) ────────────────────

def setup_owner_mention_listener(telethon: TelegramClient, bot: Bot):
    """
    Lắng nghe khi ai tag chính bạn (@your_username) trong group.
    Phân tích:
      - Họ đang nói gì / hỏi gì
      - Context xung quanh là gì
      - Đề xuất cách reply phù hợp
    """
    owner_username = config.OWNER_USERNAME
    if not owner_username:
        logger.info("Owner mention listener: OFF (chưa có OWNER_USERNAME)")
        return

    owner_id = config.ALLOWED_USER_IDS[0] if config.ALLOWED_USER_IDS else None
    if not owner_id:
        return

    trigger = f"@{owner_username}".lower()

    @telethon.on(events.NewMessage())
    async def on_owner_mentioned(event):
        if not event.message.text:
            return
        if not (event.is_group or event.is_channel):
            return
        if trigger not in event.message.text.lower():
            return

        try:
            sender = await event.get_sender()
            if sender:
                sender_name = getattr(sender, "first_name", "") or getattr(sender, "username", "Someone")
                sender_username = getattr(sender, "username", "")
            else:
                sender_name = "Someone"
                sender_username = ""

            chat = await event.get_chat()
            chat_name = getattr(chat, "title", str(event.chat_id))
            mention_text = event.message.text

            logger.info(f"Owner mention triggered: {sender_name} in {chat_name}")

            # Lưu real-time vào DB
            try:
                from datetime import datetime
                import pytz
                from services.journal_db import add_owner_mention
                
                vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
                now_str = datetime.now(vn_tz).strftime("%Y-%m-%d %H:%M:%S")
                
                await add_owner_mention(
                    sender_id=sender.id if sender else 0,
                    sender_name=sender_name,
                    sender_username=sender_username,
                    chat_id=event.chat_id,
                    chat_name=chat_name,
                    message_id=event.message.id,
                    message_text=mention_text,
                    created_at=now_str
                )
            except Exception as db_err:
                logger.error(f"Lỗi khi lưu mention real-time vào DB: {db_err}")

            n = config.MENTION_CONTEXT
            result = await fetcher.fetch_last_n(telethon, chat, n)
            result.total_fetched = len(result.messages)

            analysis = summarizer.analyze_owner_mention(
                chat_name=chat_name,
                mention_text=mention_text,
                sender_name=sender_name,
                sender_username=sender_username,
                context_messages=result.messages,
                owner_username=owner_username,
            )

            await send_message_safe(
                bot=bot,
                chat_id=owner_id,
                text=build(
                    f"🔔 {bold('Bạn bị tag trong nhóm!')}",
                    f"📍 Nhóm: {escape(chat_name)}",
                    f"👤 Người tag: {escape(sender_name)}" + (f" (@{escape(sender_username)})" if sender_username else ""),
                    "",
                    ai_to_mdv2(analysis)
                ),
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"Owner mention handler error: {e}")

    logger.info(f"Owner mention listener: ON — theo dõi '{trigger}' trong tất cả group")


# ─── Main ─────────────────────────────────────────────────────

async def main():
    validate()

    telethon = TelegramClient(
        StringSession(config.SESSION_STRING),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    await telethon.start()
    me = await telethon.get_me()
    logger.info(f"Telethon: {me.first_name} (@{me.username})")

    set_telethon(telethon)

    app = Application.builder().token(config.BOT_TOKEN).build()
    register_journal_handlers(app)
    register_brain_handlers(app)                                        # ← MỚI
    register_scraper_handlers(app)                                      # ← MỚI
    register_computer_handlers(app)                                     # ← MỚI
    register_delegate_handlers(app)
    register_docker_handlers(app)
    register_code_search_handlers(app)                                  # ← MỚI
    register_calculator_handlers(app)                                   # ← MỚI
    register(app)

    # Khởi tạo Bot Jira phụ
    app_jira = Application.builder().token(config.BOT_JIRA_TOKEN).build()
    register_jira_handlers(app_jira)
    register_build_handlers(app_jira)                                   # Chuyển Build sang Bot Jira
    register_cicd_branch_handlers(app_jira)                             # ← MỚI
    register_delegate_handlers(app_jira)
    register_docker_handlers(app_jira)
    register_code_search_handlers(app_jira)                              # ← MỚI

    # Khởi tạo Bot Agent
    app_agent = Application.builder().token(config.BOT_AGENT_TOKEN).build()
    register_agent_bot_handlers(app_agent)

    # Đăng ký cả 2 listeners (vẫn dùng bot chính để thông báo cho owner khi bị tag)
    setup_bot_mention_listener(telethon, app.bot)
    setup_owner_mention_listener(telethon, app.bot)

    # Khởi tạo Journal DB, Build DB và Scheduler
    await init_db()
    await init_build_db()                                               # ← MỚI
    await seed_sample_data()                                            # ← MỚI
    setup_scheduler(app, app_jira)

    # Khởi chạy Bot chính
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Khởi chạy Bot Jira
    await app_jira.initialize()
    await app_jira.start()
    await app_jira.updater.start_polling(drop_pending_updates=True)

    # Khởi chạy Bot Agent
    await app_agent.initialize()
    await app_agent.start()
    await app_agent.updater.start_polling(drop_pending_updates=True)

    logger.info("Cả ba Bot đang chạy...")
    logger.info(f"Whitelist: {config.ALLOWED_USER_IDS}")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Đang tắt...")
        # Dừng Bot Jira
        await app_jira.updater.stop()
        await app_jira.stop()
        await app_jira.shutdown()

        # Dừng Bot Agent
        await app_agent.updater.stop()
        await app_agent.stop()
        await app_agent.shutdown()
        
        # Dừng Bot chính
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        
        await telethon.disconnect()
        logger.info("Da dung.")


if __name__ == "__main__":
    asyncio.run(main())
