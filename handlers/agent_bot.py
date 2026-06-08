import os
import logging
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import config
from services.telegram_utils import send_message_safe, edit_message_safe, typing_action
from services.markdown import escape, bold, code, italic, pre, build, ai_to_mdv2

# Google Antigravity SDK
from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import hooks, policy

logger = logging.getLogger(__name__)

# Thư mục gốc chứa các repository trên máy Mac
SOURCE_CODE_ROOT = "/Users/macmini/SourceCode"

def require_auth(fn):
    """Decorator kiểm tra quyền truy cập whitelist."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized access attempt to Agent Bot from user_id: {user_id}")
            return
        return await fn(update, context)
    return wrapper

def get_repositories() -> list:
    """Quét các thư mục con trong /Users/macmini/SourceCode."""
    if not os.path.exists(SOURCE_CODE_ROOT):
        logger.error(f"Source root {SOURCE_CODE_ROOT} does not exist!")
        return []
    
    repos = []
    try:
        for item in os.listdir(SOURCE_CODE_ROOT):
            full_path = os.path.join(SOURCE_CODE_ROOT, item)
            if os.path.isdir(full_path) and not item.startswith('.'):
                repos.append(item)
    except Exception as e:
        logger.error(f"Error scanning source code directory: {e}")
    
    return sorted(repos)

# Lưu các task lập trình đang chạy để có thể abort
active_tasks = {}

# Lưu các agent đang chạy để nhớ context/history
active_agents = {}

# Lưu các yêu cầu phê duyệt công cụ đang chờ
pending_approvals = {}
approval_counter = 0

@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chào mừng người dùng và hướng dẫn sử dụng."""
    chat_id = update.effective_chat.id
    current_repo = context.user_data.get("active_repo", "AI.BotTelegram")
    interactive_mode = context.user_data.get("interactive_mode", False)
    mode_str = "Bật (Phê duyệt thủ công)" if interactive_mode else "Tắt (Tự động đồng ý)"
    
    await send_message_safe(
        bot=context.bot,
        chat_id=chat_id,
        text=build(
            "🤖 <b>Chào mừng bạn đến với Con Bot Ngu Ngốk AGENT!</b>",
            "",
            "Tôi là Coding Agent độc lập kết nối trực tiếp với <b>Google Antigravity SDK</b>.",
            f"📍 Repository đang chọn: <code>{escape(current_repo)}</code>",
            f"⚙️ Chế độ tương tác: <b>{mode_str}</b>",
            "",
            "<b>Các lệnh hỗ trợ:</b>",
            "• /repo hoặc /setrepo - Thay đổi repository làm việc",
            "• /code &lt;yêu cầu&gt; - Ra lệnh cho Agent thực hiện task",
            "• /abort - Hủy tác vụ Coding Agent đang chạy",
            "• /reset - Reset cuộc hội thoại (Xóa sạch context cũ để bắt đầu phiên mới)",
            "• /interactive - Bật/Tắt chế độ xác nhận thủ công từng công cụ",
            "• Chat trực tiếp - Tự động kích hoạt Agent xử lý.",
            "",
            "<i>(Mọi công cụ như Terminal Command sẽ tuân theo chế độ tương tác của bạn)</i>"
        ),
        parse_mode="HTML"
    )

