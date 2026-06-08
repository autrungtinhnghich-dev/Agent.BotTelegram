import aiosqlite
import logging
from datetime import datetime, timedelta
import json
import config
import pytz

def _get_today_date_str() -> str:
    tz = pytz.timezone(config.JOURNAL_TZ)
    return datetime.now(tz).strftime("%Y-%m-%d")

def _get_now_iso() -> str:
    tz = pytz.timezone(config.JOURNAL_TZ)
    return datetime.now(tz).isoformat()


logger = logging.getLogger(__name__)

async def init_db():
    """Khởi tạo database và các bảng cần thiết."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sentiment TEXT,
                topics TEXT,
                score REAL,
                created_at TEXT NOT NULL
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS vocab_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                word_en TEXT NOT NULL,
                word_zh TEXT NOT NULL,
                word_ja TEXT NOT NULL,
                meaning_vi TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS journal_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                notify_hour INTEGER DEFAULT 8,
                notify_minute INTEGER DEFAULT 0,
                streak_count INTEGER DEFAULT 0,
                last_entry_date TEXT,
                joined_at TEXT NOT NULL
            )
        """)
        
        # Migration: Thêm cột notify_minute nếu chưa có
        try:
            await db.execute("ALTER TABLE journal_users ADD COLUMN notify_minute INTEGER DEFAULT 0")
            logger.info("Đã thêm cột notify_minute vào journal_users")
        except Exception:
            # Cột đã tồn tại
            pass
        
        # Index để query nhanh theo user và date
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entries_user_date ON journal_entries (user_id, date)")

        # Kiến thức cá nhân (Personal Brain)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                tags TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Bảng FTS5 để tìm kiếm nhanh
        try:
            await db.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    content,
                    content_rowid='id'
                )
            """)
        except Exception as e:
            logger.warning(f"Không thể tạo bảng FTS5: {e}")

        # Jira due date notifications
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jira_due_notifications (
                issue_key TEXT NOT NULL,
                notified_level REAL NOT NULL,
                notified_at TEXT NOT NULL,
                PRIMARY KEY (issue_key, notified_level)
            )
        """)

        # AI Delegate Tasks
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delegate_tasks (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                status TEXT NOT NULL,
                result_summary TEXT,
                result_file_path TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)

        # Owner Mentions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS owner_mentions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                sender_name TEXT,
                sender_username TEXT,
                chat_id INTEGER NOT NULL,
                chat_name TEXT,
                message_id INTEGER NOT NULL,
                message_text TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(chat_id, message_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mentions_created ON owner_mentions (created_at)")

        await db.commit()
    logger.info(f"Đã khởi tạo database tại {config.JOURNAL_DB_PATH}")

async def get_user(user_id: int):
    """Lấy thông tin user journal."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM journal_users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def upsert_user(user_id: int, username: str = None):
    """Tạo mới hoặc cập nhật thông tin user."""
    now = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            INSERT INTO journal_users (user_id, username, joined_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET 
                username = COALESCE(?, username)
        """, (user_id, username, now, username))
        await db.commit()

async def calculate_streaks(user_id: int):
    """
    Tính toán thông tin chuỗi ngày (streak) từ tất cả các entry của user.
    Trả về: {
        "current_streak": int,
        "longest_streak": int,
        "streaks": list[dict], (start, end, length)
        "recent_gaps": list[str] (dạng YYYY-MM-DD)
    }
    """
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute(
            "SELECT DISTINCT date FROM journal_entries WHERE user_id = ? ORDER BY date ASC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            
    # Parse dates
    dates = []
    for r in rows:
        try:
            dates.append(datetime.strptime(r[0], "%Y-%m-%d").date())
        except ValueError:
            pass
            
    tz = pytz.timezone(config.JOURNAL_TZ)
    today = datetime.now(tz).date()
    
    if not dates:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "streaks": [],
            "recent_gaps": []
        }
        
    streaks = []
    current_segment = None
    
    for d in dates:
        if current_segment is None:
            current_segment = {"start": d, "end": d, "length": 1}
        else:
            prev_end = current_segment["end"]
            if d == prev_end + timedelta(days=1):
                current_segment["end"] = d
                current_segment["length"] += 1
            elif d > prev_end + timedelta(days=1):
                streaks.append(current_segment)
                current_segment = {"start": d, "end": d, "length": 1}
                
    if current_segment:
        streaks.append(current_segment)
        
    longest_streak = max(s["length"] for s in streaks) if streaks else 0
    
    # Tính streak hiện tại:
    # Nếu ngày cuối cùng của chuỗi cuối cùng là hôm nay hoặc hôm qua
    last_streak = streaks[-1]
    last_end = last_streak["end"]
    
    if last_end == today or last_end == today - timedelta(days=1):
        current_streak = last_streak["length"]
    else:
        current_streak = 0
        
    # Tìm khoảng trống (gaps) trong vòng 4 ngày qua (để có thể viết bù)
    # Chỉ tìm gap từ ngày có entry đầu tiên
    first_entry_date = dates[0]
    recent_gaps = []
    date_set = set(dates)
    
    # Kiểm tra các ngày từ (today - 4 ngày) tới (today - 1 ngày) (hôm qua)
    # Và không kiểm tra trước ngày viết entry đầu tiên
    start_check = max(today - timedelta(days=4), first_entry_date)
    curr = start_check
    while curr < today:
        if curr not in date_set:
            recent_gaps.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=1)
        
    # Format streaks to serializable format (strings for dates)
    formatted_streaks = []
    for s in streaks:
        formatted_streaks.append({
            "start": s["start"].strftime("%Y-%m-%d"),
            "end": s["end"].strftime("%Y-%m-%d"),
            "length": s["length"]
        })
        
    return {
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "streaks": formatted_streaks,
        "recent_gaps": sorted(recent_gaps, reverse=True) # đưa ngày gần nhất lên trước
    }

