import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram Bot Token ───────────────────────────────────────
# Lấy từ @BotFather → /newbot
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
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ─── OpenCode.ai Integration ──────────────────────────────────
OPENCODE_LOCAL_URL   = os.getenv("OPENCODE_LOCAL_URL", "http://localhost:4096")
USE_LOCAL_OPENCODE   = os.getenv("USE_LOCAL_OPENCODE", "false").lower() == "true"
