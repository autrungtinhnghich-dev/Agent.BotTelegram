"""
handlers/cicd_branch.py

Quy trình CICD theo branch bằng GitLab API:
  1. /cicd_branch hoặc bấm nút inline → Hiển thị 4 branch mặc định + nút tải thêm + nút nhập branch thủ công.
  2. Bấm branch (hoặc nhập branch thủ công) → Tải pubspec.yaml từ GitLab của branch đó, parse version & ref hiện tại, lấy commit gần nhất.
  3. Hiển thị bảng Preview cấu hình.
  4. Cho phép sửa Version, Ref, Commit Msg qua các nút tương ứng.
  5. Bấm Xác nhận & Chạy → Commit pubspec.yaml mới trực tiếp lên GitLab qua API để trigger pipeline.
  6. Sau khi thành công, hiển thị nút Quay lại để dễ dàng thực hiện lại hoặc quay về danh sách.
"""

from __future__ import annotations

import logging
import re
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import ALLOWED_USER_IDS
from services.markdown import escape, bold, italic, code, build
from services.telegram_utils import send_message_safe, edit_message_safe

logger = logging.getLogger(__name__)

MODE = "HTML"

PROJECT_PATH = "it5.ptgp.digo/vncitizens/flutter.vncitizens.smarttown"
PUBSPEC_FILE_PATH = "pubspec.yaml"

# ─── Conversation states ─────────────────────────────────────
(
    SELECT_BRANCH,
    CONFIRM_OR_EDIT,
    EDIT_VERSION,
    EDIT_REF,
    EDIT_COMMIT_MSG,
    INPUT_CUSTOM_BRANCH,  # Trạng thái nhập branch thủ công
) = range(6)

DEFAULT_BRANCHES = ["cudanso", "demo", "iward", "myward"]


# ─── Auth decorator ──────────────────────────────────────────
def require_auth(fn):
    @wraps(fn)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if ALLOWED_USER_IDS and uid not in ALLOWED_USER_IDS:
            msg = update.effective_message
            if msg:
                await msg.reply_text("Bạn không có quyền dùng tính năng này.")
            return ConversationHandler.END
        return await fn(update, ctx)
    return wrapper


# ─── Helpers ─────────────────────────────────────────────────
async def _answer(update: Update):
    """Answer callback query nếu có (tránh loading vòng tròn)."""
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass


async def _edit_message(query_or_msg, text: str, reply_markup=None, parse_mode=None):
    """Gửi hoặc sửa tin nhắn Telegram an toàn chống lỗi NetworkError."""
    if hasattr(query_or_msg, "edit_message_text"):
        # CallbackQuery
        bot = query_or_msg.get_bot()
        chat_id = query_or_msg.message.chat_id
        message_id = query_or_msg.message.message_id
        kwargs = {}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        return await edit_message_safe(bot, chat_id, message_id, text, **kwargs)
    else:
        # Message
        bot = query_or_msg.get_bot()
        chat_id = query_or_msg.chat_id
        kwargs = {}
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        return await send_message_safe(bot, chat_id, text, **kwargs)


