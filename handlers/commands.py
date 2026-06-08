"""
handlers/commands.py
Xử lý các lệnh cơ bản (/start, /help, /chat...) và điều hướng menu.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

import config
from services.markdown import escape, bold, italic, code, build, ai_to_mdv2
from services.telegram_utils import send_message_safe, edit_message_safe, typing_action
import services.fetcher as fetcher
import services.summarizer as summarizer
import services.jira_api as jira_api
import services.gitlab_api as gitlab_api
from services.journal_db import search_srs_knowledge, delete_srs_file, list_srs_files
from services.brain_service import process_srs_file

logger = logging.getLogger(__name__)

# --- Cấu hình hiển thị
MODE = "HTML"

# Session chat AI
_chat_sessions = {}  # {user_id: list_of_messages}
_chat_mode_users = set()  # Những user đang trong chế độ chat liên tục
CHAT_MAX_HISTORY = config.CHAT_MAX_HISTORY


def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized access: {user_id}")
            return
        return await fn(update, context)
    return wrapper


def _chat_id(update: Update) -> int:
    return update.effective_chat.id


async def _send(update: Update, text: str):
    return await send_message_safe(update.get_bot(), _chat_id(update), text, parse_mode=MODE)


async def _edit(msg, text: str):
    await edit_message_safe(msg.get_bot(), msg.chat_id, msg.message_id, text, parse_mode=MODE)


async def _send_report_safe(update: Update, ctx: ContextTypes.DEFAULT_TYPE, msg, report: str, file_prefix: str, caption: str):
    """
    Gửi báo cáo an toàn. 
    1. Tự động đăng tải lên Telegraph để người dùng mở bằng Webview (Instant View) cực kỳ mượt mà.
    2. Nếu báo cáo <= 4000 ký tự: Edit tin nhắn kèm nút Webview.
    3. Nếu báo cáo > 4000 ký tự: Gửi file Markdown đính kèm có nút Webview, và xóa tin nhắn loading.
    """
    from services.telegraph_api import publish_to_telegraph
    
    # Đăng tải lên Telegraph để tạo link Webview Instant View
    telegraph_url = publish_to_telegraph(caption, report)
    
    reply_markup = None
    if telegraph_url:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Xem Webview (Instant View)", url=telegraph_url)]
        ])

    if len(report) <= 4000:
        try:
            await edit_message_safe(
                msg.get_bot(), 
                msg.chat_id, 
                msg.message_id, 
                ai_to_mdv2(report), 
                parse_mode=MODE,
                reply_markup=reply_markup
            )
        except Exception as edit_err:
            logger.error(f"Error editing message with reply_markup: {edit_err}")
            await _edit(msg, ai_to_mdv2(report))
        return
        
    await _edit(msg, f"📝 {escape(caption)} khá chi tiết và dài. Đang ghi file đặc tả và gửi đính kèm...")
    
    import os
    import time
    os.makedirs("scratch", exist_ok=True)
    file_name = f"{file_prefix}_{int(time.time())}.md"
    file_path = f"scratch/{file_name}"
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report)
            
        if os.path.exists(file_path):
            with open(file_path, "rb") as doc_file:
                await ctx.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=doc_file,
                    filename=file_name,
                    caption=caption,
                    reply_markup=reply_markup
                )
            os.remove(file_path)
        await msg.delete()
    except Exception as e:
        logger.error(f"Error sending report as document: {e}", exc_info=True)
        try:
            await edit_message_safe(
                msg.get_bot(), 
                msg.chat_id, 
                msg.message_id, 
                ai_to_mdv2(report[:3800] + "\n\n...(đã cắt bớt do quá dài)..."), 
                parse_mode=MODE,
                reply_markup=reply_markup
            )
        except Exception:
            await _edit(msg, ai_to_mdv2(report[:3900] + "\n\n...(đã cắt bớt do quá dài)..."))


def _parse_args(text: str) -> tuple[str, str, int]:
    """Parse lệnh /cmd group | question N"""
    parts = text.split(None, 1)
    if len(parts) < 2:
        return "", "", 100
    
    content = parts[1].strip()
    # Tách question | N hoặc group | question
    if "|" in content:
        sub_parts = content.split("|", 1)
        group = sub_parts[0].strip()
        rest = sub_parts[1].strip()
    else:
        group = content
        rest = ""

    # Thử lấy N ở cuối
    n = 100
    rest_parts = rest.rsplit(None, 1)
    if len(rest_parts) > 1 and rest_parts[1].isdigit():
        n = int(rest_parts[1])
        question = rest_parts[0].strip()
    elif rest.isdigit():
        n = int(rest)
        question = ""
    else:
        question = rest
    
    return group, question, n


_telethon = None
def set_telethon(t):
    global _telethon
    _telethon = t


async def _resolve(query: str):
    """Tìm chat entity từ query (username hoặc tên)."""
    if not query:
        return None, "", escape("Vui lòng nhập tên nhóm hoặc username.")
    try:
        entity, matched_name = await fetcher.resolve_chat(_telethon, query)
        if not entity:
            return None, "", escape(f"Không tìm thấy chat '{query}'.")
        return entity, matched_name, None
    except Exception as e:
        return None, "", escape(f"Lỗi khi tìm chat '{query}': {e}")


def _md(text: str) -> str:
    return ai_to_mdv2(text)


# ─── /help ───────────────────────────────────────────────────

@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu chính phân loại các tính năng."""
    text = build(
        f"🌟 {bold('Hệ thống Trợ lý AI Con Bot Ngu Ngốk')}",
        "",
        escape("Chào mừng bạn! Hãy chọn một nhóm tính năng bên dưới để xem chi tiết cách dùng:"),
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Phân tích Chat", callback_data="help:group_chat"),
            InlineKeyboardButton("📓 Nhật ký & Học tập", callback_data="help:group_journal")
        ],
        [
            InlineKeyboardButton("🧠 Bộ não (RAG)", callback_data="help:group_brain"),
            InlineKeyboardButton("🤖 AI Chat", callback_data="help:group_ai")
        ],
        [
            InlineKeyboardButton("🚀 Build & Hệ thống", callback_data="help:group_system")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await edit_message_safe(
            context.bot, 
            update.effective_chat.id, 
            update.callback_query.message.message_id, 
            text, 
            reply_markup=reply_markup, 
            parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_help_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Điều hướng callback query từ menu help."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 1. Xử lý chuyển nhóm Help
    if data.startswith("help:group_"):
        group = data.split("_")[1]
        await show_help_group(update, ctx, group)
        return

    elif data == "help:main":
        await cmd_help(update, ctx)
        return

    # 2. Xử lý các command trực tiếp
    cmd_map = {
        "cmd:chats": cmd_chats,
        "cmd:chat": cmd_chat,
        "cmd:debate": cmd_debate,
        "cmd:spy": cmd_spy,
    }
    
    from handlers.journal import (
        cmd_journal, cmd_vocab, cmd_streak, cmd_history, cmd_summary, cmd_check_jobs, cmd_quiz
    )
    from handlers.brain import ask_brain_start
    from handlers.delegate_handler import cmd_delegate, cmd_delegates
    from handlers.docker_handler import cmd_docker
    
    cmd_map.update({
        "cmd:journal": cmd_journal,
        "cmd:vocab": cmd_vocab,
        "cmd:streak": cmd_streak,
        "cmd:history": cmd_history,
        "cmd:summary": cmd_summary,
        "cmd:checkjobs": cmd_check_jobs,
        "cmd:quiz": cmd_quiz,
        "cmd:ask": ask_brain_start,
        "cmd:sum": cmd_sum,
        "cmd:vibe": cmd_vibe,
        "cmd:delegate": cmd_delegate,
        "cmd:delegates": cmd_delegates,
        "cmd:docker": cmd_docker,
    })
    
    from handlers.code_search import cmd_search_code
    cmd_map.update({
        "cmd:search_code": cmd_search_code
    })
    
    handler = cmd_map.get(data)
    if handler:
        await handler(update, ctx)


async def show_help_group(update: Update, context: ContextTypes.DEFAULT_TYPE, group: str):
    """Hiển thị nội dung chi tiết của từng nhóm help."""
    groups = {
        "chat": {
            "title": "📊 PHÂN TÍCH CHAT",
            "commands": [
                "/sum [N] — Tóm tắt N tin nhắn gần nhất",
                "/tldr — Tóm tắt cực ngắn hội thoại",
                "/vibe — Phân tích không khí",
                "/who — Xem ai nói nhiều nhất",
                "/search [keyword] — Tìm và tóm tắt",
                "/sentiment — Phân tích cảm xúc",
                "/draft [ý định] — Soạn tin nhắn mẫu",
                "/reply [tên] — Gợi ý cách trả lời",
                "/debate A vs B [N] — AI tranh luận 2 phe",
                "/spy [nhóm] [2h] — Xem bỏ lỡ gì"
            ],
            "buttons": [
                [InlineKeyboardButton("📊 Tóm tắt nhanh", callback_data="cmd:sum"), InlineKeyboardButton("🌡️ Vibe Check", callback_data="cmd:vibe")],
                [InlineKeyboardButton("🥊 AI Debate", callback_data="cmd:debate"), InlineKeyboardButton("🕵️ Spy Mode", callback_data="cmd:spy")]
            ]
        },
        "journal": {
            "title": "📓 NHẬT KÝ & HỌC TẬP",
            "commands": [
                "/journal [text] — Ghi nhật ký nhanh",
                "/vocab [từ] — Lưu từ vựng mới",
                "/quiz — Làm trắc nghiệm từ vựng",
                "/streak — Xem chuỗi ngày liên tiếp",
                "/streak_summary — Tóm tắt chuỗi streak",
                "/restore_streak — Phục hồi chuỗi ngày bị đứt",
                "/history — Xem nhật ký cũ",
                "/summary — Tổng kết tuần"
            ],
            "buttons": [
                [InlineKeyboardButton("📓 Ghi nhật ký", callback_data="cmd:journal"), InlineKeyboardButton("🧠 Quiz", callback_data="cmd:quiz")],
                [InlineKeyboardButton("🔥 Chuỗi Streak", callback_data="cmd:streak")]
            ]
        },
        "brain": {
            "title": "🧠 BỘ NÃO (RAG) & NGHIÊN CỨU",
            "commands": [
                "/save [nội dung] — Lưu kiến thức",
                "Gửi file PDF/Ảnh — Cho bot học tài liệu",
                "/ask — Trò chuyện & truy vấn bộ não (nhiều lượt)",
                "/sumlink <URL> — Tóm tắt & lưu bài viết/YouTube",
                "/delegate <chủ đề> — Ủy thác nghiên cứu chạy ngầm",
                "/delegates — Xem danh sách các task nghiên cứu",
                "/search_code — Tra cứu API & Kiểm tra tham số từ SCM/Codebase"
            ],
            "buttons": [
                [InlineKeyboardButton("🧠 Hỏi bộ não", callback_data="cmd:ask"), InlineKeyboardButton("📋 DS Nghiên cứu", callback_data="cmd:delegates")],
                [InlineKeyboardButton("🔍 Tìm kiếm Codebase/API", callback_data="cmd:search_code")]
            ]
        },
        "ai": {
            "title": "🤖 AI CHAT",
            "commands": [
                "/chat [câu hỏi] — Chat nhanh",
                "/chat — Vào chế độ hội thoại liên tục",
                "/endchat — Thoát chế độ chat"
            ],
            "buttons": [
                [InlineKeyboardButton("🤖 Bật Chat Mode", callback_data="cmd:chat")]
            ]
        },
        "system": {
            "title": "⚙️ HỆ THỐNG",
            "commands": [
                "/checkjobs — Kiểm tra lịch trình nhắc nhở",
                "/settime HH:mm — Đổi giờ nhắc nhở nhật trình",
                "/docker — Bảng điều khiển Docker Container"
            ],
            "buttons": [
                [InlineKeyboardButton("⚙️ Check Jobs", callback_data="cmd:checkjobs"), InlineKeyboardButton("🐳 Docker Panel", callback_data="cmd:docker")]
            ]
        }
    }
    
    g = groups.get(group)
    if not g: return
    
    text = build(
        f"📍 {bold(g['title'])}",
        "",
        *[escape(cmd) for cmd in g['commands']],
        "",
        italic("Bấm nút dưới để thực hiện nhanh:")
    )
    
    keyboard = g['buttons'] + [[InlineKeyboardButton("⬅️ Quay lại", callback_data="help:main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await edit_message_safe(
        context.bot, 
        update.effective_chat.id, 
        update.callback_query.message.message_id, 
        text, 
        reply_markup=reply_markup, 
        parse_mode="HTML"
    )

# ─── Các Command Phân Tích Chat ─────────────────────────────

@require_auth
@typing_action
async def cmd_chats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _send(update, escape("Đang lấy danh sách chat..."))
    dialogs = await fetcher.list_dialogs(_telethon, limit=50)

    if not dialogs:
        await _send(update, escape("Không tìm thấy chat nào."))
        return

    lines = [bold("Danh sách chat của bạn:"), ""]
    for d in dialogs:
        name = escape(d["name"])
        uname = f" \\({escape('@' + d['username'])}\\)" if d["username"] else ""
        unread = f" \\[{escape(str(d['unread']))} chưa đọc\\]" if d["unread"] else ""
        lines.append(f"{d['kind']} {name}{uname}{unread}")

    # Chia chunk nếu quá 4000 ký tự
    chunks, current = [], build(*lines[:2])
    for line in lines[2:]:
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = line
        else:
            current = build(current, line)
    if current:
        chunks.append(current)

    for chunk in chunks:
        await _send(update, chunk)


@require_auth
@typing_action
async def cmd_sum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, _, n = _parse_args(update.effective_message.text if not update.callback_query else "/sum 100")
    if update.callback_query and not chat_q:
        await _send(update, escape("Vui lòng nhập tên nhóm sau lệnh /sum. Ví dụ: /sum TênNhóm 50"))
        return

    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/sum <group> [số tin]")))
        return

    msg = await _send(update, escape(f"Đang lấy {n} tin từ {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, n)
    summary = summarizer.summarize(result)

    await _edit(msg, build(
        f"{bold('Tóm tắt')} — {escape(result.chat_name)} {escape(f'({result.total_fetched} tin)')}",
        "",
        _md(summary)
    ))


@require_auth
@typing_action
async def cmd_tldr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, _, n = _parse_args(update.effective_message.text)
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/tldr <group> [số tin]")))
        return
    msg = await _send(update, escape(f"Đang tóm tắt {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, n)
    summary = summarizer.summarize(result, mode="short")
    await _edit(msg, build(
        f"{bold('TL;DR')} — {escape(result.chat_name)}",
        "",
        _md(summary)
    ))


@require_auth
@typing_action
async def cmd_vibe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, _, n = _parse_args(update.effective_message.text if not update.callback_query else "/vibe 100")
    if update.callback_query and not chat_q:
        await _send(update, escape("Vui lòng nhập tên nhóm sau lệnh /vibe."))
        return
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/vibe <group> [số tin]")))
        return
    msg = await _send(update, escape(f"Đang đọc không khí {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, n)
    analysis = summarizer.analyze_vibe(result)
    await _edit(msg, build(
        f"{bold('Vibe Check')} — {escape(result.chat_name)}",
        "",
        _md(analysis)
    ))


@require_auth
@typing_action
async def cmd_who(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, _, n = _parse_args(update.effective_message.text)
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/who <group> [số tin]")))
        return
    msg = await _send(update, escape(f"Đang đếm trong {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, n)
    analysis = summarizer.who_dominated(result)
    await _edit(msg, build(
        f"{bold('Leaderboard')} — {escape(result.chat_name)}",
        "",
        _md(analysis)
    ))


@require_auth
@typing_action
async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, keyword, _ = _parse_args(update.effective_message.text)
    if not keyword:
        await _send(update, build(bold("Cú pháp:"), code("/search <group> | <từ khóa>")))
        return
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/search <group> | <từ khóa>")))
        return
    msg = await _send(update, escape(f"Đang tìm {keyword}..."))
    result = await fetcher.search_messages(_telethon, entity, keyword)
    summary = summarizer.summarize_search(keyword, result)
    await _edit(msg, build(
        f"{bold('Search:')} {code(keyword)} — {escape(result.chat_name)}",
        "",
        _md(summary)
    ))


@require_auth
@typing_action
async def cmd_sentiment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, _, n = _parse_args(update.effective_message.text)
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/sentiment <group> [số tin]")))
        return
    msg = await _send(update, escape(f"Đang phân tích cảm xúc {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, max(n, 30))
    analysis = summarizer.analyze_sentiment(result)
    await _edit(msg, build(
        f"{bold('Cảm xúc')} — {escape(result.chat_name)}",
        "",
        _md(analysis)
    ))


@require_auth
@typing_action
async def cmd_draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, intent, _ = _parse_args(update.effective_message.text)
    if not intent:
        await _send(update, build(bold("Cú pháp:"), code("/draft <group> | <ý định>")))
        return
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/draft <group> | <ý định>")))
        return
    msg = await _send(update, escape(f"Đang soạn tin nhắn cho {name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, 30)
    draft = summarizer.draft_message(result, intent)
    await _edit(msg, build(f"{bold('Draft')} — {escape(result.chat_name)}", "", _md(draft)))


@require_auth
@typing_action
async def cmd_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_q, target_name, _ = _parse_args(update.effective_message.text)
    if not target_name:
        await _send(update, build(bold("Cú pháp:"), code("/reply <group> | <tên người>")))
        return
    entity, name, err = await _resolve(chat_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/reply <group> | <tên người>")))
        return
    msg = await _send(update, escape(f"Đang phân tích {target_name}..."))
    result = await fetcher.fetch_last_n(_telethon, entity, 50)
    target_lower = target_name.lower().strip()
    target_messages = [m for m in result.messages if target_lower in m.user.lower()]
    if not target_messages:
        await _edit(msg, f"Không tìm thấy tin nhắn nào của '{target_name}'.")
        return
    suggestion = summarizer.suggest_reply(result, target_name, target_messages)
    await _edit(msg, build(f"{bold('Gợi ý reply')} — {escape(target_name)}", "", _md(suggestion)))

# ─── /debate ────────────────────────────────────────────────

@require_auth
async def cmd_debate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tổ chức cuộc tranh luận AI 2 phe về bất kỳ chủ đề nào."""
    text = update.effective_message.text if not update.callback_query else ""
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(
            bold("Cú pháp:"),
            code("/debate <chủ đề> [số vòng]"),
            "",
            italic("Ví dụ:"),
            escape("/debate React vs Vue"),
            escape("/debate WFH vs Office 3"),
            escape("/debate Python vs Go 2"),
        ))
        return

    raw = parts[1].strip()

    # Parse số vòng ở cuối (nếu có)
    rounds = 2
    raw_parts = raw.rsplit(None, 1)
    if len(raw_parts) > 1 and raw_parts[1].isdigit():
        rounds = max(1, min(int(raw_parts[1]), 4))  # giới hạn 1-4 vòng
        raw = raw_parts[0].strip()

    # Tách 2 phe qua "vs" (không phân biệt hoa thường)
    import re
    vs_match = re.split(r'\s+vs\.?\s+', raw, maxsplit=1, flags=re.IGNORECASE)
    if len(vs_match) == 2:
        side_a, side_b = vs_match[0].strip(), vs_match[1].strip()
        topic = f"{side_a} vs {side_b}"
    else:
        # Không có "vs" — dùng Ủng hộ/Phản đối
        topic = raw
        side_a, side_b = "Ủng hộ", "Phản đối"

    total_turns = rounds * 2  # Mỗi vòng = 2 lượt (A + B)
    header_text = build(
        f"⚔️ {bold(f'CUỘC TRANH LUẬN: {topic}')}",
        f"🔵 Phe {bold(side_a)} vs 🔴 Phe {bold(side_b)}",
        escape(f"Số vòng: {rounds} | Đang chuẩn bị..."),
    )
    msg = await _send(update, header_text)

    # Thu thập tất cả lập luận để phán xử
    all_arguments = []
    last_text = ""
    current_side = side_a
    opp_side = side_b

    for turn in range(total_turns):
        round_num = turn // 2 + 1
        is_first = (turn == 0)

        label = f"🔵 Phe {bold(side_a)}" if current_side == side_a else f"🔴 Phe {bold(side_b)}"
        status = escape(f"Vòng {round_num}/{rounds} — {current_side} đang lập luận...")
        try:
            await msg.edit_text(build(header_text, "", status), parse_mode="HTML")
        except Exception:
            pass

        # Gọi AI
        if is_first:
            arg_text = summarizer.debate_opening(topic, current_side, opp_side)
        else:
            arg_text = summarizer.debate_counter(topic, current_side, opp_side, last_text)

        all_arguments.append({"side": current_side, "text": arg_text})
        last_text = arg_text

        # Gửi lượt tranh luận này
        await _send(update, build(
            f"{label} — {escape(f'Vòng {round_num}')}",
            "",
            _md(arg_text),
        ))

        # Đổi phe
        current_side, opp_side = opp_side, current_side

    # Phán xử
    try:
        await msg.edit_text(build(header_text, "", escape("⚖️ Đang phán xử kết quả...")), parse_mode="HTML")
    except Exception:
        pass

    verdict = summarizer.debate_verdict(topic, side_a, side_b, all_arguments)
    await _send(update, build(
        f"⚖️ {bold('PHÁN XỬ CUỐI CÙNG')}",
        "",
        _md(verdict),
    ))

    # Xoá tin nhắn loading
    try:
        await msg.delete()
    except Exception:
        pass


# ─── /spy ─────────────────────────────────────────────────────

def _parse_time_ago(arg: str):
    """Parse chuỗi thời gian sang datetime: '2h', '30m', '1d', 'hôm qua'."""
    from datetime import datetime, timedelta, timezone
    import pytz
    now = datetime.now(tz=timezone.utc)

    arg = arg.strip().lower()

    if arg in ("hôm qua", "yesterday", "hqua"):
        # Đầu ngày hôm qua theo giờ VN
        try:
            vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
            today_vn = datetime.now(vn_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_vn = today_vn - timedelta(days=1)
            return yesterday_vn.astimezone(timezone.utc)
        except Exception:
            return now - timedelta(days=1)

    if arg in ("hôm nay", "today"):
        try:
            vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
            today_vn = datetime.now(vn_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            return today_vn.astimezone(timezone.utc)
        except Exception:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

    import re
    m = re.match(r'^(\d+)([mhd])$', arg)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        if unit == 'm':
            return now - timedelta(minutes=val)
        elif unit == 'h':
            return now - timedelta(hours=val)
        elif unit == 'd':
            return now - timedelta(days=val)

    # Default: 1 giờ
    return now - timedelta(hours=1)


def _time_label(arg: str) -> str:
    """Tạo nhãn mô tả khoảng thời gian."""
    arg = arg.strip().lower()
    if arg in ("hôm qua", "yesterday", "hqua"):
        return "từ hôm qua"
    if arg in ("hôm nay", "today"):
        return "từ đầu ngày hôm nay"
    import re
    m = re.match(r'^(\d+)([mhd])$', arg)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        labels = {'m': 'phút', 'h': 'giờ', 'd': 'ngày'}
        return f"{val} {labels[unit]} qua"
    return "1 giờ qua"


@require_auth
@typing_action
async def cmd_spy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Tóm tắt nhóm theo góc nhìn 'người vừa quay lại'."""
    text = update.effective_message.text if not update.callback_query else ""
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(
            bold("Cú pháp:"),
            code("/spy <nhóm> [thời gian]"),
            "",
            italic("Ví dụ:"),
            escape("/spy DevTeam 2h"),
            escape("/spy DevTeam 30m"),
            escape("/spy DevTeam hôm qua"),
            escape("/spy DevTeam  (mặc định 1 giờ)"),
        ))
        return

    raw = parts[1].strip()

    # Tách group và time_arg (time_arg ở cuối nếu khớp pattern)
    import re
    time_arg = "1h"  # default
    group_q = raw

    # Kiểm tra phần cuối có phải time arg không
    time_patterns = [r'\d+[mhd]$', r'hôm qua$', r'yesterday$', r'hôm nay$', r'today$', r'hqua$']
    for pat in time_patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            time_arg = m.group(0).strip()
            group_q = raw[:m.start()].strip()
            break

    if not group_q:
        group_q = time_arg
        time_arg = "1h"

    entity, name, err = await _resolve(group_q)
    if err:
        await _send(update, build(err, "", bold("Cú pháp:"), code("/spy <nhóm> [thời gian]")))
        return

    label = _time_label(time_arg)
    since_dt = _parse_time_ago(time_arg)

    msg = await _send(update, escape(f"🕵️ Đang điều tra {name} ({label})..."))

    result = await fetcher.fetch_since(_telethon, entity, since_dt)

    if not result.messages:
        await _edit(msg, build(
            f"🕵️ {bold('SPY REPORT')} — {escape(name)}",
            f"⏱ {escape(label)}",
            "",
            escape("Nhóm im lặng hoàn toàn trong khoảng thời gian này. 😴"),
        ))
        return

    import config as _config
    owner_username = getattr(_config, 'OWNER_USERNAME', '')
    spy_text = summarizer.spy_summary(result, owner_username=owner_username, time_label=label)

    await _edit(msg, build(
        f"🕵️ {bold('SPY REPORT')} — {escape(name)}",
        f"⏱ {escape(label)} {escape('|')} {escape(str(result.total_fetched))} {escape('tin nhắn')}",
        "",
        _md(spy_text),
    ))


# ─── /chat ───────────────────────────────────────────────────

def _append_to_history(user_id: int, role: str, content: str):
    if user_id not in _chat_sessions: _chat_sessions[user_id] = []
    _chat_sessions[user_id].append({"role": role, "content": content})
    if len(_chat_sessions[user_id]) > CHAT_MAX_HISTORY * 2:
        _chat_sessions[user_id] = _chat_sessions[user_id][-(CHAT_MAX_HISTORY * 2):]

async def _do_chat(update: Update, question: str):
    user_id = update.effective_user.id
    if user_id not in _chat_sessions: _chat_sessions[user_id] = []
    history = _chat_sessions[user_id]
    await update.effective_message.reply_chat_action(ChatAction.TYPING)
    msg = await _send(update, escape("Đang suy nghĩ..."))
    try:
        answer = summarizer.chat_with_history(history, question)
        _append_to_history(user_id, "user", question)
        _append_to_history(user_id, "assistant", answer)
        turn = len(_chat_sessions[user_id]) // 2
        footer = f"\n\n_{escape(f'Lượt {turn}/{CHAT_MAX_HISTORY} • /endchat để kết thúc')}_" if user_id in _chat_mode_users else ""
        await send_message_safe(msg.get_bot(), update.effective_chat.id, _md(answer) + footer, parse_mode=MODE)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Lỗi khi gọi AI: {e}")

@require_auth
async def cmd_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: text = ""
    else: text = update.effective_message.text if update.effective_message else ""
    parts = text.strip().split(None, 1)
    question = parts[1].strip() if len(parts) > 1 else ""
    user_id = update.effective_user.id
    if not question:
        _chat_mode_users.add(user_id)
        await _send(update, build(bold("🤖 Chat AI"), "Gửi tin nhắn bất kỳ để trò chuyện. /endchat để thoát."))
        return
    await _do_chat(update, question)

@require_auth
async def cmd_endchat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in _chat_sessions: _chat_sessions[user_id].clear()
    _chat_mode_users.discard(user_id)
    await _send(update, bold("✅ Đã kết thúc hội thoại."))

@require_auth
async def handle_chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_message.text: return
    user_id = update.effective_user.id
    if user_id in _chat_mode_users:
        await _do_chat(update, update.effective_message.text.strip())

# ─── Jira & GitLab Review ─────────────────────────────────────

@require_auth
@typing_action
async def cmd_jira(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(bold("Cú pháp:"), code("/jira <mã_task>"), "", italic("Ví dụ: /jira G038-18744")))
        return

    issue_key = parts[1].strip()
    msg = await _send(update, escape(f"Đang tra cứu Jira task {issue_key}..."))
    
    result = await jira_api.get_issue(issue_key)
    await _edit(msg, result)


@require_auth
@typing_action
async def cmd_jira_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ""
    if not update.callback_query and update.effective_message:
        text = update.effective_message.text or ""
    
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(bold("Cú pháp:"), code("/jira_risk <mã_task>"), "", italic("Ví dụ: /jira_risk G038-18744")))
        return

    issue_key = parts[1].strip()
    msg = await _send(update, escape(f"Đang AI phân tích rủi ro trễ hạn cho task {issue_key}..."))
    
    # Lấy thông tin đầy đủ kèm comments/changelog
    issue_data = await jira_api.get_issue_full(issue_key)
    if not issue_data:
        await _edit(msg, f"❌ Không tìm thấy task {escape(issue_key)} trên Jira hoặc có lỗi kết nối.")
        return
        
    analysis = summarizer.analyze_jira_issue_risk(issue_data)
    report = analysis.get("markdown_report")
    if not report:
        report = build(f"⚠️ {bold('Không thể lập báo cáo phân tích rủi ro cho task')} {code(issue_key)}")
        
    await _edit(msg, report)


@require_auth
async def cmd_jira_srs_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bắt đầu phiên upload file SRS đặc tả dự án cho Jira Bot."""
    ctx.user_data["waiting_jira_srs_upload"] = True
    ctx.user_data["srs_uploaded_files_count"] = 0
    
    keyboard = [[InlineKeyboardButton("✅ Hoàn thành tải lên", callback_data="jira_srs:done")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message_safe(
        ctx.bot,
        _chat_id(update),
        build(
            f"📥 {bold('UPLOADING PROJECT SRS DOCUMENTS')}",
            "",
            escape("Vui lòng tải lên và gửi các file đặc tả hệ thống SRS (định dạng PDF, DOCX, TXT, MD hoặc ZIP chứa tài liệu)."),
            italic("Bạn có thể gửi nhiều file liên tục. Sau khi gửi xong toàn bộ, hãy bấm nút dưới đây để kết thúc."),
        ),
        reply_markup=reply_markup,
        parse_mode=MODE
    )


@require_auth
async def handle_jira_srs_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý các sự kiện callback trong phiên upload tài liệu đặc tả SRS."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    import os
    
    if data == "jira_srs:done":
        total = ctx.user_data.get("srs_uploaded_files_count", 0)
        ctx.user_data["waiting_jira_srs_upload"] = False
        ctx.user_data["srs_uploaded_files_count"] = 0
        ctx.user_data.pop("srs_pending_confirm", None)
        
        await query.message.reply_text(build(
            f"✅ {bold('HOÀN THÀNH TẢI LÊN ĐẶC TẢ SRS')}",
            f"Đã đóng phiên upload. Tổng cộng hệ thống đã lưu và lập chỉ mục {bold(str(total))} đoạn nghiệp vụ đặc tả dự án.",
            "",
            f"Sẵn sàng hoạt động với lệnh {code('/jira_analyze <mã_task>')}"
        ), parse_mode="HTML")
        
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    if data == "jira_srs:list_refresh" or data == "jira_srs:list_back":
        await cmd_jira_srs_list(update, ctx)
        return

    # Định dạng: jira_srs:overwrite:<unique_id> hoặc jira_srs:skip:<unique_id>
    parts = data.split(":")
    if len(parts) < 3:
        return
        
    action = parts[1]
    
    if action == "del_query":
        idx = int(parts[2])
        active_list = ctx.user_data.get("srs_active_list")
        if not active_list or idx >= len(active_list):
            await query.edit_message_text(
                "❌ Phiên làm việc đã hết hạn hoặc không tìm thấy thông tin file. Vui lòng chạy lại lệnh /jira_srs_list.",
                parse_mode="HTML"
            )
            return
            
        file_info = active_list[idx]
        file_name = file_info["file_name"]
        chunk_count = file_info["chunk_count"]
        
        keyboard = [
            [
                InlineKeyboardButton("🔥 Đồng ý xóa", callback_data=f"jira_srs:del_confirm:{idx}"),
                InlineKeyboardButton("❌ Hủy bỏ", callback_data="jira_srs:list_back")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            build(
                "⚠️ " + bold("XÁC NHẬN XÓA TÀI LIỆU SRS"),
                "─" * 32,
                f"Bạn có chắc chắn muốn xóa tài liệu đặc tả {code(file_name)}?",
                "",
                f"Hành động này sẽ xóa sạch {bold(str(chunk_count))} mẩu nghiệp vụ tương ứng và " + bold("không thể hoàn tác") + "."
            ),
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return

    elif action == "del_confirm":
        idx = int(parts[2])
        active_list = ctx.user_data.get("srs_active_list")
        if not active_list or idx >= len(active_list):
            await query.edit_message_text(
                "❌ Phiên làm việc đã hết hạn. Vui lòng chạy lại lệnh /jira_srs_list.",
                parse_mode="HTML"
            )
            return
            
        file_info = active_list[idx]
        file_name = file_info["file_name"]
        
        try:
            deleted_count = await delete_srs_file(file_name)
            
            # Hiển thị thông báo popup Toast trên giao diện Telegram
            await query.answer(f"✅ Đã xóa thành công tài liệu: {file_name}!", show_alert=True)
            
            # Tải lại danh sách mới tự động
            await cmd_jira_srs_list(update, ctx)
        except Exception as e:
            logger.error(f"Lỗi khi xóa file đặc tả: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Có lỗi xảy ra khi xóa tài liệu: {e}")
        return

    unique_id = parts[2]
    
    pending = ctx.user_data.get("srs_pending_confirm")
    if not pending or pending.get("file_unique_id") != unique_id:
        await query.edit_message_text("❌ Lỗi: Phiên xác nhận file đã hết hạn hoặc không hợp lệ.")
        return
        
    file_name = pending["file_name"]
    temp_file_path = pending["temp_file_path"]
    
    if action == "overwrite":
        await query.edit_message_text(f"⏳ Đang ghi đè và lập chỉ mục lại tệp {code(file_name)}...", parse_mode="HTML")
        try:
            # 1. Xóa dữ liệu cũ
            deleted_rows = await delete_srs_file(file_name)
            logger.info(f"Đã xóa {deleted_rows} đoạn đặc tả cũ của file {file_name}")
            
            # 2. Xử lý tệp mới
            count = await process_srs_file(update.effective_user.id, temp_file_path, file_name)
            
            # Xóa file tạm
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                
            # Cập nhật tổng số chunks
            current_total = ctx.user_data.get("srs_uploaded_files_count", 0) + count
            ctx.user_data["srs_uploaded_files_count"] = current_total
            
            keyboard = [[InlineKeyboardButton("✅ Hoàn thành tải lên", callback_data="jira_srs:done")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                build(
                    f"🔄 {bold('Đã ghi đè tài liệu đặc tả thành công!')}",
                    f"• Tên file: {code(file_name)}",
                    f"• Số mẩu nghiệp vụ mới đã lưu: {bold(str(count))}",
                    f"• Tổng số mẩu trong phiên này: {bold(str(current_total))}",
                    "",
                    italic("Tiếp tục gửi thêm các file đặc tả khác hoặc click nút bấm dưới để hoàn tất.")
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Lỗi khi ghi đè file SRS: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Có lỗi xảy ra khi ghi đè file: {e}")
            
    elif action == "skip":
        # Hủy tệp tạm
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            
        current_total = ctx.user_data.get("srs_uploaded_files_count", 0)
        keyboard = [[InlineKeyboardButton("✅ Hoàn thành tải lên", callback_data="jira_srs:done")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            build(
                f"❌ {bold('Đã bỏ qua tệp tin trùng lặp:')} {code(file_name)}",
                "",
                f"• Tổng số mẩu đặc tả đã lưu hiện tại: {bold(str(current_total))}",
                "",
                italic("Tiếp tục gửi thêm các file đặc tả khác hoặc click nút bấm dưới để hoàn tất.")
            ),
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
    # Dọn dẹp context tạm
    ctx.user_data.pop("srs_pending_confirm", None)


@require_auth
async def cmd_jira_srs_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xem danh sách các tài liệu đặc tả SRS đã được nạp (Giao diện Premium tương tác)."""
    query = update.callback_query
    
    try:
        files = await list_srs_files()
        
        # Lưu danh sách file hoạt động vào user_data để xóa nhanh bằng nút bấm
        ctx.user_data["srs_active_list"] = files
        
        if not files:
            text = build(
                "📂 " + bold("CƠ SỞ DỮ LIỆU ĐẶC TẢ NGHIỆP VỤ (SRS)"),
                "─" * 32,
                "ℹ️ " + bold("Cơ sở dữ liệu đặc tả SRS hiện đang trống."),
                "",
                "AI chưa có nghiệp vụ dự án nào để phân tích.",
                "Bạn có thể gõ lệnh /jira_srs_upload hoặc click nút bên dưới để nạp tài liệu mới."
            )
            keyboard = [
                [InlineKeyboardButton("📥 Nạp SRS Mới", callback_data="jira_help:group_jira")],
                [InlineKeyboardButton("⬅️ Quay lại Menu Help", callback_data="jira_help:main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if query:
                await query.answer()
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
            else:
                await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
            return
            
        lines = [
            "📂 " + bold("CƠ SỞ DỮ LIỆU ĐẶC TẢ NGHIỆP VỤ (SRS)"),
            "─" * 32,
            f"Hiện tại hệ thống đã học và lập chỉ mục {bold(str(len(files)))} tài liệu đặc tả nghiệp vụ dự án.",
            "AI sẽ tự động đối chiếu các tài liệu này khi bạn chạy lệnh phân tích task.",
            ""
        ]
        
        for idx, f in enumerate(files, 1):
            created_dt = f["created_at"][:16].replace("T", " ")
            lines.append(
                f"{idx}️⃣  📄 {bold(escape(f['file_name']))}\n"
                f"    🧩 {italic('Số mẩu:')} {code(str(f['chunk_count']))}  |  📅 {italic('Nạp:')} {code(created_dt)}"
            )
            
        lines.append("")
        lines.append(italic("Để xóa nhanh tài liệu và các mảnh kiến thức nghiệp vụ tương ứng, vui lòng bấm nút tương ứng bên dưới:"))
        
        text = "\n".join(lines)
        
        # Build Inline Keyboard
        keyboard = []
        # Nhóm các nút xóa 3 cột
        row = []
        for idx in range(1, len(files) + 1):
            row.append(InlineKeyboardButton(f"🗑️ Xóa {idx}", callback_data=f"jira_srs:del_query:{idx-1}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
        keyboard.append([
            InlineKeyboardButton("⬅️ Menu Help", callback_data="jira_help:group_jira"),
            InlineKeyboardButton("🔄 Làm mới", callback_data="jira_srs:list_refresh")
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.answer()
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách SRS: {e}", exc_info=True)
        err_msg = f"❌ Không thể tải danh sách tài liệu đặc tả SRS: {e}"
        if query:
            await query.answer()
            await query.edit_message_text(err_msg)
        else:
            await update.effective_message.reply_text(err_msg)


@require_auth
async def cmd_jira_srs_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xóa một tài liệu đặc tả SRS khỏi database."""
    args = ctx.args
    
    if not args:
        await update.effective_message.reply_text(
            build(
                "❌ Vui lòng nhập tên file đặc tả cần xóa.",
                "Cú pháp: " + code("/jira_srs_delete <tên_file>")
            ),
            parse_mode="HTML"
        )
        return
        
    file_name = " ".join(args).strip()
    
    try:
        deleted_count = await delete_srs_file(file_name)
        if deleted_count > 0:
            await update.effective_message.reply_text(
                f"✅ Đã xóa thành công tài liệu {code(file_name)} và giải phóng {bold(str(deleted_count))} mẩu nghiệp vụ tương ứng khỏi cơ sở dữ liệu.",
                parse_mode="HTML"
            )
        else:
            await update.effective_message.reply_text(
                f"❌ Không tìm thấy tài liệu nào có tên khớp với {code(file_name)} trong cơ sở dữ liệu đặc tả.",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Lỗi khi xóa file SRS {file_name}: {e}", exc_info=True)
        await update.effective_message.reply_text(f"❌ Có lỗi xảy ra khi xóa tài liệu: {e}")


@require_auth
@typing_action
async def cmd_jira_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Phân tích một Jira Task dựa trên đặc tả SRS có sẵn,
    đánh giá tính khả thi nghiệp vụ và lập kế hoạch triển khai.
    """
    text = update.effective_message.text
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(
            bold("Cú pháp:"),
            code("/jira_analyze <mã_task>"),
            "",
            italic("Ví dụ: /jira_analyze PROJ-123")
        ))
        return

    issue_key = parts[1].strip()
    msg = await _send(update, escape(f"Đang AI phân tích task {issue_key} dựa trên đặc tả SRS..."))

    # 1. Lấy thông tin chi tiết Jira ticket
    issue_data = await jira_api.get_issue_full(issue_key)
    if not issue_data:
        await _edit(msg, f"❌ Không tìm thấy task {escape(issue_key)} trên Jira hoặc có lỗi kết nối.")
        return

    # 2. Tìm kiếm đặc tả SRS liên quan
    # Gom summary để search FTS5
    search_query = issue_data.get("summary", "")
    srs_results = await search_srs_knowledge(search_query, limit=8)

    if not srs_results:
        # Nếu search theo cả câu summary không ra kết quả, thử search theo các từ khóa
        import re
        words = re.findall(r'\b\w{3,}\b', search_query)
        if words:
            srs_results = await search_srs_knowledge(" OR ".join(words[:3]), limit=5)

    if not srs_results:
        # Cảnh báo người dùng cần upload SRS trước
        await _edit(msg, build(
            f"⚠️ {bold('Thiếu tài liệu đặc tả SRS liên quan')}",
            "",
            escape("Chưa tìm thấy đoạn đặc tả SRS nào phù hợp với nội dung task trong bộ nhớ."),
            f"Vui lòng sử dụng lệnh {code('/jira_srs_upload')} để tải lên file đặc tả dự án."
        ))
        return

    # 3. Gom context SRS
    context_parts = []
    for r in srs_results:
        src_clean = r['source'].replace("srs:", "") if r['source'] else "SRS Document"
        context_parts.append(f"--- [Đặc tả từ file: {src_clean}] ---\n{r['content']}")
    srs_context = "\n\n".join(context_parts)

    # 4. Gom comment thảo luận
    comments_list = []
    for c in issue_data.get("comments", []):
        comments_list.append(f"[{c['author']}]: {c['body']}")
    issue_data["comments_str"] = "\n".join(comments_list) if comments_list else "Không có bình luận nào"

    # 5. Gọi AI để lập báo cáo
    try:
        report = summarizer.analyze_task_with_srs(issue_data, srs_context)
        
        await _send_report_safe(
            update, 
            ctx, 
            msg, 
            report, 
            f"Jira_Analyze_{issue_key}", 
            f"Báo cáo phân tích task {issue_key} dựa trên SRS"
        )
            
    except Exception as e:
        logger.error(f"Lỗi khi AI phân tích task SRS: {e}", exc_info=True)
        await _edit(msg, escape(f"❌ Có lỗi khi phân tích: {str(e)}"))


@require_auth
@typing_action
async def cmd_missing_logwork(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ""
    if not update.callback_query and update.effective_message:
        text = update.effective_message.text or ""
    parts = text.strip().split(None, 1)
    assignee = parts[1].strip() if len(parts) > 1 else None
    
    target_str = f"cho user {assignee}" if assignee else "của bản thân"
    msg = await _send(update, escape(f"Đang tra cứu danh sách task thiếu logwork {target_str}..."))
    
    result = await jira_api.get_missing_logwork(assignee)
    await _edit(msg, result)


@require_auth
@typing_action
async def cmd_jira_estimate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ""
    if not update.callback_query and update.effective_message:
        text = update.effective_message.text or ""
    
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(
            bold("Cú pháp sử dụng:"),
            code("/estimate <mã_task_Jira>"),
            "Hoặc:",
            code("/estimate <nội_dung_mô_tả_yêu_cầu_công_việc>"),
            "",
            italic("Ví dụ: /estimate G038-19035"),
            italic("Ví dụ: /estimate Viết API đồng bộ thời tiết cho App HPG, lấy data từ OpenWeatherMap")
        ))
        return

    input_text = parts[1].strip()
    
    import re
    is_jira_key = bool(re.match(r'^[A-Za-z0-9]+-\d+$', input_text))
    
    if is_jira_key:
        issue_key = input_text.upper()
        msg = await _send(update, escape(f"🔍 Đang lấy dữ liệu từ Jira cho task {issue_key}..."))
        
        issue_data = await jira_api.get_issue_full(issue_key)
        if not issue_data:
            await _edit(msg, f"❌ Không tìm thấy task {escape(issue_key)} trên Jira hoặc có lỗi kết nối.")
            return
            
        await _edit(msg, escape(f"🔄 Đang quét các task Done mẫu trong cùng dự án và phân tích bằng AI..."))
        
        project_key = issue_key.split('-')[0]
        historical_issues = await jira_api.get_project_historical_issues(project_key=project_key)
        
        try:
            task_desc = f"{issue_data.get('summary', '')}\n{issue_data.get('description', '')}"
            estimate_report = summarizer.generate_jira_estimate(
                task_text=task_desc,
                historical_issues=historical_issues,
                task_key=issue_key
            )
            await _send_report_safe(update, ctx, msg, estimate_report, f"Jira_Estimate_{issue_key}", f"Đề xuất Estimate cho task {issue_key}")
        except Exception as e:
            logger.error(f"Error in cmd_jira_estimate for key {issue_key}: {e}", exc_info=True)
            await _edit(msg, escape(f"❌ Có lỗi khi AI phân tích: {str(e)}"))
            
    else:
        # Raw text / draft info
        msg = await _send(update, escape("🔄 Đang phân tích nội dung, quét lịch sử làm việc của bạn và gọi AI..."))
        
        historical_issues = await jira_api.get_project_historical_issues(assignee=None)
        
        try:
            estimate_report = summarizer.generate_jira_estimate(
                task_text=input_text,
                historical_issues=historical_issues,
                task_key=None
            )
            await _send_report_safe(update, ctx, msg, estimate_report, "AI_Estimate", "Đề xuất Estimate từ AI")
        except Exception as e:
            logger.error(f"Error in cmd_jira_estimate for raw text: {e}", exc_info=True)
            await _edit(msg, escape(f"❌ Có lỗi khi AI phân tích: {str(e)}"))


@require_auth
@typing_action
async def cmd_jira_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ""
    if not update.callback_query and update.effective_message:
        text = update.effective_message.text or ""
        
    parts = text.strip().split(None, 1)
    assignee = parts[1].strip() if len(parts) > 1 else None
    
    target_str = f"cho user {assignee}" if assignee else "của bản thân"
    msg = await _send(update, escape(f"📊 Đang tổng hợp hoạt động Jira tuần này {target_str}..."))
    
    weekly_data = await jira_api.get_weekly_dev_issues(assignee)
    
    if not weekly_data["resolved"] and not weekly_data["active"]:
        await _edit(
            msg, 
            f"🎉 Tuyệt vời! Không tìm thấy hoạt động Jira nào gần đây hoặc task đang hoạt động cho {bold(weekly_data['target_display'])}."
        )
        return
        
    await _edit(msg, escape(f"🧠 Đang gọi AI phân tích hiệu suất tuần và đánh giá rủi ro hiện tại..."))
    
    try:
        report = summarizer.generate_weekly_velocity_report(
            user_name=weekly_data["target_display"],
            resolved_issues=weekly_data["resolved"],
            active_issues=weekly_data["active"],
            total_logged_seconds=weekly_data["total_logged_seconds"]
        )
        await _send_report_safe(update, ctx, msg, report, f"Dev_Report_{weekly_data['target_display'].replace(' ', '_')}", f"Báo cáo hiệu suất của {weekly_data['target_display']}")
    except Exception as e:
        logger.error(f"Error in cmd_jira_report: {e}", exc_info=True)
        await _edit(msg, escape(f"❌ Có lỗi khi AI phân tích báo cáo tuần: {str(e)}"))


@require_auth
@typing_action
async def cmd_arch_design(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = ""
    if not update.callback_query and update.effective_message:
        text = update.effective_message.text or ""
        
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(
            bold("Cú pháp sử dụng:"),
            code("/arch <nội_dung_yêu_cầu_thiết_kế>"),
            "",
            italic("Ví dụ: /arch Bổ sung chuông thông báo nhắc việc trên app...")
        ))
        return
        
    requirement = parts[1].strip()
    msg = await _send(update, escape("🔄 Đang phân tích yêu cầu, quét ngầm đặc tả SRS liên quan và gọi AI kiến trúc sư..."))
    
    # RAG search: Use first 60 chars of the requirement to find relevant SRS blocks
    search_query = requirement[:60]
    srs_results = await search_srs_knowledge(search_query, limit=5)
    
    srs_context = ""
    if srs_results:
        context_parts = []
        for r in srs_results:
            src_clean = r['source'].replace("srs:", "") if r['source'] else "SRS Document"
            context_parts.append(f"--- [Đặc tả từ: {src_clean}] ---\n{r['content']}")
        srs_context = "\n\n".join(context_parts)
        
    try:
        report = summarizer.generate_architecture_design(
            requirement_text=requirement,
            srs_context=srs_context
        )
        await _send_report_safe(update, ctx, msg, report, "Arch_Design", "Tài liệu Thiết kế Kiến trúc Hệ thống")
    except Exception as e:
        logger.error(f"Error in cmd_arch_design: {e}", exc_info=True)
        await _edit(msg, escape(f"❌ Có lỗi khi AI thiết kế kiến trúc: {str(e)}"))


@require_auth
@typing_action
async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_review(update, ctx, full=False)

@require_auth
@typing_action
async def cmd_review_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_review(update, ctx, full=True)

async def _do_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE, full: bool = False):
    text = update.effective_message.text
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        cmd_name = "/review_full" if full else "/review"
        await _send(update, build(bold("Cú pháp:"), code(f"{cmd_name} <link_gitlab_mr>")))
        return

    mr_link = parts[1].strip()
    status_msg = "đầy đủ nội dung file" if full else "code thay đổi (diff)"
    msg = await _send(update, escape(f"Đang kết nối GitLab để lấy {status_msg}..."))
    
    mr_data = await gitlab_api.get_mr_diff(mr_link, include_full_file=full)
    if mr_data.get("error"):
        await _edit(msg, escape(mr_data["error"]))
        return
        
    code_content = mr_data.get("diff", "")
    if not code_content:
        await _edit(msg, escape("Không có thay đổi code nào trong MR này."))
        return
        
    await _edit(msg, build(
        f"✅ {bold('Đã lấy code thành công:')} {escape(mr_data['title'])}",
        f"⏳ {italic('Đang gửi cho AI để review, vui lòng đợi...')}"
    ))
    
    try:
        review_result = summarizer.review_code_changes(code_content, is_full_file=full)
        await _send_report_safe(
            update,
            ctx,
            msg,
            review_result,
            f"MR_Review_{mr_data.get('title', 'Code')[:30].replace(' ', '_')}",
            f"Đánh giá & Review Code cho MR: {mr_data.get('title', '')}"
        )
    except Exception as e:
        logger.error(f"AI Review error: {e}")
        await _edit(msg, escape(f"❌ Có lỗi khi AI review: {str(e)}"))

# ─── Register ────────────────────────────────────────────────

def register(app):
    from telegram.ext import MessageHandler, filters
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_help_callback, pattern="^(help:|cmd:)"))
    app.add_handler(CommandHandler("chats", cmd_chats))
    app.add_handler(CommandHandler("sum", cmd_sum))
    app.add_handler(CommandHandler("tldr", cmd_tldr))
    app.add_handler(CommandHandler("vibe", cmd_vibe))
    app.add_handler(CommandHandler("who", cmd_who))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("sentiment", cmd_sentiment))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("reply", cmd_reply))
    app.add_handler(CommandHandler("debate", cmd_debate))  # ← MỚI
    app.add_handler(CommandHandler("spy", cmd_spy))        # ← MỚI
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("endchat", cmd_endchat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))


@require_auth
@typing_action
async def cmd_release_mr(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await _send(update, build(bold("Cú pháp:"), code("/release_mr <link_gitlab_mr>")))
        return

    mr_link = parts[1].strip()
    msg = await _send(update, escape("Đang truy vấn thông tin Merge Request từ GitLab..."))

    # 1. Lấy tags để tìm phiên bản hiện tại
    tag_result = await gitlab_api.get_latest_project_tag(mr_link)
    if tag_result.get("error"):
        await _edit(msg, escape(tag_result["error"]))
        return
    current_tag = tag_result.get("tag")

    # 2. Lấy danh sách commits của MR
    commits_result = await gitlab_api.get_mr_commits(mr_link)
    if commits_result.get("error"):
        await _edit(msg, escape(commits_result["error"]))
        return
    
    commits = commits_result.get("commits", [])
    if not commits:
        await _edit(msg, escape("Không tìm thấy commit nào trong Merge Request này."))
        return

    await _edit(msg, build(
        f"✅ {bold('Đã lấy dữ liệu thành công:')} {escape(str(len(commits)))} commits.",
        f"⏳ {italic('Đang gửi cho AI để phân tích và đề xuất Release...')}"
    ))

    # 3. Phân tích bằng LLM
    try:
        import re
        project_name = "SmartTown"
        match_path = re.search(r"/([^/]+)/-/merge_requests", mr_link)
        if match_path:
            raw_name = match_path.group(1)
            if "zalominiapp.vncitizens" in raw_name:
                project_name = "SmartTown"
            elif "vncitizens" in raw_name:
                project_name = "VnCitizens"
            else:
                project_name = raw_name.replace("svc.", "").replace("zalominiapp.", "").replace("-", " ").title()

        release_proposal = summarizer.analyze_release_commits(commits, current_tag, project_name)
        await _send_report_safe(
            update,
            ctx,
            msg,
            release_proposal,
            f"Release_Proposal_{project_name.replace(' ', '_')}",
            f"Đề xuất phiên bản & Release Notes cho {project_name}"
        )
    except Exception as e:
        logger.error(f"AI Release analysis error: {e}")
        await _edit(msg, escape(f"❌ Có lỗi khi AI phân tích release: {str(e)}"))


def increment_tag(tag: str) -> str:
    """
    Tăng tag hiện tại thêm 1 đơn vị.
    Ví dụ:
      v1.1.3 -> v1.1.4
      v1.5.9 -> v1.6.0
      v1.0.9 -> v1.1.0
    """
    if not tag:
        return "v1.0.0"
        
    prefix = ""
    if tag.lower().startswith("v"):
        prefix = tag[0]
        tag_num = tag[1:]
    else:
        tag_num = tag
        
    parts = tag_num.split(".")
    if len(parts) != 3:
        return prefix + tag_num + ".1"
        
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])
    except ValueError:
        return prefix + tag_num + ".1"
        
    if patch == 9:
        minor += 1
        patch = 0
    else:
        patch += 1
        
    return f"{prefix}{major}.{minor}.{patch}"


@require_auth
@typing_action
async def cmd_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /release - Khởi tạo quy trình release chọn 1 trong 2 ứng dụng.
    """
    keyboard = [
        [
            InlineKeyboardButton("SmartTown", callback_data="release:select:smarttown"),
            InlineKeyboardButton("VnCitizens", callback_data="release:select:vncitizens")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = build(
        f"🚀 {bold('QUY TRÌNH AUTOMATED RELEASE')}",
        "",
        escape("Vui lòng chọn ứng dụng bạn muốn release:")
    )
    
    await send_message_safe(update.get_bot(), _chat_id(update), text, reply_markup=reply_markup, parse_mode=MODE)


@require_auth
async def handle_release_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Xử lý các callback query liên quan tới quy trình release.
    """
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    
    if parts[1] == "cancel":
        await query.edit_message_text(
            text=build(
                f"❌ {bold('QUY TRÌNH AUTOMATED RELEASE')}",
                "",
                escape("Đã hủy bỏ quy trình release.")
            ),
            parse_mode=MODE
        )
        return
        
    app_key = parts[2]
    projects = {
        "smarttown": {
            "name": "SmartTown",
            "path": "it5.ptgp.digo/vncitizens/flutter.vncitizens.smarttown"
        },
        "vncitizens": {
            "name": "VnCitizens",
            "path": "it5.ptgp.digo/vncitizens/flutter.vncitizens"
        }
    }
    
    if app_key not in projects:
        await query.edit_message_text("Lỗi: Ứng dụng không hợp lệ.")
        return
        
    project = projects[app_key]
    project_name = project["name"]
    project_path = project["path"]
    
    if parts[1] == "select":
        # 1. Hiển thị trạng thái đang kiểm tra
        await query.edit_message_text(
            text=build(
                f"⏳ {bold(f'RELEASE: {project_name.upper()}')}",
                "",
                escape("Đang kiểm tra Merge Request và thông tin tag hiện tại trên GitLab...")
            ),
            parse_mode=MODE
        )
        
        # 2. Kiểm tra/Tạo Merge Request dev -> master
        mr_res = await gitlab_api.check_existing_mr(project_path, source="dev", target="master")
        if mr_res.get("error"):
            await query.edit_message_text(f"❌ Lỗi khi kiểm tra MR: {escape(mr_res['error'])}", parse_mode=MODE)
            return
            
        mr = mr_res.get("mr")
        is_new_mr = False
        if not mr:
            # Tạo MR mới
            create_res = await gitlab_api.create_mr(
                project_path, 
                source="dev", 
                target="master", 
                title=f"Release dev to master - {project_name}"
            )
            if create_res.get("error"):
                await query.edit_message_text(f"❌ Lỗi khi tạo MR mới: {escape(create_res['error'])}", parse_mode=MODE)
                return
            mr = create_res.get("mr")
            is_new_mr = True
            
        mr_iid = mr["iid"]
        mr_url = mr["web_url"]
        
        # 3. Lấy tag phiên bản hiện tại
        tag_result = await gitlab_api.get_latest_project_tag(mr_url)
        if tag_result.get("error"):
            await query.edit_message_text(f"❌ Lỗi lấy tag: {escape(tag_result['error'])}", parse_mode=MODE)
            return
            
        current_tag = tag_result.get("tag")
        suggested_tag = increment_tag(current_tag)
        
        # 4. Lấy danh sách commits của MR
        commits_result = await gitlab_api.get_mr_commits(mr_url)
        if commits_result.get("error"):
            await query.edit_message_text(f"❌ Lỗi lấy commits: {escape(commits_result['error'])}", parse_mode=MODE)
            return
            
        commits = commits_result.get("commits", [])
        if not commits:
            # Tìm MR đã merge gần nhất từ dev sang master
            merged_mr_res = await gitlab_api.get_latest_merged_mr(project_path, source="dev", target="master")
            if merged_mr_res.get("error"):
                await query.edit_message_text(
                    text=f"❌ Không tìm thấy thay đổi mới và lỗi khi tra cứu MR đã merge trước đó: {escape(merged_mr_res['error'])}", 
                    parse_mode=MODE
                )
                return
                
            merged_mr = merged_mr_res.get("mr")
            if not merged_mr:
                await query.edit_message_text(
                    text=build(
                        f"⚠️ {bold(f'RELEASE: {project_name.upper()}')}",
                        "",
                        escape("Không tìm thấy commit khác biệt nào giữa dev và master, và cũng không tìm thấy Merge Request đã merge nào trước đó.")
                    ),
                    parse_mode=MODE
                )
                return
                
            merged_mr_iid = merged_mr["iid"]
            merged_mr_url = merged_mr["web_url"]
            merged_mr_title = merged_mr["title"]
            
            # Lấy commits của MR đã merge đó để hiển thị
            merged_commits_res = await gitlab_api.get_mr_commits(merged_mr_url)
            merged_commits = merged_commits_res.get("commits", [])
            
            commit_lines = []
            for c in merged_commits[:10]:
                author = escape(c.get("author_name", "Anonymous"))
                title = escape(c.get("title", ""))
                commit_lines.append(f"• [{author}] {title}")
            if len(merged_commits) > 10:
                commit_lines.append(f"• ... và {len(merged_commits) - 10} commits khác.")
                
            text = build(
                f"⚠️ {bold(f'RELEASE: {project_name.upper()}')}",
                "",
                escape("Không tìm thấy commit khác biệt mới nào giữa dev và master (Nhánh dev đã được merge)."),
                "",
                f"🔍 Tìm thấy Merge Request đã merge gần đây nhất:",
                f"🔗 <a href='{merged_mr_url}'>#{merged_mr_iid} {escape(merged_mr_title)}</a>",
                "",
                f"🏷️ {bold('Tag hiện tại')}: {code(current_tag or 'Không có')}",
                f"🆕 {bold('Tag đề xuất (+1)')}: {bold(suggested_tag)}",
                f"🔢 {bold('Số lượng commit trong MR')}: {len(merged_commits)}",
                "",
                bold("📝 Xem trước commits trong MR đã merge (tối đa 10):"),
                *commit_lines,
                "",
                italic("Bạn có muốn tiếp tục tạo release tag cho Merge Request đã merge này không?")
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Xác nhận Tạo Tag", callback_data=f"release:confirm_tag:{app_key}:{merged_mr_iid}:{suggested_tag}"),
                    InlineKeyboardButton("❌ Hủy", callback_data="release:cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=MODE)
            return
            
        # 5. Hiển thị thông tin review cơ bản
        commit_lines = []
        for c in commits[:10]:
            author = escape(c.get("author_name", "Anonymous"))
            title = escape(c.get("title", ""))
            commit_lines.append(f"• [{author}] {title}")
        if len(commits) > 10:
            commit_lines.append(f"• ... và {len(commits) - 10} commits khác.")
            
        mr_status_str = "Tạo mới" if is_new_mr else "Đã có sẵn"
        
        text = build(
            f"🚀 {bold(f'XÁC NHẬN RELEASE: {project_name.upper()}')}",
            "",
            f"🔗 {bold('Merge Request')}: <a href='{mr_url}'>#{mr_iid} Release dev to master</a> ({mr_status_str})",
            f"🏷️ {bold('Tag hiện tại')}: {code(current_tag or 'Không có')}",
            f"🆕 {bold('Tag đề xuất (+1)')}: {bold(suggested_tag)}",
            f"🔢 {bold('Số lượng commit')}: {len(commits)}",
            "",
            bold("📝 Xem trước commits (tối đa 10):"),
            *commit_lines,
            "",
            italic("Vui lòng nhấn nút phía dưới để xác nhận merge và tự động tạo tag release.")
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Xác nhận Merge", callback_data=f"release:confirm_merge:{app_key}:{mr_iid}:{suggested_tag}"),
                InlineKeyboardButton("❌ Hủy", callback_data="release:cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=MODE)
        
    elif parts[1] == "confirm_merge":
        mr_iid = int(parts[3])
        suggested_tag = parts[4]
        
        # 1. Trạng thái đang merge
        await query.edit_message_text(
            text=build(
                f"⏳ {bold(f'RELEASE: {project_name.upper()}')}",
                "",
                f"Đang tiến hành merge MR #{mr_iid} và tạo tag release `{suggested_tag}`..."
            ),
            parse_mode=MODE
        )
        
        # 2. Merge MR
        merge_res = await gitlab_api.merge_mr(project_path, mr_iid)
        if merge_res.get("error"):
            await query.edit_message_text(
                text=build(
                    f"❌ {bold(f'RELEASE THẤT BẠI: {project_name.upper()}')}",
                    "",
                    f"Không thể merge MR #{mr_iid}. Lỗi từ GitLab:",
                    code(escape(merge_res["error"])),
                    "",
                    italic("Vui lòng kiểm tra lại trạng thái MR trên trang GitLab.")
                ),
                parse_mode=MODE
            )
            return
            
        # 3. Lấy commits của MR để tạo Release Notes
        from config import GITLAB_BASE_URL
        mr_url = f"{GITLAB_BASE_URL}/{project_path}/-/merge_requests/{mr_iid}"
        commits_res = await gitlab_api.get_mr_commits(mr_url)
        commits = commits_res.get("commits", [])
        
        # Tạo Release Notes qua AI
        release_notes = ""
        try:
            if commits:
                release_notes = summarizer.generate_release_notes(commits, project_name)
            else:
                release_notes = "Tóm tắt tự động: Release phiên bản mới."
        except Exception as llm_err:
            logger.error(f"LLM Release Notes generation failed: {llm_err}")
            release_notes = f"Release note tự động từ các commit của MR #{mr_iid}."
            
        # 4. Tạo Release Tag trên master
        tag_res = await gitlab_api.create_tag(
            project_path=project_path,
            tag_name=suggested_tag,
            ref="master",
            description=release_notes
        )
        
        if tag_res.get("error"):
            await query.edit_message_text(
                text=build(
                    f"⚠️ {bold(f'RELEASE BỊ LỖI PHẦN TẠO TAG: {project_name.upper()}')}",
                    "",
                    f"✅ Đã merge thành công MR #{mr_iid} vào master.",
                    f"❌ Tuy nhiên, việc tạo tag `{suggested_tag}` thất bại. Lỗi:",
                    code(escape(tag_res["error"])),
                    "",
                    bold("Release Notes dự kiến:"),
                    escape(release_notes)
                ),
                parse_mode=MODE
            )
            return
            
        # 5. Hoàn thành
        await query.edit_message_text(
            text=build(
                f"🎉 {bold(f'RELEASE THÀNH CÔNG: {project_name.upper()}')}",
                "",
                f"✅ Đã merge thành công MR #{mr_iid} vào nhánh master.",
                f"🏷️ Đã tạo tag release mới: {bold(suggested_tag)} từ master.",
                "",
                bold("📝 Release Notes (Tóm tắt bởi AI):"),
                ai_to_mdv2(release_notes)
            ),
            parse_mode=MODE
        )

    elif parts[1] == "confirm_tag":
        mr_iid = int(parts[3])
        suggested_tag = parts[4]
        
        # 1. Trạng thái đang tạo tag
        await query.edit_message_text(
            text=build(
                f"⏳ {bold(f'RELEASE (TẠO TAG): {project_name.upper()}')}",
                "",
                f"Đang tiến hành tạo tag release `{suggested_tag}` từ MR #{mr_iid} đã được merge trước đó..."
            ),
            parse_mode=MODE
        )
        
        # 2. Lấy commits của MR để tạo Release Notes
        from config import GITLAB_BASE_URL
        mr_url = f"{GITLAB_BASE_URL}/{project_path}/-/merge_requests/{mr_iid}"
        commits_res = await gitlab_api.get_mr_commits(mr_url)
        commits = commits_res.get("commits", [])
        
        # Tạo Release Notes qua AI
        release_notes = ""
        try:
            if commits:
                release_notes = summarizer.generate_release_notes(commits, project_name)
            else:
                release_notes = "Tóm tắt tự động: Release phiên bản mới."
        except Exception as llm_err:
            logger.error(f"LLM Release Notes generation failed: {llm_err}")
            release_notes = f"Release note tự động từ các commit của MR #{mr_iid}."
            
        # 3. Tạo Release Tag trên master
        tag_res = await gitlab_api.create_tag(
            project_path=project_path,
            tag_name=suggested_tag,
            ref="master",
            description=release_notes
        )
        
        if tag_res.get("error"):
            await query.edit_message_text(
                text=build(
                    f"❌ {bold(f'TẠO TAG THẤT BẠI: {project_name.upper()}')}",
                    "",
                    f"Không thể tạo tag `{suggested_tag}`. Lỗi:",
                    code(escape(tag_res["error"])),
                    "",
                    bold("Release Notes dự kiến:"),
                    escape(release_notes)
                ),
                parse_mode=MODE
            )
            return
            
        # 4. Hoàn thành
        await query.edit_message_text(
            text=build(
                f"🎉 {bold(f'TẠO TAG THÀNH CÔNG: {project_name.upper()}')}",
                "",
                f"🏷️ Đã tạo tag release mới: {bold(suggested_tag)} từ master (dựa trên MR #{mr_iid} đã merge).",
                "",
                bold("📝 Release Notes (Tóm tắt bởi AI):"),
                ai_to_mdv2(release_notes)
            ),
            parse_mode=MODE
        )



@require_auth
async def cmd_jira_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu trợ giúp chính phân loại các tính năng cho Bot Jira (Dev Bot)."""
    text = build(
        f"🛠️ {bold('Hệ thống Trợ lý Dev Bot (Jira, GitLab & Infrastructure)')}",
        "",
        escape("Chào mừng bạn đến với Dev Bot! Hãy chọn nhóm chức năng bên dưới để thao tác nhanh hoặc xem cú pháp:"),
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🎫 Jira & Worklog", callback_data="jira_help:group_jira"),
            InlineKeyboardButton("🔍 Code Review & MR", callback_data="jira_help:group_review")
        ],
        [
            InlineKeyboardButton("🚀 Build & Release", callback_data="jira_help:group_release"),
            InlineKeyboardButton("🐳 Docker & AI Agent", callback_data="jira_help:group_docker")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await edit_message_safe(
            context.bot, 
            update.effective_chat.id, 
            update.callback_query.message.message_id, 
            text, 
            reply_markup=reply_markup, 
            parse_mode="HTML"
        )
    else:
        if hasattr(update.effective_message, "reply_text"):
            await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await send_message_safe(context.bot, update.effective_chat.id, text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_jira_help_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Điều hướng callback query cho Bot Jira Help."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("jira_help:group_"):
        group = data.replace("jira_help:group_", "")
        await show_jira_help_group(update, ctx, group)
        return
        
    elif data == "jira_help:main":
        await cmd_jira_help(update, ctx)
        return
        
    from handlers.build import cmd_build_version
    from handlers.delegate_handler import cmd_delegates
    from handlers.docker_handler import cmd_docker
    from handlers.code_search import cmd_search_code
    
    cmd_map = {
        "cmd:jira_logwork": cmd_missing_logwork,
        "cmd:jira_release": cmd_release,
        "cmd:jira_build": cmd_build_version,
        "cmd:jira_docker": cmd_docker,
        "cmd:jira_delegates": cmd_delegates,
        "cmd:jira_srs_list": cmd_jira_srs_list,
        "cmd:jira_report": cmd_jira_report,
        "cmd:jira_search_code": cmd_search_code,
    }
    
    handler = cmd_map.get(data)
    if handler:
        # Xóa tin nhắn help cũ đi để mở giao diện dashboard mới sạch sẽ
        await query.message.delete()
        await handler(update, ctx)


async def show_jira_help_group(update: Update, context: ContextTypes.DEFAULT_TYPE, group: str):
    """Hiển thị nội dung trợ giúp chi tiết theo nhóm trên Bot Jira."""
    groups = {
        "jira": {
            "title": "🎫 JIRA, WORKLOG & SRS",
            "commands": [
                "/jira <mã_task> — Xem nhanh chi tiết Task trên Jira",
                "/jira_risk <mã_task> — AI phân tích rủi ro trễ hạn task",
                "/missing_logwork [user] — Danh sách task chưa logwork đủ",
                "/logwork [user] — Xem nhanh logwork thiếu",
                "/estimate <mã_task_hoặc_mô_tả> — AI gợi ý thời gian estimate",
                "/report [user] — Báo cáo hiệu suất tuần & đánh giá rủi ro",
                "/arch <nội_dung_yêu_cầu> — AI thiết kế hệ thống & database",
                "/jira_srs_upload — Nạp tài liệu đặc tả SRS mới (.docx, .pdf, .zip...)",
                "/jira_srs_list — Xem danh sách các file đặc tả SRS đã nạp",
                "/jira_analyze <mã_task> — AI đối chiếu SRS để thiết kế giải pháp & checklist"
            ],
            "buttons": [
                [
                    InlineKeyboardButton("⏰ Check Logwork", callback_data="cmd:jira_logwork"),
                    InlineKeyboardButton("📋 Danh sách SRS", callback_data="cmd:jira_srs_list")
                ],
                [
                    InlineKeyboardButton("📊 Báo cáo Tuần", callback_data="cmd:jira_report")
                ]
            ]
        },
        "review": {
            "title": "🔍 CODE REVIEW & MR",
            "commands": [
                "/review <link_mr> — AI review code thay đổi (diff) trên MR",
                "/review_full <link_mr> — AI review toàn bộ nội dung file trong MR",
                "/release_mr <link_mr> — AI phân tích commit và đề xuất Release",
                "/search_code — Tra cứu API & Kiểm tra tham số từ SCM/Codebase"
            ],
            "buttons": [
                [
                    InlineKeyboardButton("🔍 Tìm kiếm Codebase/API", callback_data="cmd:jira_search_code")
                ]
            ]
        },
        "release": {
            "title": "🚀 BUILD & RELEASE",
            "commands": [
                "/release — Khởi tạo quy trình merge và release ứng dụng",
                "/build_version — Quản lý các phiên bản build",
                "/cicd_branch — Chạy CICD theo branch tùy chỉnh"
            ],
            "buttons": [
                [
                    InlineKeyboardButton("🚀 Chạy Release", callback_data="cmd:jira_release"),
                    InlineKeyboardButton("📦 Bản Build", callback_data="cmd:jira_build")
                ],
                [
                    InlineKeyboardButton("🌿 CICD theo Branch", callback_data="cicd_br:start")
                ]
            ]
        },
        "docker": {
            "title": "🐳 DOCKER & AI AGENT",
            "commands": [
                "/docker — Bảng điều khiển quản lý Docker Container",
                "/delegate <chủ đề> — Ủy thác nghiên cứu chạy ngầm",
                "/delegates — Xem danh sách các task nghiên cứu chạy ngầm"
            ],
            "buttons": [
                [
                    InlineKeyboardButton("🐳 Docker Dashboard", callback_data="cmd:jira_docker"),
                    InlineKeyboardButton("📋 DS Nghiên cứu", callback_data="cmd:jira_delegates")
                ]
            ]
        }
    }
    
    g = groups.get(group)
    if not g: return
    
    text = build(
        f"📍 {bold(g['title'])}",
        "",
        *[escape(cmd) for cmd in g['commands']],
        "",
        italic("Bấm nút dưới để thực hiện nhanh:") if g['buttons'] else ""
    )
    
    keyboard = g['buttons'] + [[InlineKeyboardButton("⬅️ Quay lại", callback_data="jira_help:main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await edit_message_safe(
        context.bot, 
        update.effective_chat.id, 
        update.callback_query.message.message_id, 
        text, 
        reply_markup=reply_markup, 
        parse_mode="HTML"
    )


def register_jira_handlers(app):
    app.add_handler(CommandHandler("start", cmd_jira_help))
    app.add_handler(CommandHandler("help", cmd_jira_help))
    app.add_handler(CommandHandler("jira", cmd_jira))
    app.add_handler(CommandHandler("jira_risk", cmd_jira_risk))
    app.add_handler(CommandHandler("jira_srs_upload", cmd_jira_srs_upload))
    app.add_handler(CommandHandler("jira_srs_list", cmd_jira_srs_list))
    app.add_handler(CommandHandler("jira_srs_delete", cmd_jira_srs_delete))
    app.add_handler(CommandHandler("jira_analyze", cmd_jira_analyze))
    app.add_handler(CommandHandler("missing_logwork", cmd_missing_logwork))
    app.add_handler(CommandHandler("logwork", cmd_missing_logwork))
    app.add_handler(CommandHandler("jira_estimate", cmd_jira_estimate))
    app.add_handler(CommandHandler("estimate", cmd_jira_estimate))
    app.add_handler(CommandHandler("jira_report", cmd_jira_report))
    app.add_handler(CommandHandler("report", cmd_jira_report))
    app.add_handler(CommandHandler("jira_arch", cmd_arch_design))
    app.add_handler(CommandHandler("arch_design", cmd_arch_design))
    app.add_handler(CommandHandler("arch", cmd_arch_design))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("review_full", cmd_review_full))
    app.add_handler(CommandHandler("release_mr", cmd_release_mr))
    app.add_handler(CommandHandler("release", cmd_release))
    app.add_handler(CallbackQueryHandler(handle_release_callback, pattern="^release:"))
    app.add_handler(CallbackQueryHandler(handle_jira_srs_callback, pattern="^jira_srs:"))
    app.add_handler(CallbackQueryHandler(handle_jira_help_callback, pattern="^(jira_help:|cmd:jira_)"))
    
    # Cho phép Jira Bot nhận và xử lý file đặc tả SRS khi ở trong phiên upload
    from telegram.ext import MessageHandler, filters
    from handlers.brain import handle_document
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))



