"""
services/fetcher.py
Fetch messages từ Telegram trực tiếp qua Telethon.
"""

from __future__ import annotations
import re
import logging
from datetime import date, datetime, timezone
from dataclasses import dataclass, field
from collections import Counter

from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel

logger = logging.getLogger(__name__)


# ─── Markdown escape ─────────────────────────────────────────

def md_escape(text: str) -> str:
    """Escape ký tự đặc biệt cho Telegram Markdown v1."""
    return re.sub(r"([_*`\[])", r"\\\1", text or "")


# ─── Data classes ────────────────────────────────────────────

@dataclass
class Message:
    user: str
    user_id: int
    text: str
    date: object

    def format(self) -> str:
        ts = self.date.strftime("%H:%M")
        return f"[{ts}] {self.user}: {self.text}"


@dataclass
class FetchResult:
    messages: list[Message] = field(default_factory=list)
    chat_name: str = ""
    chat_id: int = 0
    total_fetched: int = 0
    error: str = ""

    def ok(self) -> bool:
        return not self.error

    def formatted_text(self) -> str:
        return "\n".join(m.format() for m in self.messages)

    def user_stats(self) -> dict[str, int]:
        return dict(Counter(m.user for m in self.messages).most_common())


# ─── Helpers ─────────────────────────────────────────────────

async def _get_sender_name(msg) -> tuple[str, int]:
    try:
        sender = await msg.get_sender()
        if isinstance(sender, User):
            name = f"{sender.first_name or ''} {sender.last_name or ''}".strip() or f"User{sender.id}"
            return name, sender.id
        if hasattr(sender, "title"):
            return sender.title, getattr(sender, "id", 0)
    except Exception:
        pass
    return "Unknown", 0


def _fuzzy_score(query: str, name: str) -> int:
    """
    Điểm tương đồng 0-100 giữa query và tên chat.
    Không cần khớp chính xác — tìm gần đúng.
    """
    q = query.lower().strip()
    n = name.lower().strip()

    if not q or not n:
        return 0
    if q == n:
        return 100
    if q in n:
        return 70 + int(len(q) / max(len(n), 1) * 29)

    # Khớp theo từng từ của query
    q_words = q.split()
    matched_words = sum(1 for w in q_words if w in n)
    if matched_words:
        return int(matched_words / len(q_words) * 65)

    # Fallback: đếm ký tự chung
    common = sum(1 for c in q if c in n)
    return int(common / max(len(q), 1) * 30)


# ─── Resolve chat ─────────────────────────────────────────────

async def resolve_chat(client: TelegramClient, query: str):
    """
    Tìm chat theo @username, link, chat_id, hoặc tên gần đúng.
    Trả về (entity, matched_name) hoặc (None, "")
    """
    query = query.strip()

    # Theo @username hoặc link
    if query.startswith("@") or query.startswith("https://t.me/"):
        try:
            entity = await client.get_entity(query)
            return entity, getattr(entity, "title", query)
        except Exception as e:
            logger.warning(f"get_entity failed for {query}: {e}")

    # Theo chat_id số
    if query.lstrip("-").isdigit():
        try:
            entity = await client.get_entity(int(query))
            return entity, getattr(entity, "title", query)
        except Exception:
            pass

    # Fuzzy search trong dialog list
    best_entity = None
    best_name = ""
    best_score = 0

    async for dialog in client.iter_dialogs():
        score = _fuzzy_score(query, dialog.name)
        if score > best_score:
            best_score = score
            best_entity = dialog.entity
            best_name = dialog.name

    if best_entity and best_score >= 25:
        logger.info(f"Fuzzy: '{query}' -> '{best_name}' (score={best_score})")
        return best_entity, best_name

    return None, ""


# ─── Fetch functions ──────────────────────────────────────────

async def fetch_last_n(client: TelegramClient, chat, n: int) -> FetchResult:
    from config import MAX_MESSAGES
    n = min(n, MAX_MESSAGES)
    result = FetchResult()
    result.chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "Unknown")
    result.chat_id = getattr(chat, "id", 0)

    collected = []
    async for msg in client.iter_messages(chat, limit=n * 2):
        if not msg.text:
            continue
        user, uid = await _get_sender_name(msg)
        collected.append(Message(user=user, user_id=uid, text=msg.text, date=msg.date))
        if len(collected) >= n:
            break

    collected.reverse()
    result.messages = collected
    result.total_fetched = len(collected)
    return result


async def fetch_today(client: TelegramClient, chat) -> FetchResult:
    from config import MAX_MESSAGES
    today = date.today()
    result = FetchResult()
    result.chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "Unknown")

    collected = []
    async for msg in client.iter_messages(chat, limit=MAX_MESSAGES):
        if not msg.text:
            continue
        if msg.date.astimezone(timezone.utc).date() < today:
            break
        user, uid = await _get_sender_name(msg)
        collected.append(Message(user=user, user_id=uid, text=msg.text, date=msg.date))

    collected.reverse()
    result.messages = collected
    result.total_fetched = len(collected)
    return result