def _branches_keyboard(branches: list[str], show_more: bool = True) -> InlineKeyboardMarkup:
    """Tạo bàn phím hiển thị danh sách branch."""
    rows = []
    row = []
    for b in branches:
        row.append(InlineKeyboardButton(f"🌿 {b}", callback_data=f"cicd_br:select:{b}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
        
    if show_more:
        rows.append([InlineKeyboardButton("➕ Tải thêm branch từ GitLab", callback_data="cicd_br:fetch_all")])
        
    rows.append([InlineKeyboardButton("✏️ Nhập tên branch khác", callback_data="cicd_br:input_custom")])
    rows.append([InlineKeyboardButton("❌ Huỷ", callback_data="cicd:cancel")])
    return InlineKeyboardMarkup(rows)


def parse_pubspec_version(content: str) -> str | None:
    """Trích xuất version từ file pubspec.yaml content."""
    match = re.search(r'^version:\s*(\S+)', content, re.MULTILINE)
    if match:
        val = match.group(1)
        if '#' in val:
            val = val.split('#', 1)[0]
        return val.strip()
    return None


def parse_pubspec_ref(content: str) -> str | None:
    """Trích xuất ref của smarttown_common git từ pubspec.yaml content."""
    pattern = r'url:\s*https://scm\.devops\.vnpt\.vn/.*/flutter\.vncitizens\.smarttown\.git\s*\n\s*ref:\s*(\S+)'
    match = re.search(pattern, content)
    if match:
        val = match.group(1)
        if '#' in val:
            val = val.split('#', 1)[0]
        return val.strip()
    
    # Fallback tìm kiếm ref: dòng đầu tiên
    match = re.search(r'ref:\s*(\S+)', content)
    if match:
        val = match.group(1)
        if '#' in val:
            val = val.split('#', 1)[0]
        return val.strip()
    return None


def update_pubspec_content(content: str, new_version: str, new_ref: str) -> str:
    """Thay thế phiên bản và các ref git dependency trong file pubspec.yaml content."""
    lines = content.splitlines(keepends=True)
    new_lines = []
    in_git_block = False
    for line in lines:
        # 1. Update version
        if line.startswith('version:'):
            parts = line.split(':', 1)
            comment = ""
            if '#' in parts[1]:
                parts[1], comment = parts[1].split('#', 1)
                comment = " #" + comment.rstrip()
            new_lines.append(f"version: {new_version}{comment}\n")
            continue
        
        # 2. Check for git block
        if 'git:' in line:
            in_git_block = True
        
        if in_git_block and 'url:' in line:
            if 'flutter.vncitizens.smarttown.git' not in line:
                in_git_block = False
                
        if in_git_block and 'ref:' in line:
            indent = len(line) - len(line.lstrip())
            comment = ""
            if '#' in line:
                _, comment = line.split('#', 1)
                comment = " #" + comment.rstrip()
            new_lines.append(f"{' ' * indent}ref: {new_ref}{comment}\n")
            continue
            
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            indent = len(line) - len(line.lstrip())
            if indent <= 4 and 'git:' not in line and 'url:' not in line and 'ref:' not in line and 'path:' not in line:
                in_git_block = False
                
        new_lines.append(line)
        
    return "".join(new_lines)


# ─── Entry Point ─────────────────────────────────────────────
@require_auth
async def cmd_cicd_branch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    
    text = build(
        bold("🌿 CICD THEO BRANCH"),
        "",
        escape("Vui lòng chọn branch để cấu hình chạy CI/CD:")
    )
    keyboard = _branches_keyboard(DEFAULT_BRANCHES, show_more=True)
    
    if update.callback_query:
        await _edit_message(update.callback_query, text, keyboard, MODE)
    else:
        await send_message_safe(
            bot=ctx.bot,
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            parse_mode=MODE
        )
    return SELECT_BRANCH


# ─── Callback: Fetch all branches ─────────────────────────────
async def cb_fetch_all_branches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    await _edit_message(
        query,
        text=build(
            bold("🌿 CICD THEO BRANCH"),
            "",
            italic("⏳ Đang tải toàn bộ danh sách branch từ GitLab...")
        ),
        parse_mode=MODE
    )
    
    import services.gitlab_api as gitlab_api
    try:
        res = await gitlab_api.get_project_branches(PROJECT_PATH, timeout=8.0, max_attempts=2)
    except Exception as e:
        logger.error(f"Lỗi khi fetch branches từ GitLab: {e}", exc_info=True)
        res = {"error": f"Lỗi hệ thống: {str(e)}"}

    if res.get("error"):
        await _edit_message(
            query,
            text=build(
                bold("🌿 CICD THEO BRANCH"),
                "",
                f"❌ Lỗi: {escape(res['error'])}",
                "",
                escape("Vui lòng chọn từ các branch mặc định:")
            ),
            reply_markup=_branches_keyboard(DEFAULT_BRANCHES, show_more=False),
            parse_mode=MODE
        )
        return SELECT_BRANCH
        
    branches = res.get("branches", [])
    if not branches:
        branches = DEFAULT_BRANCHES
        
    # Sắp xếp các branch
    def rank_key(b):
        b_lower = b.lower()
        if 'autrungtinhnghich' in b_lower:
            return (0, b_lower)
        elif b_lower in DEFAULT_BRANCHES:
            order = DEFAULT_BRANCHES.index(b_lower)
            return (1, order)
        else:
            return (2, b_lower)
            
    branches.sort(key=rank_key)
    limited_branches = branches[:24]
    
    await _edit_message(
        query,
        text=build(
            bold("🌿 CICD THEO BRANCH"),
            "",
            escape("Đã lấy được danh sách branch. Vui lòng chọn:")
        ),
        reply_markup=_branches_keyboard(limited_branches, show_more=False),
        parse_mode=MODE
    )
    return SELECT_BRANCH


# ─── Callback: Input custom branch name ────────────────────────
async def cb_input_custom_branch_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    await _edit_message(
        query,
        text=build(
            bold("✏️ NHẬP TÊN BRANCH THỦ CÔNG"),
            "",
            escape("Vui lòng nhập tên branch bạn muốn chạy cấu hình:")
        ),
        parse_mode=MODE
    )
    return INPUT_CUSTOM_BRANCH


async def handle_input_custom_branch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    
    if not val or any(c.isspace() for c in val):
        await update.effective_message.reply_text(
            text="❌ Tên branch không hợp lệ (không chứa khoảng trắng). Vui lòng nhập lại:"
        )
        return INPUT_CUSTOM_BRANCH
        
    ctx.user_data["cicd_target_branch"] = val
    
    status_msg = await update.effective_message.reply_text(
        text=build(
            bold(f"🌿 BRANCH: {val.upper()}"),
            "",
            italic("⏳ Đang tải file pubspec.yaml và tin nhắn commit gần đây nhất...")
        ),
        parse_mode=MODE
    )
    
    return await _load_branch_and_show_preview(status_msg, val, ctx)


# ─── Callback: Select branch ──────────────────────────────────
async def cb_select_branch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    branch_name = query.data.replace("cicd_br:select:", "")
    ctx.user_data["cicd_target_branch"] = branch_name
    
    await _edit_message(
        query,
        text=build(
            bold(f"🌿 BRANCH: {branch_name.upper()}"),
            "",
            italic("⏳ Đang tải file pubspec.yaml và tin nhắn commit gần đây nhất...")
        ),
        parse_mode=MODE
    )
    
    return await _load_branch_and_show_preview(query, branch_name, ctx)


async def _load_branch_and_show_preview(query_or_msg, branch_name: str, ctx: ContextTypes.DEFAULT_TYPE):
    import services.gitlab_api as gitlab_api
    import asyncio
    
    try:
        # 1. Tải song song pubspec.yaml và chi tiết branch
        file_task = gitlab_api.get_file_content(PROJECT_PATH, PUBSPEC_FILE_PATH, branch_name, timeout=8.0, max_attempts=2)
        branch_task = gitlab_api.get_branch_detail(PROJECT_PATH, branch_name, timeout=8.0, max_attempts=2)
        
        file_res, branch_res = await asyncio.gather(file_task, branch_task)
        
        # 2. Kiểm tra lỗi tải file pubspec.yaml
        if file_res.get("error"):
            text = build(
                bold(f"🌿 BRANCH: {branch_name.upper()}"),
                "",
                f"❌ {escape(file_res['error'])}",
                "",
                italic("Vui lòng thử lại bằng cách gõ /cicd_branch")
            )
            await _edit_message(query_or_msg, text, parse_mode=MODE)
            _clear_cicd_data(ctx)
            return ConversationHandler.END
            
        pubspec_content = file_res.get("content", "")
        current_version = parse_pubspec_version(pubspec_content) or "unknown"
        current_ref = parse_pubspec_ref(pubspec_content) or "unknown"
        
        ctx.user_data["cicd_pubspec_content"] = pubspec_content
        ctx.user_data["cicd_old_version"] = current_version
        ctx.user_data["cicd_old_ref"] = current_ref
        
        # Cấu hình mặc định bằng chính thông tin cũ của branch
        ctx.user_data["cicd_new_version"] = current_version
        ctx.user_data["cicd_new_ref"] = current_ref
        ctx.user_data["cicd_commit_msg"] = f"Build app version: {current_version}"
        
        # 3. Phân tích tin nhắn commit mới nhất từ kết quả tải branch detail
        commit_msg = "Không rõ"
        if not branch_res.get("error") and branch_res.get("branch"):
            b_data = branch_res.get("branch")
            commit_data = b_data.get("commit") or {}
            if isinstance(commit_data, dict):
                commit_msg = commit_data.get("message", "Không rõ").strip()
                commit_msg = commit_msg.split("\n")[0] # Chỉ lấy dòng tiêu đề chính
            
        ctx.user_data["cicd_last_commit"] = commit_msg
        
        await _send_preview(query_or_msg, ctx)
        return CONFIRM_OR_EDIT
        
    except Exception as e:
        logger.error(f"Lỗi khi tải thông tin branch {branch_name}: {e}", exc_info=True)
        text = build(
            bold(f"🌿 BRANCH: {branch_name.upper()}"),
            "",
            f"❌ Đã xảy ra lỗi hệ thống khi tải thông tin branch: {escape(str(e))}",
            "",
            italic("Vui lòng thử lại bằng cách gõ /cicd_branch")
        )
        await _edit_message(query_or_msg, text, parse_mode=MODE)
        _clear_cicd_data(ctx)
        return ConversationHandler.END


# ─── Preview Screen ───────────────────────────────────────────
def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Sửa Version", callback_data="cicd:edit_ver"),
            InlineKeyboardButton("✏️ Sửa Ref", callback_data="cicd:edit_ref"),
        ],
        [
            InlineKeyboardButton("✏️ Sửa Commit Msg", callback_data="cicd:edit_msg"),
        ],
        [
            InlineKeyboardButton("✅ Xác nhận & Chạy CICD", callback_data="cicd:confirm"),
        ],
        [
            InlineKeyboardButton("❌ Huỷ", callback_data="cicd:cancel"),
        ]
    ])


