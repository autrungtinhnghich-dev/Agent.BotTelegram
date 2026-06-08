import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram User Account (Telethon — đọc tin nhắn) ────────
TELEGRAM_API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_STRING    = os.getenv("SESSION_STRING", "")

# ─── Telegram Bot (nhận lệnh, trả kết quả) ──────────────────
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
BOT_JIRA_TOKEN    = os.getenv("BOT_JIRA_TOKEN", "")
BOT_AGENT_TOKEN   = os.getenv("BOT_AGENT_TOKEN", "")

# ─── Whitelist — chỉ những user_id này mới dùng được ────────
# Lấy user_id bằng cách nhắn @userinfobot trên Telegram
ALLOWED_USER_IDS  = [
    int(x.strip())
    for x in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
]

# ─── Google Gemini ───────────────────────────────────────────
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# --- LLM API
LLM_API_URL = os.getenv("LLM_API_URL","")
LLM_API_KEY = os.getenv("LLM_API_KEY","")
LLM_MODEL   = os.getenv("LLM_MODEL", "Qwen3.5-0.5B")

# ─── Bot settings ────────────────────────────────────────────
MAX_MESSAGES      = int(os.getenv("MAX_MESSAGES", "200"))
LANGUAGE          = os.getenv("LANGUAGE", "vi")

# ─── Chat mode ───────────────────────────────────────────────
# Số lượt hội thoại giữ trong memory (mỗi lượt = 1 câu hỏi + 1 câu trả lời)
CHAT_MAX_HISTORY  = int(os.getenv("CHAT_MAX_HISTORY", "20"))

# ─── Bot username (để detect mention) ───────────────────────
# Lấy từ @BotFather — KHÔNG có dấu @
# Ví dụ: nếu bot là @MySummaryBot thì điền: MySummaryBot
BOT_USERNAME      = os.getenv("BOT_USERNAME", "")

# Số tin nhắn lấy khi được mention
MENTION_CONTEXT   = int(os.getenv("MENTION_CONTEXT", "20"))

# ─── Owner username (để detect khi bị tag) ──────────────────
# Username Telegram CUA BAN (không có @)
# Ví dụ: nếu bạn là @johnsmith thì điền: johnsmith
OWNER_USERNAME    = os.getenv("OWNER_USERNAME", "")

# ─── Micro-Journal Settings ──────────────────────────────────
JOURNAL_DB_PATH   = os.getenv("JOURNAL_DB_PATH", "./data/journal.db")
JOURNAL_TZ        = os.getenv("JOURNAL_TZ", "Asia/Ho_Chi_Minh")

# ─── Jira & GitLab Settings ──────────────────────────────────
JIRA_BASE_URL     = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_PAT          = os.getenv("JIRA_PAT", "")
JIRA_VERIFY_SSL   = os.getenv("JIRA_VERIFY_SSL", "true").lower() == "true"

GITLAB_BASE_URL   = os.getenv("GITLAB_BASE_URL", "https://scm.devops.vnpt.vn").rstrip("/")
GITLAB_PAT        = os.getenv("GITLAB_PAT", "")
GITLAB_VERIFY_SSL = os.getenv("GITLAB_VERIFY_SSL", "true").lower() == "true"

# ─── YouTube Settings ─────────────────────────────────────────
YOUTUBE_PROXY        = os.getenv("YOUTUBE_PROXY", "")
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE", "data/youtube_cookies.txt")



