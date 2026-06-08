import asyncio
import logging
import sys

from telegram.ext import Application

import config
from handlers.agent_bot import register_agent_bot_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def validate():
    missing = []
    if not config.BOT_AGENT_TOKEN:   missing.append("BOT_AGENT_TOKEN")
    if not config.GEMINI_API_KEY and not config.USE_LOCAL_OPENCODE:
        missing.append("GEMINI_API_KEY (hoặc kích hoạt USE_LOCAL_OPENCODE)")
    if not config.ALLOWED_USER_IDS:  missing.append("ALLOWED_USER_IDS")
    if missing:
        for m in missing:
            logger.error(f"  x {m} chưa được set trong .env")
        sys.exit(1)


async def main():
    validate()

    # Khởi tạo Bot Agent
    app_agent = Application.builder().token(config.BOT_AGENT_TOKEN).build()
    register_agent_bot_handlers(app_agent)

    # Khởi chạy Bot Agent
    await app_agent.initialize()
    await app_agent.start()
    await app_agent.updater.start_polling(drop_pending_updates=True)

    logger.info("Bot Agent đang chạy...")
    logger.info(f"Whitelist: {config.ALLOWED_USER_IDS}")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Đang tắt...")
        # Dừng Bot Agent
        await app_agent.updater.stop()
        await app_agent.stop()
        await app_agent.shutdown()
        logger.info("Đã dừng.")


if __name__ == "__main__":
    asyncio.run(main())