async def _send_preview(query_or_msg, ctx: ContextTypes.DEFAULT_TYPE):
    branch_name = ctx.user_data.get("cicd_target_branch")
    old_ver = ctx.user_data.get("cicd_old_version")
    old_ref = ctx.user_data.get("cicd_old_ref")
    new_ver = ctx.user_data.get("cicd_new_version")
    new_ref = ctx.user_data.get("cicd_new_ref")
    commit_msg = ctx.user_data.get("cicd_commit_msg")
    last_commit = ctx.user_data.get("cicd_last_commit", "Không rõ")
    
    text = build(
        bold(f"🌿 CẤU HÌNH CICD: {branch_name.upper()}"),
        "",
        f"💬 <b>Commit gần nhất của branch:</b>",
        f"<i>{escape(last_commit)}</i>",
        "",
        f"📦 <b>Version hiện tại (cũ):</b> {code(old_ver)}",
        f"🔗 <b>Ref hiện tại (cũ):</b> {code(old_ref)}",
        "",
        f"🆕 <b>Version sẽ cập nhật:</b> {bold(new_ver)}",
        f"🎯 <b>Ref sẽ cập nhật:</b> {bold(new_ref)}",
        f"📝 <b>Commit message đề xuất:</b> {code(commit_msg)}",
        "",
        italic("Chọn các chức năng chỉnh sửa hoặc xác nhận chạy ở nút bên dưới:")
    )
    
    await _edit_message(query_or_msg, text, _preview_keyboard(), MODE)