async def search_messages(client: TelegramClient, chat, keyword: str, limit: int = 30) -> FetchResult:
    result = FetchResult()
    result.chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "Unknown")

    collected = []
    async for msg in client.iter_messages(chat, search=keyword, limit=limit):
        if not msg.text:
            continue
        user, uid = await _get_sender_name(msg)
        collected.append(Message(user=user, user_id=uid, text=msg.text, date=msg.date))

    collected.reverse()
    result.messages = collected
    result.total_fetched = len(collected)
    return result


async def list_dialogs(client: TelegramClient, limit: int = 50) -> list[dict]:
    """Liệt kê tất cả chat/group đang tham gia."""
    dialogs = []
    async for dialog in client.iter_dialogs(limit=limit):
        entity = dialog.entity
        kind = "👤"
        if isinstance(entity, Chat):
            kind = "👥"
        elif isinstance(entity, Channel):
            kind = "📢" if getattr(entity, "broadcast", False) else "👥"
        dialogs.append({
            "name": dialog.name,
            "id": dialog.id,
            "username": getattr(entity, "username", None),
            "kind": kind,
            "unread": dialog.unread_count,
        })
    return dialogs


async def fetch_since(client: TelegramClient, chat, since_dt: datetime) -> FetchResult:
    """
    Fetch tất cả tin nhắn từ thời điểm since_dt đến hiện tại.
    Dùng cho Spy Mode — lấy tin nhắn trong khoảng thời gian cụ thể.
    """
    from config import MAX_MESSAGES
    result = FetchResult()
    result.chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "Unknown")
    result.chat_id = getattr(chat, "id", 0)

    # Đảm bảo since_dt có timezone để so sánh
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    collected = []
    async for msg in client.iter_messages(chat, limit=MAX_MESSAGES):
        if not msg.text:
            continue
        # Đảm bảo msg.date có timezone
        msg_date = msg.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)

        # Dừng khi vượt qua mốc thời gian
        if msg_date < since_dt:
            break

        user, uid = await _get_sender_name(msg)
        collected.append(Message(user=user, user_id=uid, text=msg.text, date=msg_date))

    collected.reverse()  # Sắp xếp cũ → mới
    result.messages = collected
    result.total_fetched = len(collected)
    return result


async def sync_owner_mentions(client: TelegramClient, owner_username: str, days: int = 30) -> int:
    """
    Quét Telegram để tìm các tin nhắn mention @owner_username trong `days` ngày qua
    và cập nhật vào database.
    """
    from datetime import datetime, timedelta, timezone
    import pytz
    from services.journal_db import add_owner_mention
    
    # Mốc thời gian bắt đầu quét
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    
    query = f"@{owner_username}"
    logger.info(f"Đang sync tin nhắn tag '{query}' từ {days} ngày trước...")
    
    sync_count = 0
    try:
        # iter_messages với chat=None sẽ tìm kiếm toàn cục
        async for msg in client.iter_messages(None, search=query, limit=500):
            # Kiểm tra thời gian
            msg_date = msg.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
                
            if msg_date < since_dt:
                continue
                
            # Lấy thông tin chat
            try:
                chat = await msg.get_chat()
                chat_name = getattr(chat, "title", None) or getattr(chat, "first_name", "Private Chat")
                chat_id = msg.chat_id
            except Exception:
                chat_name = "Unknown Chat"
                chat_id = msg.chat_id or 0
                
            # Lấy thông tin sender
            try:
                sender = await msg.get_sender()
                if sender:
                    sender_name = f"{getattr(sender, 'first_name', '') or ''} {getattr(sender, 'last_name', '') or ''}".strip() or getattr(sender, 'username', 'Someone')
                    sender_username = getattr(sender, "username", "")
                    sender_id = sender.id
                else:
                    sender_name = "Someone"
                    sender_username = ""
                    sender_id = 0
            except Exception:
                sender_name = "Someone"
                sender_username = ""
                sender_id = 0
                
            # Convert msg_date sang string format YYYY-MM-DD HH:MM:SS
            # Đảm bảo timezone là Asia/Ho_Chi_Minh cho dễ đọc
            try:
                vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
                msg_date_vn = msg_date.astimezone(vn_tz)
                created_at_str = msg_date_vn.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at_str = msg_date.strftime("%Y-%m-%d %H:%M:%S")
                
            # Lưu vào DB
            success = await add_owner_mention(
                sender_id=sender_id,
                sender_name=sender_name,
                sender_username=sender_username,
                chat_id=chat_id,
                chat_name=chat_name,
                message_id=msg.id,
                message_text=msg.text or "",
                created_at=created_at_str
            )
            if success:
                sync_count += 1
                
        logger.info(f"Đã sync thành công {sync_count} tin nhắn tag mới.")
    except Exception as e:
        logger.error(f"Lỗi khi sync owner mentions: {e}", exc_info=True)
        
    return sync_count
