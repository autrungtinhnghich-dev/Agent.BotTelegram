import asyncio
import logging
import sys

import config

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


import socket
import subprocess

def is_running_in_docker() -> bool:
    import os
    return os.path.exists('/.dockerenv')


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def ensure_services():
    if is_running_in_docker():
        logger.info("Bot đang chạy trong Docker. Bỏ qua việc tự khởi chạy LLM Proxy và OpenCode Server trên host.")
        return

    # Khởi động LLM Proxy nếu chưa chạy
    if not is_port_open(8046):
        logger.info("Đang tự động khởi chạy LLM Proxy trên cổng 8046...")
        try:
            subprocess.Popen(
                ["python3", "-m", "uvicorn", "services.llm_proxy:app", "--host", "127.0.0.1", "--port", "8046"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            logger.error(f"Không thể khởi chạy LLM Proxy: {e}")

    # Khởi động OpenCode Server nếu chưa chạy
    if config.USE_LOCAL_OPENCODE and not is_port_open(4096):
        logger.info("Đang tự động khởi chạy OpenCode Local Server trên cổng 4096...")
        try:
            subprocess.Popen(
                ["opencode", "serve", "--port", "4096"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        except Exception as e:
            logger.error(f"Không thể khởi chạy OpenCode Server: {e}")


async def main():
    validate()
    ensure_services()

    from telegram.ext import Application
    from handlers.agent_bot import register_agent_bot_handlers

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