# ─── Conversation states: EDIT VERSION ───────────────────────
async def cb_edit_ver_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    await _edit_message(
        query,
        text=build(
            bold("✏️ CHỈNH SỬA VERSION"),
            "",
            f"Version hiện tại của branch là: {code(ctx.user_data.get('cicd_old_version'))}",
            "",
            escape("Nhập số version mới (VD: 1.2.2+28):")
        ),
        parse_mode=MODE
    )
    return EDIT_VERSION


async def handle_edit_version(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    
    if not val or any(c.isspace() for c in val):
        await update.effective_message.reply_text(
            text="❌ Version không hợp lệ (không chứa khoảng trắng). Vui lòng nhập lại:"
        )
        return EDIT_VERSION
        
    ctx.user_data["cicd_new_version"] = val
    
    # Cập nhật cả commit message nếu nó đang sử dụng định dạng mặc định của version cũ
    old_ver = ctx.user_data.get("cicd_old_version")
    if ctx.user_data.get("cicd_commit_msg") == f"Build app version: {old_ver}":
        ctx.user_data["cicd_commit_msg"] = f"Build app version: {val}"
        
    await _send_preview(update.effective_message, ctx)
    return CONFIRM_OR_EDIT


# ─── Conversation states: EDIT REF ───────────────────────────
async def cb_edit_ref_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    await _edit_message(
        query,
        text=build(
            bold("✏️ CHỈNH SỬA REF DEPENDENCY"),
            "",
            f"Ref hiện tại của branch là: {code(ctx.user_data.get('cicd_old_ref'))}",
            "",
            escape("Nhập tên ref mới mong muốn (như v1.1.5 hoặc tên branch):")
        ),
        parse_mode=MODE
    )
    return EDIT_REF


async def handle_edit_ref(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    
    if not val or any(c.isspace() for c in val):
        await update.effective_message.reply_text(
            text="❌ Ref không hợp lệ. Vui lòng nhập lại:"
        )
        return EDIT_REF
        
    ctx.user_data["cicd_new_ref"] = val
    await _send_preview(update.effective_message, ctx)
    return CONFIRM_OR_EDIT


# ─── Conversation states: EDIT COMMIT MSG ─────────────────────
async def cb_edit_msg_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    await _edit_message(
        query,
        text=build(
            bold("✏️ CHỈNH SỬA COMMIT MESSAGE"),
            "",
            escape("Nhập commit message mới:")
        ),
        parse_mode=MODE
    )
    return EDIT_COMMIT_MSG


async def handle_edit_commit_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    
    if not val:
        await update.effective_message.reply_text(
            text="❌ Commit message không được để trống. Vui lòng nhập lại:"
        )
        return EDIT_COMMIT_MSG
        
    ctx.user_data["cicd_commit_msg"] = val
    await _send_preview(update.effective_message, ctx)
    return CONFIRM_OR_EDIT


# ─── Conversation states: CONFIRM & RUN ──────────────────────
async def cb_confirm_cicd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    query = update.callback_query
    
    branch = ctx.user_data.get("cicd_target_branch")
    new_ver = ctx.user_data.get("cicd_new_version")
    new_ref = ctx.user_data.get("cicd_new_ref")
    commit_msg = ctx.user_data.get("cicd_commit_msg")
    pubspec_content = ctx.user_data.get("cicd_pubspec_content")
    
    await _edit_message(
        query,
        text=build(
            bold(f"🌿 RUNNING CICD: {branch.upper()}"),
            "",
            italic("⏳ Đang chuẩn bị sửa pubspec.yaml và commit thẳng lên GitLab...")
        ),
        parse_mode=MODE
    )
    
    # 1. Chỉnh sửa nội dung pubspec.yaml trong bộ nhớ
    modified_content = update_pubspec_content(pubspec_content, new_ver, new_ref)
    
    # 2. Gọi GitLab API để commit
    import services.gitlab_api as gitlab_api
    commit_res = await gitlab_api.update_file_content(
        project_path=PROJECT_PATH,
        file_path=PUBSPEC_FILE_PATH,
        branch=branch,
        content=modified_content,
        commit_message=commit_msg
    )
    
    if commit_res.get("error"):
        await _edit_message(
            query,
            text=build(
                bold(f"❌ THẤT BẠI: {branch.upper()}"),
                "",
                f"Không thể commit thay đổi lên GitLab. Lỗi:",
                code(escape(commit_res["error"])),
                "",
                italic("Vui lòng thử lại bằng cách gõ /cicd_branch")
            ),
            parse_mode=MODE
        )
    else:
        res_data = commit_res.get("result", {})
        commit_id = res_data.get("id", "N/A")
        short_id = commit_id[:8] if commit_id != "N/A" else "N/A"
        web_url = res_data.get("web_url", "")
        
        link_str = f"<a href='{web_url}'>{short_id}</a>" if web_url else short_id
        
        await _edit_message(
            query,
            text=build(
                bold(f"🎉 THÀNH CÔNG: {branch.upper()}"),
                "",
                f"✅ Đã cập nhật file <code>pubspec.yaml</code>:",
                f"   • Version mới: {bold(new_ver)}",
                f"   • Ref mới: {bold(new_ref)}",
                f"✅ Đã commit & push trực tiếp qua GitLab API thành công!",
                f"🆔 Commit ID: {link_str}",
                "",
                f"🚀 <b>GitLab CI/CD Pipeline</b> cho branch <code>{branch}</code> đã được tự động trigger!"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Quay lại danh sách branch", callback_data="cicd_br:start")]
            ]),
            parse_mode=MODE
        )
        
    _clear_cicd_data(ctx)
    return ConversationHandler.END


# ─── Cancel & Fallbacks ───────────────────────────────────────
async def conv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _clear_cicd_data(ctx)
    if update.effective_message:
        await update.effective_message.reply_text(
            escape("Đã huỷ cấu hình CICD branch."), parse_mode=MODE
        )
    return ConversationHandler.END


async def cb_conv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    _clear_cicd_data(ctx)
    await _edit_message(
        update.callback_query,
        text=escape("Đã huỷ cấu hình CICD branch."),
        parse_mode=MODE
    )
    return ConversationHandler.END


def _clear_cicd_data(ctx: ContextTypes.DEFAULT_TYPE):
    keys = [
        "cicd_target_branch",
        "cicd_pubspec_content",
        "cicd_old_version",
        "cicd_old_ref",
        "cicd_new_version",
        "cicd_new_ref",
        "cicd_commit_msg",
        "cicd_last_commit"
    ]
    for k in keys:
        ctx.user_data.pop(k, None)


# ─── Registration ─────────────────────────────────────────────
def register_cicd_branch_handlers(app: Application):
    cicd_conv = ConversationHandler(
        entry_points=[
            CommandHandler("cicd_branch", cmd_cicd_branch),
            CallbackQueryHandler(cmd_cicd_branch, pattern=r"^cicd_br:start$"),
        ],
        states={
            SELECT_BRANCH: [
                CallbackQueryHandler(cb_select_branch, pattern=r"^cicd_br:select:.*$"),
                CallbackQueryHandler(cb_fetch_all_branches, pattern=r"^cicd_br:fetch_all$"),
                CallbackQueryHandler(cb_input_custom_branch_start, pattern=r"^cicd_br:input_custom$"),
            ],
            INPUT_CUSTOM_BRANCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input_custom_branch),
            ],
            CONFIRM_OR_EDIT: [
                CallbackQueryHandler(cb_edit_ver_start, pattern=r"^cicd:edit_ver$"),
                CallbackQueryHandler(cb_edit_ref_start, pattern=r"^cicd:edit_ref$"),
                CallbackQueryHandler(cb_edit_msg_start, pattern=r"^cicd:edit_msg$"),
                CallbackQueryHandler(cb_confirm_cicd, pattern=r"^cicd:confirm$"),
            ],
            EDIT_VERSION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_version),
            ],
            EDIT_REF: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_ref),
            ],
            EDIT_COMMIT_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_commit_msg),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(cb_conv_cancel, pattern=r"^(cicd:cancel|cicd_br:cancel)$"),
        ],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(cicd_conv)
    logger.info("✅ Custom branch CICD handlers registered (/cicd_branch)")
