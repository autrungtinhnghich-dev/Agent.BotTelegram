"""
Chạy 1 lần trên máy local để lấy SESSION_STRING.
Copy kết quả vào file .env.

    python3 setup_session.py
"""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH


async def main():
    print("=" * 60)
    print("  Telegram Summarizer Bot — Setup Session")
    print("=" * 60)
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("\n[ERROR] Chưa set TELEGRAM_API_ID / TELEGRAM_API_HASH trong .env")
        print("  → https://my.telegram.org")
        return

    async with TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        session = client.session.save()

    print("\n✅ Thành công! Thêm dòng sau vào .env:\n")
    print(f"SESSION_STRING={session}")
    print("\n⚠️  Giữ bí mật SESSION_STRING — ai có chuỗi này truy cập được Telegram của bạn!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