async def recalculate_and_update_user_streak(user_id: int):
    """
    Tính toán lại và cập nhật thông tin streak vào bảng journal_users.
    Trả về (current_streak, longest_streak).
    """
    info = await calculate_streaks(user_id)
    current_streak = info["current_streak"]
    
    # Lấy ngày entry lớn nhất (cuối cùng)
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(date) FROM journal_entries WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            last_date = row[0] if row else None
            
        await db.execute("""
            UPDATE journal_users 
            SET streak_count = ?, last_entry_date = ? 
            WHERE user_id = ?
        """, (current_streak, last_date, user_id))
        await db.commit()
        
    return current_streak, info["longest_streak"]

async def add_entry(user_id: int, question: str, answer: str, date_str: str = None):
    """Lưu một entry nhật ký mới. Trả về (entry_id, streak)."""
    if not date_str:
        date_str = _get_today_date_str()
    
    now_iso = _get_now_iso()
    
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO journal_entries (user_id, date, question, answer, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, date_str, question, answer, now_iso))
        entry_id = cursor.lastrowid
        await db.commit()
        
    # Cập nhật streak
    current_streak, _ = await recalculate_and_update_user_streak(user_id)
    return entry_id, current_streak

async def has_answered_today(user_id: int, date_str: str = None):
    """Kiểm tra xem user đã trả lời hôm nay chưa."""
    if not date_str:
        date_str = _get_today_date_str()
    
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM journal_entries WHERE user_id = ? AND date = ?", 
            (user_id, date_str)
        ) as cursor:
            return await cursor.fetchone() is not None

async def update_entry_ai(entry_id: int, sentiment: str, topics: list, score: float):
    """Cập nhật kết quả phân tích AI cho một entry."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            UPDATE journal_entries 
            SET sentiment = ?, topics = ?, score = ?
            WHERE id = ?
        """, (sentiment, json.dumps(topics), score, entry_id))
        await db.commit()

async def get_recent_entries(user_id: int, limit: int = 7):
    """Lấy danh sách entries gần nhất của user."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM journal_entries WHERE user_id = ? ORDER BY date DESC LIMIT ?", 
            (user_id, limit)
        ) as cursor:
            return await cursor.fetchall()

async def get_recent_vocabs(limit: int = 5):
    """Lấy danh sách các từ vựng đã gửi gần đây."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM vocab_history ORDER BY date DESC LIMIT ?", 
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

async def get_random_vocabs(limit: int = 4):
    """Lấy N từ vựng ngẫu nhiên để làm quiz."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM vocab_history ORDER BY RANDOM() LIMIT ?", 
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

async def get_daily_vocab(date_str: str = None):
    """Lấy từ vựng của một ngày cụ thể."""
    if not date_str:
        date_str = _get_today_date_str()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM vocab_history WHERE date = ?", 
            (date_str,)
        ) as cursor:
            return await cursor.fetchone()

async def save_daily_vocab(date_str: str, vocab_data: dict):
    """Lưu từ vựng mới vào DB."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO vocab_history (date, word_en, word_zh, word_ja, meaning_vi, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date_str, vocab_data['en'], vocab_data['zh'], vocab_data['ja'], vocab_data['vi'], now_iso))
        await db.commit()