@require_auth
async def cmd_repo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị danh sách Repo thông qua Inline Keyboard để người dùng chọn."""
    chat_id = update.effective_chat.id
    repos = get_repositories()
    
    if not repos:
        await send_message_safe(
            bot=context.bot,
            chat_id=chat_id,
            text=f"❌ Không tìm thấy thư mục con nào trong thư mục: <code>{escape(SOURCE_CODE_ROOT)}</code>."
        )
        return
        
    current_repo = context.user_data.get("active_repo", "AI.BotTelegram")
    
    keyboard = []
    # Tạo các hàng nút bấm cho các repo
    for repo in repos:
        prefix = "📍 " if repo == current_repo else ""
        keyboard.append([InlineKeyboardButton(f"{prefix}{repo}", callback_data=f"agent_repo:select:{repo}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await send_message_safe(
        bot=context.bot,
        chat_id=chat_id,
        text="📂 <b>Hãy chọn repository dự án bạn muốn thực hiện công việc:</b>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def cb_select_repo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback xử lý khi người dùng chọn nút repo."""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split(":")
    if len(data_parts) < 3:
        return
        
    selected_repo = data_parts[2]
    context.user_data["active_repo"] = selected_repo
    
    # Cập nhật lại giao diện nút bấm
    repos = get_repositories()
    keyboard = []
    for repo in repos:
        prefix = "📍 " if repo == selected_repo else ""
        keyboard.append([InlineKeyboardButton(f"{prefix}{repo}", callback_data=f"agent_repo:select:{repo}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        text=build(
            f"✅ Đã chọn làm việc tại repository: <code>/Users/macmini/SourceCode/{escape(selected_repo)}</code>",
            "",
            "Bây giờ bạn có thể chat trực tiếp yêu cầu lập trình hoặc dùng lệnh /code."
        ),
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def run_coding_agent(user_prompt: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khởi tạo hoặc tái sử dụng Google Antigravity Agent và xử lý yêu cầu."""
    chat_id = update.effective_chat.id
    bot = context.bot
    
    # Hủy tác vụ cũ nếu đang chạy ở chat này
    if chat_id in active_tasks:
        old_task = active_tasks[chat_id]
        if not old_task.done():
            old_task.cancel()
            await asyncio.sleep(0.5) # Chờ task cũ dừng
            
    active_tasks[chat_id] = asyncio.current_task()
    
    # Lấy repo được chọn
    selected_repo = context.user_data.get("active_repo", "AI.BotTelegram")
    repo_path = os.path.join(SOURCE_CODE_ROOT, selected_repo)
    
    # Verify lại folder tồn tại
    if not os.path.exists(repo_path):
        await send_message_safe(
            bot=bot,
            chat_id=chat_id,
            text=f"❌ Lỗi: Thư mục <code>{escape(repo_path)}</code> không tồn tại. Vui lòng chọn lại repo bằng lệnh /repo."
        )
        active_tasks.pop(chat_id, None)
        return
        
    status_lines = [
        f"🚀 <b>Đang kết nối tới Coding Agent...</b>",
        f"📍 Workspace: <code>{escape(repo_path)}</code>",
        f"🤖 Model: <code>gemini-2.5-flash</code>",
        f"⏳ Đang chuẩn bị phiên làm việc...",
        ""
    ]
    
    status_msg = await send_message_safe(
        bot=bot,
        chat_id=chat_id,
        text="\n".join(status_lines),
        parse_mode="HTML"
    )
    
    if not status_msg:
        active_tasks.pop(chat_id, None)
        return

    # Lock cập nhật Telegram để tránh rate limits (throttle 1 giây)
    last_update_time = [0]
    update_lock = asyncio.Lock()
    
    async def update_telegram():
        async with update_lock:
            now = asyncio.get_event_loop().time()
            if now - last_update_time[0] < 1.0:
                return
            
            try:
                full_text = "\n".join(status_lines)
                if len(full_text) > 4000:
                    header = status_lines[0]
                    body = "\n".join(status_lines[1:])
                    body = body[-3800:]
                    full_text = f"{header}\n...[cắt bớt log cũ]...\n{body}"
                
                await edit_message_safe(bot, chat_id, status_msg.message_id, full_text, parse_mode="HTML")
                last_update_time[0] = now
            except Exception as e:
                logger.warning(f"Error editing status message on Telegram: {e}")

    # Lấy hoặc tạo Agent
    if config.USE_LOCAL_OPENCODE:
        status_lines[2] = f"🤖 Model: <code>OpenCode Local Server</code>"
        status_lines[3] = f"⏳ Đang kết nối tới OpenCode server..."
        await update_telegram()
        
        from services.opencode_service import OpenCodeService
        opencode_service = OpenCodeService(config.OPENCODE_LOCAL_URL)
        
        session_dir = "./data/agent_sessions"
        os.makedirs(session_dir, exist_ok=True)
        map_file = os.path.join(session_dir, "session_map.json")
        session_map = {}
        if os.path.exists(map_file):
            try:
                with open(map_file, "r") as f:
                    session_map = json.load(f)
            except Exception as e:
                logger.error(f"Error reading session map: {e}")
                
        session_key = f"{chat_id}_{selected_repo}_opencode"
        conversation_id = session_map.get(session_key)
        
        if not conversation_id:
            status_lines[3] = "⏳ Đang tạo OpenCode session mới..."
            await update_telegram()
            conversation_id = await opencode_service.create_session(f"Telegram {chat_id} - {selected_repo}")
            if not conversation_id:
                status_lines.append("❌ Không thể tạo Session trên OpenCode Server.")
                await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
                active_tasks.pop(chat_id, None)
                return
            
            session_map[session_key] = conversation_id
            try:
                with open(map_file, "w") as f:
                    json.dump(session_map, f)
            except Exception as e:
                logger.error(f"Error saving session map: {e}")
            status_lines[3] = "✅ Đã kết nối OpenCode session mới!"
        else:
            status_lines[3] = "✅ Đã tái sử dụng OpenCode session hiện tại!"
            
        await update_telegram()
        
        status_lines.append("🤔 <b>OpenCode Agent:</b> Đang phân tích và xử lý...")
        await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
        
        response_text = ""
        try:
            async for chunk in opencode_service.send_message_stream(conversation_id, user_prompt):
                response_text += chunk
                status_lines[-1] = f"🤔 <b>OpenCode Agent:</b>\n{ai_to_mdv2(response_text)}"
                await update_telegram()
                
            status_lines[-1] = f"🏁 <b>OpenCode Agent đã xử lý xong:</b>\n{ai_to_mdv2(response_text)}"
            try:
                full_text = "\n".join(status_lines)
                if len(full_text) > 4000:
                    header = status_lines[0]
                    body = "\n".join(status_lines[1:])
                    body = body[-3800:]
                    full_text = f"{header}\n...[cắt bớt log cũ]...\n{body}"
                await edit_message_safe(bot, chat_id, status_msg.message_id, full_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Final edit failed: {e}")
                await send_message_safe(bot, chat_id, ai_to_mdv2(response_text), parse_mode="HTML")
        except asyncio.CancelledError:
            logger.info(f"Task coding agent OpenCode for chat {chat_id} was cancelled.")
            status_lines.append("🛑 <b>Tác vụ đã bị dừng bởi người dùng.</b>")
            try:
                await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
            except Exception:
                pass
        except Exception as err:
            logger.error(f"System error executing OpenCode agent: {err}", exc_info=True)
            status_lines.append(f"💥 <b>Gặp lỗi hệ thống:</b> <code>{escape(str(err))}</code>")
            try:
                await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
            except Exception:
                pass
        finally:
            active_tasks.pop(chat_id, None)
        return

    agent = active_agents.get(chat_id)
    if not agent or getattr(agent, "repo_path", "") != repo_path:

        if agent:
            try:
                await agent.__aexit__(None, None, None)
            except Exception:
                pass
            active_agents.pop(chat_id, None)
            
        status_lines[3] = "⏳ Đang khởi tạo Agent session mới..."
        await update_telegram()
        
        # Đường dẫn lưu session
        session_dir = "./data/agent_sessions"
        os.makedirs(session_dir, exist_ok=True)
        
        # Load map từ file json
        map_file = os.path.join(session_dir, "session_map.json")
        session_map = {}
        if os.path.exists(map_file):
            try:
                with open(map_file, "r") as f:
                    session_map = json.load(f)
            except Exception as e:
                logger.error(f"Error reading session map: {e}")
                
        session_key = f"{chat_id}_{selected_repo}"
        conversation_id = session_map.get(session_key)
        
        # Cấu hình Agent mới
        config_agent = LocalAgentConfig(
            workspaces=[repo_path],
            policies=[policy.allow_all()],
            model="gemini-2.5-flash",
            api_key=config.GEMINI_API_KEY,
            save_dir=session_dir,
            conversation_id=conversation_id
        )
        agent = Agent(config=config_agent)
        agent.repo_path = repo_path
        agent.session_key = session_key
        agent.map_file = map_file
        agent.session_map = session_map
        
        # Định nghĩa các hook động sử dụng context động từ agent.chat_ctx
        @hooks.pre_tool_call_decide
        async def agent_pre_tool(data: types.ToolCall) -> types.HookResult:
            ctx = getattr(agent, "chat_ctx", {})
            if not ctx:
                return types.HookResult(allow=True)
                
            args_str = str(data.args)[:1000]
            interactive_mode = ctx["context"].user_data.get("interactive_mode", False)
            
            if interactive_mode:
                global approval_counter
                approval_counter += 1
                callback_id = f"appr_{approval_counter}"
                
                loop = asyncio.get_running_loop()
                fut = loop.create_future()
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Cho phép (Approve)", callback_data=f"agent_tool:approve:{callback_id}"),
                        InlineKeyboardButton("❌ Từ chối (Deny)", callback_data=f"agent_tool:deny:{callback_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                msg = await send_message_safe(
                    bot=ctx["bot"],
                    chat_id=ctx["chat_id"],
                    text=build(
                        f"⚠️ <b>Yêu cầu phê duyệt công cụ:</b> <code>{escape(data.name)}</code>",
                        f"📝 Arguments:",
                        f"<code>{escape(args_str)}</code>",
                        "",
                        "<i>Chọn Cho phép hoặc Từ chối để tiếp tục. Hết hạn sau 60 giây.</i>"
                    ),
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                
                if not msg:
                    return types.HookResult(allow=False)
                    
                pending_approvals[callback_id] = {
                    "future": fut,
                    "chat_id": ctx["chat_id"],
                    "message_id": msg.message_id,
                    "tool_name": data.name
                }
                
                try:
                    allowed = await asyncio.wait_for(fut, timeout=60.0)
                except asyncio.TimeoutError:
                    allowed = False
                    pending_approvals.pop(callback_id, None)
                    await edit_message_safe(
                        bot=ctx["bot"],
                        chat_id=ctx["chat_id"],
                        message_id=msg.message_id,
                        text=f"⏰ <b>Yêu cầu phê duyệt công cụ <code>{escape(data.name)}</code> đã hết hạn (Tự động từ chối).</b>",
                        parse_mode="HTML"
                    )
                    
                ctx["status_lines"].append(f"⚙️ <b>Gọi Tool (Interactive):</b> <code>{escape(data.name)}</code> - " + ("✅ Được cho phép" if allowed else "❌ Bị từ chối"))
                await ctx["update_telegram"]()
                return types.HookResult(allow=allowed)
            else:
                ctx["status_lines"].append(f"⚙️ <b>Gọi Tool:</b> <code>{escape(data.name)}</code>\nArguments: <code>{escape(args_str[:150])}</code>")
                await ctx["update_telegram"]()
                return types.HookResult(allow=True)

        @hooks.post_tool_call
        async def agent_post_tool(data):
            ctx = getattr(agent, "chat_ctx", {})
            if ctx:
                ctx["status_lines"].append(f"✅ <b>Tool hoàn tất.</b>")
                await ctx["update_telegram"]()

        @hooks.on_tool_error
        async def agent_tool_error(data: Exception):
            ctx = getattr(agent, "chat_ctx", {})
            if ctx:
                ctx["status_lines"].append(f"❌ <b>Lỗi Tool:</b> <code>{escape(str(data))}</code>")
                await ctx["update_telegram"]()
            return None

        @hooks.pre_turn
        async def agent_pre_turn(data: str) -> types.HookResult:
            ctx = getattr(agent, "chat_ctx", {})
            if ctx:
                ctx["status_lines"].append(f"🤔 <b>Agent:</b> Đang phân tích và xử lý...")
                await ctx["update_telegram"]()
            return types.HookResult(allow=True)

        agent.register_hook(agent_pre_turn)
        agent.register_hook(agent_pre_tool)
        agent.register_hook(agent_post_tool)
        agent.register_hook(agent_tool_error)
        
        await agent.__aenter__()
        active_agents[chat_id] = agent
        
        # Lưu conversation_id mới
        new_conv_id = agent.conversation_id
        if new_conv_id and getattr(agent, "session_key", None):
            agent.session_map[agent.session_key] = new_conv_id
            try:
                with open(agent.map_file, "w") as f:
                    json.dump(agent.session_map, f)
            except Exception as e:
                logger.error(f"Error saving session map: {e}")
                
        status_lines[3] = "✅ Đã kết nối Agent session mới!"
        await update_telegram()
    else:
        status_lines[3] = "✅ Đã tái sử dụng Agent session hiện tại (Nhớ context)!"
        await update_telegram()

    # Thiết lập context động cho các hook truy cập
    agent.chat_ctx = {
        "bot": bot,
        "chat_id": chat_id,
        "context": context,
        "status_lines": status_lines,
        "status_msg": status_msg,
        "update_telegram": update_telegram
    }
    
    try:
        response = await agent.chat(user_prompt)
        final_text = await response.text()
        
        status_lines.append("")
        status_lines.append(f"🏁 <b>Agent đã xử lý xong:</b>")
        status_lines.append(ai_to_mdv2(final_text))
        
        try:
            full_text = "\n".join(status_lines)
            await edit_message_safe(bot, chat_id, status_msg.message_id, full_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Final edit failed: {e}")
            await send_message_safe(bot, chat_id, ai_to_mdv2(final_text), parse_mode="HTML")
            
    except asyncio.CancelledError:
        logger.info(f"Task coding agent for chat {chat_id} was cancelled.")
        status_lines.append("")
        status_lines.append("🛑 <b>Tác vụ đã bị dừng bởi người dùng.</b>")
        try:
            await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
        except Exception:
            pass
        # Nếu task bị hủy (abort), đóng luôn agent để khởi động lại sạch sẽ
        if chat_id in active_agents:
            a = active_agents.pop(chat_id)
            try:
                await a.__aexit__(None, None, None)
            except Exception:
                pass
                
    except Exception as err:
        logger.error(f"System error executing agent: {err}", exc_info=True)
        status_lines.append("")
        status_lines.append(f"💥 <b>Gặp lỗi hệ thống:</b> <code>{escape(str(err))}</code>")
        try:
            await edit_message_safe(bot, chat_id, status_msg.message_id, "\n".join(status_lines), parse_mode="HTML")
        except Exception:
            pass
        # Gặp lỗi hệ thống, đóng agent
        if chat_id in active_agents:
            a = active_agents.pop(chat_id)
            try:
                await a.__aexit__(None, None, None)
            except Exception:
                pass
                
    finally:
        active_tasks.pop(chat_id, None)
        # Hủy các pending approvals của chat này
        for cb_id, app_info in list(pending_approvals.items()):
            if app_info["chat_id"] == chat_id:
                fut = app_info["future"]
                if not fut.done():
                    fut.set_result(False)
                pending_approvals.pop(cb_id, None)

@require_auth
async def cmd_abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /abort để dừng Coding Agent đang chạy."""
    chat_id = update.effective_chat.id
    task = active_tasks.get(chat_id)
    if task and not task.done():
        task.cancel()
        await send_message_safe(
            bot=context.bot,
            chat_id=chat_id,
            text="🛑 <b>Đã phát lệnh dừng Coding Agent đang chạy.</b>",
            parse_mode="HTML"
        )
    else:
        await send_message_safe(
            bot=context.bot,
            chat_id=chat_id,
            text="ℹ️ Không có tác vụ Coding Agent nào đang chạy.",
            parse_mode="HTML"
        )

@require_auth
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /reset để xóa lịch sử/context và khởi động phiên Agent mới."""
    chat_id = update.effective_chat.id
    selected_repo = context.user_data.get("active_repo", "AI.BotTelegram")
    
    agent = active_agents.pop(chat_id, None)
    if agent:
        try:
            await agent.__aexit__(None, None, None)
        except Exception:
            pass
            
    # Xóa khỏi session_map.json
    session_dir = "./data/agent_sessions"
    map_file = os.path.join(session_dir, "session_map.json")
    removed = False
    if os.path.exists(map_file):
        try:
            with open(map_file, "r") as f:
                session_map = json.load(f)
            session_key = f"{chat_id}_{selected_repo}"
            session_key_opencode = f"{chat_id}_{selected_repo}_opencode"
            
            if session_key in session_map or session_key_opencode in session_map:
                session_map.pop(session_key, None)
                session_map.pop(session_key_opencode, None)
                with open(map_file, "w") as f:
                    json.dump(session_map, f)
                removed = True
        except Exception as e:
            logger.error(f"Error resetting session map: {e}")

            
    if agent or removed:
        await send_message_safe(
            bot=context.bot,
            chat_id=chat_id,
            text=build(
                "🔄 <b>Đã reset cuộc hội thoại.</b>",
                "Phiên Coding Agent tiếp theo của bạn tại repo này sẽ bắt đầu mới hoàn toàn (đã xóa sạch context/history cũ)."
            ),
            parse_mode="HTML"
        )
    else:
        await send_message_safe(
            bot=context.bot,
            chat_id=chat_id,
            text="ℹ️ Hiện không có phiên Agent hoạt động nào để reset.",
            parse_mode="HTML"
        )

@require_auth
async def cmd_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /interactive để Bật/Tắt chế độ xác nhận thủ công từng công cụ."""
    chat_id = update.effective_chat.id
    current_mode = context.user_data.get("interactive_mode", False)
    new_mode = not current_mode
    context.user_data["interactive_mode"] = new_mode
    
    mode_str = "<b>Bật (Kích hoạt chế độ phê duyệt thủ công từng công cụ)</b>" if new_mode else "<b>Tắt (Tự động đồng ý mọi công cụ)</b>"
    
    await send_message_safe(
        bot=context.bot,
        chat_id=chat_id,
        text=f"⚙️ Chế độ tương tác: {mode_str}",
        parse_mode="HTML"
    )

async def cb_tool_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback xử lý khi người dùng chọn Approve / Deny công cụ."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    if len(parts) < 3:
        return
        
    action = parts[1]
    callback_id = parts[2]
    
    approval = pending_approvals.pop(callback_id, None)
    if not approval:
        await query.edit_message_text("❌ Yêu cầu phê duyệt này không còn tồn tại hoặc đã hết hạn.")
        return
        
    fut = approval["future"]
    tool_name = approval["tool_name"]
    
    if action == "approve":
        if not fut.done():
            fut.set_result(True)
        await query.edit_message_text(
            f"✅ <b>Đã đồng ý chạy công cụ:</b> <code>{escape(tool_name)}</code>",
            parse_mode="HTML"
        )
    else:
        if not fut.done():
            fut.set_result(False)
        await query.edit_message_text(
            f"❌ <b>Đã từ chối chạy công cụ:</b> <code>{escape(tool_name)}</code>",
            parse_mode="HTML"
        )



@require_auth
async def cmd_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /code để kích hoạt Agent."""
    user_prompt = " ".join(context.args) if context.args else ""
    if not user_prompt:
        # Nếu có tin nhắn reply, lấy nội dung reply làm prompt
        reply = update.effective_message.reply_to_message
        if reply and (reply.text or reply.caption):
            user_prompt = reply.text or reply.caption
            
    if not user_prompt:
        await send_message_safe(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            text=build(
                "❌ <b>Thiếu nội dung yêu cầu!</b>",
                "Cú pháp: <code>/code &lt;yêu cầu lập trình&gt;</code>",
                "Hoặc reply tin nhắn của bạn và gõ <code>/code</code>"
            ),
            parse_mode="HTML"
        )
        return
        
    asyncio.create_task(run_coding_agent(user_prompt, update, context))

@require_auth
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý tin nhắn text thông thường (nếu không phải câu lệnh) để chạy Agent luôn."""
    user_prompt = update.effective_message.text.strip()
    if not user_prompt:
        return
        
    if user_prompt.startswith('/'):
        return
        
    asyncio.create_task(run_coding_agent(user_prompt, update, context))

def register_agent_bot_handlers(app):
    """Đăng ký các Handler cho Bot Agent."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("repo", cmd_repo))
    app.add_handler(CommandHandler("setrepo", cmd_repo))
    app.add_handler(CommandHandler("code", cmd_code))
    app.add_handler(CommandHandler("abort", cmd_abort))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("interactive", cmd_interactive))
    
    app.add_handler(CallbackQueryHandler(cb_select_repo, pattern="^agent_repo:select:"))
    app.add_handler(CallbackQueryHandler(cb_tool_approval, pattern="^agent_tool:(approve|deny):"))
    
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_text_message))
    
    logger.info("✅ Đã đăng ký Agent Bot handlers (/help, /repo, /code, /abort, /reset, /interactive...)")
