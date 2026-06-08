import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import config
from services.markdown import escape, bold, code, build, italic, ai_to_mdv2
from services.telegram_utils import send_message_safe, edit_message_safe, typing_action
from services.gitlab_api import get_user_projects, search_remote_repository
from services.code_search import get_local_path_for_project, search_local_repository, analyze_api_with_gemini
from handlers.commands import require_auth, _send_report_safe

logger = logging.getLogger(__name__)

# State lưu trữ trạng thái của người dùng
# Format: {user_id: {"project_id": int, "name": str, "local_path": str, "mode": "local"|"remote"}}
_code_search_states = {}

# Cache lưu trữ danh sách dự án GitLab tạm thời để tránh gọi API nhiều lần
# Format: {project_id: {"name": str, "path_with_namespace": str, "web_url": str}}
_projects_cache = {}


@require_auth
@typing_action
async def cmd_search_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Điểm kích hoạt tra cứu API: Lấy danh sách dự án từ SCM GitLab và hiển thị menu.
    """
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Reset trạng thái cũ nếu có
    if user_id in _code_search_states:
        del _code_search_states[user_id]

    msg = await send_message_safe(
        context.bot,
        chat_id,
        "🦊 Đang kết nối SCM GitLab để lấy danh sách dự án của bạn...",
        parse_mode="HTML"
    )

    # 1. Gọi API GitLab lấy dự án
    projects = await get_user_projects(limit=30)
    
    if not projects:
        # Nếu không có dự án nào từ GitLab, thử quét trực tiếp folder cục bộ để fallback
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            "⚠️ Không tìm thấy dự án nào từ SCM GitLab (hoặc chưa cấu hình GITLAB_PAT).\n"
            "Bot sẽ quét trực tiếp thư mục code cục bộ của bạn...",
            parse_mode="HTML"
        )
        
        # Quét các folder trong /Users/macmini/SourceCode
        import os
        from services.code_search import REPOS_ROOT_DIR
        local_projects = []
        try:
            if os.path.exists(REPOS_ROOT_DIR):
                for entry in os.scandir(REPOS_ROOT_DIR):
                    if entry.is_dir() and not entry.name.startswith("."):
                        local_projects.append({
                            "id": abs(hash(entry.name)) % 10000000, # Giả lập ID
                            "name": entry.name,
                            "path_with_namespace": f"local/{entry.name}",
                            "path": entry.name
                        })
            projects = local_projects
        except Exception as e:
            logger.error(f"Error scanning fallback folder: {e}")
            
    if not projects:
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            "❌ Không tìm thấy repository nào khả dụng trên cả SCM GitLab lẫn thư mục cục bộ.",
            parse_mode="HTML"
        )
        return

    # 2. Lưu vào Cache để Callback Query tìm kiếm thông tin nhanh
    for p in projects:
        _projects_cache[p["id"]] = p

    # 3. Tạo nút bấm Inline Keyboard chọn dự án
    # Sắp xếp nút bấm dạng grid (tối đa 2 nút 1 dòng)
    keyboard = []
    row = []
    for p in projects:
        btn = InlineKeyboardButton(p["name"], callback_data=f"cs:sel:{p['id']}")
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = build(
        f"🤖 {bold('AI SCM & Codebase API Explorer')}",
        "",
        escape("Hãy chọn dự án (Repository) mà bạn muốn tra cứu API & kiểm tra tham số bên dưới:")
    )

    await edit_message_safe(
        context.bot,
        chat_id,
        msg.message_id,
        text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def handle_code_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Xử lý khi người dùng chọn dự án từ menu nút bấm.
    """
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = query.data

    if not data.startswith("cs:sel:"):
        return

    try:
        project_id = int(data.split(":")[-1])
    except Exception:
        await send_message_safe(context.bot, chat_id, "❌ Lỗi định dạng callback.", parse_mode="HTML")
        return

    project_data = _projects_cache.get(project_id)
    if not project_data:
        await send_message_safe(
            context.bot,
            chat_id,
            "⚠️ Phiên làm việc đã hết hạn. Vui lòng chạy lại lệnh /search_code.",
            parse_mode="HTML"
        )
        return

    project_name = project_data["name"]
    path_with_namespace = project_data["path_with_namespace"]

    # Kiểm tra xem đã được clone cục bộ chưa
    local_path = get_local_path_for_project(path_with_namespace)
    
    if local_path:
        # Chế độ Cục bộ (Local Mode)
        _code_search_states[user_id] = {
            "project_id": project_id,
            "name": project_name,
            "local_path": local_path,
            "mode": "local"
        }
        
        mode_text = build(
            f"🔍 {bold('Chế độ: Cục bộ (Local Mode)')}",
            f"📍 Dự án: {escape(project_name)}",
            f"📁 Thư mục: {code(local_path)}",
            "",
            italic("👉 Dự án đã được ánh xạ cục bộ thành công! Bạn có thể tra cứu những đoạn code mới nhất đang chỉnh sửa chưa commit.")
        )
    else:
        # Chế độ SCM Từ xa (Remote SCM Mode)
        _code_search_states[user_id] = {
            "project_id": project_id,
            "name": project_name,
            "local_path": "",
            "mode": "remote"
        }
        
        mode_text = build(
            f"🌐 {bold('Chế độ: SCM Remote (GitLab)')}",
            f"📍 Dự án: {escape(project_name)}",
            f"🔗 Đường dẫn: {escape(path_with_namespace)}",
            "",
            italic("👉 Dự án chưa được clone về máy. Bot sẽ tìm kiếm trực tiếp trên SCM thông qua API của GitLab.")
        )

    prompt_text = build(
        mode_text,
        "",
        "💬 **Hãy gõ từ khóa API hoặc tên hàm/tham số cần tra cứu:**",
        "*(Ví dụ: `login`, `getUserInfo`, `api/v1/auth/register`, hoặc tên tham số để kiểm tra xem có khả dụng không)*"
    )

    # Thêm nút bấm quay lại danh sách repo
    keyboard = [[InlineKeyboardButton("⬅️ Quay lại danh sách Repo", callback_data="cs:back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await edit_message_safe(
        context.bot,
        chat_id,
        query.message.message_id,
        prompt_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def handle_code_search_callback_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Quay lại danh sách Repo.
    """
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id in _code_search_states:
        del _code_search_states[user_id]
        
    await cmd_search_code(update, context)


@require_auth
async def handle_code_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Xử lý text input chứa từ khóa tìm kiếm API của người dùng.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Chỉ xử lý nếu user đang ở trong state tra cứu
    state = _code_search_states.get(user_id)
    if not state:
        return

    keyword = update.message.text.strip()
    if not keyword:
        await send_message_safe(context.bot, chat_id, "⚠️ Vui lòng nhập từ khóa tìm kiếm.", parse_mode="HTML")
        return

    project_name = state["name"]
    project_id = state["project_id"]
    mode = state["mode"]
    local_path = state["local_path"]

    msg = await send_message_safe(
        context.bot,
        chat_id,
        f"🔍 Đang tìm kiếm từ khóa `{escape(keyword)}` trong repo `{escape(project_name)}`...",
        parse_mode="HTML"
    )

    results = []

    # 1. Thực thi tìm kiếm tùy theo Chế độ (Local/Remote)
    if mode == "local":
        results = search_local_repository(local_path, keyword)
        if not results:
            logger.info("Không tìm thấy code cục bộ, thử fallback sang tìm kiếm SCM Remote...")
            results = await search_remote_repository(project_id, keyword)
    else:
        results = await search_remote_repository(project_id, keyword)

    # 2. Xử lý kết quả tìm kiếm
    if not results:
        back_kb = [[InlineKeyboardButton("⬅️ Chọn Repo khác", callback_data="cs:back")]]
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            f"❌ Không tìm thấy bất kỳ file code hoặc API nào khớp với từ khóa `{escape(keyword)}` trong dự án `{escape(project_name)}`.\n\n"
            "Vui lòng thử lại với từ khóa khác hoặc bấm nút dưới để đổi dự án:",
            reply_markup=InlineKeyboardMarkup(back_kb),
            parse_mode="HTML"
        )
        return

    # Cập nhật trạng thái hiển thị loading AI
    await edit_message_safe(
        context.bot,
        chat_id,
        msg.message_id,
        f"🤖 Đã tìm thấy {len(results)} file code liên quan.\n"
        "Đang nhờ Gemini phân tích cú pháp, lập tài liệu API và đối chiếu tham số cho bạn...",
        parse_mode="HTML"
    )

    # 3. Gọi AI phân tích
    try:
        report = analyze_api_with_gemini(project_name, keyword, results)
        
        # 4. Gửi báo cáo an toàn và trực quan (hỗ trợ Webview/Telegraph)
        caption = f"Tra cứu API: {project_name} - {keyword}"
        await _send_report_safe(
            update=update,
            ctx=context,
            msg=msg,
            report=report,
            file_prefix="api_search",
            caption=caption
        )
        
        # Gửi thêm tin nhắn gợi ý tương tác tiếp theo
        back_kb = [
            [
                InlineKeyboardButton("🔍 Tìm kiếm tiếp trong repo này", callback_data=f"cs:sel:{project_id}"),
                InlineKeyboardButton("⬅️ Đổi Repo khác", callback_data="cs:back")
            ]
        ]
        await send_message_safe(
            context.bot,
            chat_id,
            italic("💡 Bạn có thể tiếp tục gõ từ khóa khác để tra cứu tiếp, hoặc bấm nút dưới để thay đổi tùy chọn:"),
            reply_markup=InlineKeyboardMarkup(back_kb),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error analyzing and sending code search report: {e}", exc_info=True)
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            f"❌ Đã xảy ra lỗi trong quá trình phân tích AI: {escape(str(e))}",
            parse_mode="HTML"
        )


def register_code_search_handlers(app):
    """Đăng ký các handlers vào PTB Application."""
    app.add_handler(CommandHandler("search_code", cmd_search_code))
    app.add_handler(CommandHandler("search_api", cmd_search_code))
    app.add_handler(CallbackQueryHandler(handle_code_search_callback_back, pattern="^cs:back$"))
    app.add_handler(CallbackQueryHandler(handle_code_search_callback, pattern="^cs:sel:"))
    # Handler nhận tin nhắn từ khóa (chỉ xử lý khi user có state trong _code_search_states)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code_search_input), group=1)