async def get_or_create_daily_vocab():
    """Lấy từ vựng hôm nay, nếu chưa có thì gọi AI tạo mới."""
    date_str = _get_today_date_str()
    vocab = await get_daily_vocab(date_str)
    if vocab:
        return dict(vocab)
        
    from services.vocab_ai import generate_daily_vocab_ai
    recent = await get_recent_vocabs(limit=14)
    recent_words = [r['word_en'] for r in recent]
    
    new_vocab = await generate_daily_vocab_ai(recent_words)
    if new_vocab:
        await save_daily_vocab(date_str, new_vocab)
        # Trả về với key đồng nhất với database để handler hiển thị được ngay lần đầu
        return {
            'date': date_str,
            'word_en': new_vocab['en'],
            'word_zh': new_vocab['zh'],
            'word_ja': new_vocab['ja'],
            'meaning_vi': new_vocab['vi']
        }
    return None

# ─── Knowledge Base (Brain) ─────────────────────────────────

async def add_knowledge(user_id: int, content: str, source: str = "message", tags: str = ""):
    """Lưu kiến thức mới vào bộ nhớ."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO knowledge_base (user_id, content, source, tags, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, content, source, tags, now_iso))
        row_id = cursor.lastrowid
        
        # Cập nhật vào FTS index
        try:
            await db.execute("INSERT INTO knowledge_fts (rowid, content) VALUES (?, ?)", (row_id, content))
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật FTS index: {e}")
            
        await db.commit()
        return row_id

async def search_knowledge(query: str, limit: int = 5):
    """Tìm kiếm kiến thức bằng FTS5."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Thử tìm bằng FTS5 trước
        try:
            async with db.execute("""
                SELECT k.* FROM knowledge_base k
                JOIN knowledge_fts f ON k.id = f.rowid
                WHERE knowledge_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)) as cursor:
                results = await cursor.fetchall()
                if results:
                    return [dict(r) for r in results]
        except Exception:
            pass

        # Nếu FTS thất bại hoặc không có kết quả, dùng LIKE (fallback)
        async with db.execute("""
            SELECT * FROM knowledge_base 
            WHERE content LIKE ? OR tags LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit)) as cursor:
            results = await cursor.fetchall()
            return [dict(r) for r in results]

async def search_srs_knowledge(query: str, limit: int = 8):
    """Tìm kiếm tài liệu đặc tả SRS bằng FTS5 (chỉ lọc tags = 'srs')."""
    import re
    # Dọn dẹp query FTS5 để tránh lỗi cú pháp và tách từ khóa bằng OR
    cleaned_query = re.sub(r'[^\w\s]', ' ', query)
    # Lọc các từ từ 3 ký tự trở lên để tránh noise
    words = [w.strip() for w in cleaned_query.split() if len(w.strip()) >= 3]
    fts_query = " OR ".join(words) if words else query

    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            if fts_query:
                async with db.execute("""
                    SELECT k.* FROM knowledge_base k
                    JOIN knowledge_fts f ON k.id = f.rowid
                    WHERE knowledge_fts MATCH ? AND k.tags = 'srs'
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit)) as cursor:
                    results = await cursor.fetchall()
                    if results:
                        return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"FTS search for SRS failed: {e}")
            pass

        # LIKE fallback chỉ lọc tags = 'srs'
        fallback_term = words[0] if words else query
        async with db.execute("""
            SELECT * FROM knowledge_base 
            WHERE tags = 'srs' AND (content LIKE ? OR source LIKE ?)
            ORDER BY created_at DESC
            LIMIT ?
        """, (f"%{fallback_term}%", f"%{fallback_term}%", limit)) as cursor:
            results = await cursor.fetchall()
            return [dict(r) for r in results]

async def list_srs_files():
    """Lấy danh sách các tài liệu đặc tả SRS đã được lập chỉ mục kèm theo số lượng chunk và thời gian tạo."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT source, COUNT(*) as chunk_count, MIN(created_at) as created_at
            FROM knowledge_base
            WHERE tags = 'srs'
            GROUP BY source
            ORDER BY created_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            # Dọn dẹp prefix 'srs:' trước khi trả về
            result = []
            for r in rows:
                source = r['source']
                clean_name = source[4:] if source.startswith("srs:") else source
                result.append({
                    "raw_source": source,
                    "file_name": clean_name,
                    "chunk_count": r['chunk_count'],
                    "created_at": r['created_at']
                })
            return result

async def check_srs_file_exists(file_name: str) -> bool:
    """Kiểm tra xem tài liệu đặc tả SRS cùng tên (hoặc ZIP chứa nó) đã tồn tại trong DB chưa."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute("""
            SELECT 1 FROM knowledge_base 
            WHERE tags = 'srs' AND (source = ? OR source LIKE ?)
            LIMIT 1
        """, (f"srs:{file_name}", f"srs:{file_name}/%")) as cursor:
            return await cursor.fetchone() is not None

async def delete_srs_file(file_name: str) -> int:
    """Xóa tất cả các đoạn dữ liệu đặc tả SRS của file cùng tên khỏi database và FTS index."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute("""
            SELECT id FROM knowledge_base 
            WHERE tags = 'srs' AND (source = ? OR source LIKE ?)
        """, (f"srs:{file_name}", f"srs:{file_name}/%")) as cursor:
            rows = await cursor.fetchall()
            ids = [r[0] for r in rows]
            
        if ids:
            placeholders = ",".join("?" for _ in ids)
            # Xóa khỏi knowledge_base
            await db.execute(f"DELETE FROM knowledge_base WHERE id IN ({placeholders})", ids)
            # Xóa khỏi FTS index
            await db.execute(f"DELETE FROM knowledge_fts WHERE rowid IN ({placeholders})", ids)
            await db.commit()
            return len(ids)
        return 0

async def delete_knowledge(kb_id: int):
    """Xóa một mẩu kiến thức."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("DELETE FROM knowledge_base WHERE id = ?", (kb_id,))
        await db.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (kb_id,))
        await db.commit()


