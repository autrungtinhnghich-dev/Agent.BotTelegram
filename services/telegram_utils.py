"""
services/telegram_utils.py

Tiện ích gửi tin nhắn Telegram an toàn (handle long messages).
"""

import logging
from telegram import Bot
from telegram.constants import ChatAction
from functools import wraps

import asyncio
from telegram.error import TimedOut, NetworkError, BadRequest

logger = logging.getLogger(__name__)

def typing_action(fn):
    """Decorator hiển thị trạng thái 'typing...' khi xử lý lệnh."""
    @wraps(fn)
    async def wrapper(update, context, *args, **kwargs):
        if update.effective_chat:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, 
                action=ChatAction.TYPING
            )
        return await fn(update, context, *args, **kwargs)
    return wrapper

async def send_message_safe(bot: Bot, chat_id: int, text: str, **kwargs):
    """
    Gửi tin nhắn Telegram, tự động chia nhỏ nếu text quá dài (>4096 chars).
    Có chế độ retry khi lỗi mạng hoặc timeout.
    """
    MAX_LENGTH = 4000  # Dự phòng một chút so với 4096
    
    if not text:
        return

    async def _send_one(p_text: str, **p_kwargs):
        for attempt in range(1, 4):
            try:
                return await bot.send_message(chat_id=chat_id, text=p_text, **p_kwargs)
            except BadRequest as e:
                logger.error(f"Error sending message (BadRequest): {e}")
                if "parse_mode" in p_kwargs:
                    logger.warning("Retrying send without parse_mode due to BadRequest")
                    kwargs_plain = p_kwargs.copy()
                    kwargs_plain.pop("parse_mode", None)
                    try:
                        return await bot.send_message(chat_id=chat_id, text=p_text, **kwargs_plain)
                    except Exception as pe:
                        logger.error(f"Fallback send failed: {pe}")
                raise
            except (TimedOut, NetworkError) as e:
                logger.warning(f"Telegram send_message failed due to transient error (attempt {attempt}/3): {e}")
                if attempt == 3:
                    raise
                await asyncio.sleep(1.0 * attempt)

    if len(text) <= MAX_LENGTH:
        return await _send_one(text, **kwargs)

    # Chia nhỏ text theo dòng nếu được
    parts = []
    while len(text) > 0:
        if len(text) <= MAX_LENGTH:
            parts.append(text)
            break
            
        # Tìm vị trí ngắt dòng gần MAX_LENGTH nhất
        break_at = text.rfind("\n", 0, MAX_LENGTH)
        if break_at == -1:
            # Nếu không có ngắt dòng, cắt đại
            break_at = MAX_LENGTH
            
        parts.append(text[:break_at])
        text = text[break_at:].lstrip()

    last_msg = None
    for p in parts:
        last_msg = await _send_one(p, **kwargs)
    return last_msg

async def edit_message_safe(bot: Bot, chat_id: int, message_id: int, text: str, **kwargs):
    """
    Edit tin nhắn Telegram, tự động fallback nếu quá dài hoặc lỗi parse.
    Có chế độ retry khi lỗi mạng hoặc timeout.
    """
    MAX_LENGTH = 4000
    
    # Nếu text quá dài, xóa tin nhắn loading và gửi loạt tin nhắn mới sạch sẽ
    if len(text) > MAX_LENGTH:
        logger.warning(f"Text too long for edit ({len(text)}), deleting loading message and sending fresh messages")
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as de:
            logger.warning(f"Could not delete loading message: {de}")
        return await send_message_safe(bot, chat_id, text, **kwargs)

    for attempt in range(1, 4):
        try:
            return await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs)
        except BadRequest as e:
            logger.error(f"Error editing message (BadRequest): {e}")
            if "parse_mode" in kwargs:
                logger.warning("Retrying edit without parse_mode due to BadRequest")
                kwargs_plain = kwargs.copy()
                kwargs_plain.pop("parse_mode", None)
                try:
                    return await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs_plain)
                except Exception as pe:
                    logger.error(f"Fallback edit failed: {pe}")
            raise
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Telegram edit_message failed due to transient error (attempt {attempt}/3): {e}")
            if attempt == 3:
                raise
            await asyncio.sleep(1.0 * attempt)