async def is_jira_due_notified(issue_key: str, level: float) -> bool:
    """Check if a due notification for a given level (1.0 or 0.5) has been sent."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM jira_due_notifications WHERE issue_key = ? AND notified_level = ?",
            (issue_key, level)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_jira_due_notified(issue_key: str, level: float):
    """Mark a due notification of a specific level as sent."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO jira_due_notifications (issue_key, notified_level, notified_at)
            VALUES (?, ?, ?)
        """, (issue_key, level, now_iso))
        await db.commit()


async def is_jira_risk_notified(issue_key: str, risk_level: str, jira_updated_at: str) -> bool:
    """Check if a risk notification for a given level and updated timestamp has been sent."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM jira_risk_notifications WHERE issue_key = ? AND risk_level = ? AND jira_updated_at = ?",
            (issue_key, risk_level, jira_updated_at)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_jira_risk_notified(issue_key: str, risk_level: str, jira_updated_at: str):
    """Mark a risk notification as sent with the issue's last updated timestamp."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO jira_risk_notifications (issue_key, risk_level, jira_updated_at, notified_at)
            VALUES (?, ?, ?, ?)
        """, (issue_key, risk_level, jira_updated_at, now_iso))
        await db.commit()


async def create_delegate_task(task_id: str, user_id: int, topic: str):
    """Tạo một task nghiên cứu chạy ngầm mới."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            INSERT INTO delegate_tasks (id, user_id, topic, status, created_at)
            VALUES (?, ?, ?, 'running', ?)
        """, (task_id, user_id, topic, now_iso))
        await db.commit()


async def update_delegate_task(task_id: str, status: str, result_summary: str = None, result_file_path: str = None):
    """Cập nhật trạng thái và kết quả của task nghiên cứu."""
    now_iso = _get_now_iso()
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        await db.execute("""
            UPDATE delegate_tasks
            SET status = ?, result_summary = ?, result_file_path = ?, completed_at = ?
            WHERE id = ?
        """, (status, result_summary, result_file_path, now_iso, task_id))
        await db.commit()


async def get_delegate_tasks(user_id: int, limit: int = 10):
    """Lấy danh sách các task nghiên cứu của user."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM delegate_tasks
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit)) as cursor:
            results = await cursor.fetchall()
            return [dict(r) for r in results]


# ─── Owner Mentions (Tag stats) ─────────────────────────────

async def add_owner_mention(
    sender_id: int, 
    sender_name: str, 
    sender_username: str, 
    chat_id: int, 
    chat_name: str, 
    message_id: int, 
    message_text: str, 
    created_at: str
) -> bool:
    """Lưu một tin nhắn tag chủ sở hữu vào DB. Trả về True nếu thêm mới, False nếu đã tồn tại."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        try:
            cursor = await db.execute("""
                INSERT OR IGNORE INTO owner_mentions (
                    sender_id, sender_name, sender_username, chat_id, chat_name, message_id, message_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sender_id, sender_name, sender_username, chat_id, chat_name, message_id, message_text, created_at))
            await db.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Lỗi khi lưu owner mention: {e}")
            return False


async def get_owner_mentions_stats(since_date: str) -> list[dict]:
    """Lấy danh sách thống kê số lượng tag theo từng người từ ngày since_date."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT sender_id, sender_name, sender_username, COUNT(*) as tag_count
            FROM owner_mentions
            WHERE created_at >= ?
            GROUP BY sender_id, sender_name, sender_username
            ORDER BY tag_count DESC
        """, (since_date,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_owner_mentions_raw(since_date: str, limit: int = 150) -> list[dict]:
    """Lấy danh sách các tin nhắn tag thô từ ngày since_date để phân tích AI."""
    async with aiosqlite.connect(config.JOURNAL_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT sender_name, chat_name, message_text, created_at
            FROM owner_mentions
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (since_date, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


