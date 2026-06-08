import logging
import io
import asyncio
import requests
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ChatAction

import config
from services.markdown import escape, bold, italic, code, build
from services.telegram_utils import send_message_safe, edit_message_safe, typing_action
import services.os_agent as os_agent

logger = logging.getLogger(__name__)

# Trạng thái chạy agent điều khiển tự động
_running_tasks = {}  # {chat_id: task_running_boolean}

def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if config.ALLOWED_USER_IDS and user_id not in config.ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized OS agent access attempt: {user_id}")
            return
        return await fn(update, context)
    return wrapper

@require_auth
async def cmd_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chụp ảnh màn hình máy Mac và gửi về Telegram."""
    chat_id = update.effective_chat.id
    msg = await send_message_safe(context.bot, chat_id, "📸 Đang chụp màn hình...")
    
    try:
        # Nhờ loop chạy blocking request trong executor
        loop = asyncio.get_event_loop()
        image = await loop.run_in_executor(None, os_agent.get_screenshot)
        
        # Chuyển Image sang bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        img_byte_arr.name = 'screenshot.png'
        
        await msg.delete()
        await update.effective_message.reply_photo(
            photo=img_byte_arr,
            caption=f"🖥️ Màn hình hiện tại ({image.width}x{image.height})"
        )
    except Exception as e:
        logger.error(f"Error in cmd_screen: {e}")
        await edit_message_safe(context.bot, chat_id, msg.message_id, f"❌ Lỗi khi chụp màn hình: {e}")

@require_auth
async def cmd_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chạy lệnh Terminal trên máy Mac."""
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    parts = text.split(None, 1)
    
    if len(parts) < 2:
        await send_message_safe(
            context.bot, 
            chat_id, 
            build(
                bold("Cú pháp:"),
                code("/cmd <lệnh_terminal>"),
                "",
                "Ví dụ: `/cmd ls -la` hoặc `/cmd df -h`"
            ),
            parse_mode="HTML"
        )
        return
        
    cmd_str = parts[1].strip()
    
    # Một số từ khóa nhạy cảm cần cảnh báo
    dangerous_keywords = ["rm ", "format", "shutdown", "reboot", "init ", "mkfs"]
    if any(k in cmd_str.lower() for k in dangerous_keywords):
        # Yêu cầu xác nhận hoặc cảnh báo cực mạnh
        await send_message_safe(
            context.bot,
            chat_id,
            f"⚠️ Lệnh chứa từ khóa nhạy cảm. Đang chạy trong 60 giây giới hạn..."
        )
        
    msg = await send_message_safe(context.bot, chat_id, f"⏳ Đang thực thi lệnh: <code>{escape(cmd_str)}</code>...", parse_mode="HTML")
    
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None, 
            lambda: os_agent.execute_helper_action("cmd", {"command": cmd_str})
        )
        
        stdout = res.get("stdout", "")
        stderr = res.get("stderr", "")
        status = res.get("status", "failed")
        code_val = res.get("returncode", -1)
        
        output_parts = []
        if stdout:
            output_parts.append(f"🟢 <b>STDOUT:</b>\n<pre>{escape(stdout[:3000])}</pre>")
        if stderr:
            output_parts.append(f"🔴 <b>STDERR:</b>\n<pre>{escape(stderr[:1000])}</pre>")
            
        if not output_parts:
            output_parts.append("<i>(Không có output)</i>")
            
        header = f"<b>Kết quả lệnh</b> (Status: {status}, Code: {code_val}):\n\n"
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            header + "\n\n".join(output_parts),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        await edit_message_safe(
            context.bot,
            chat_id,
            msg.message_id,
            f"❌ Thất bại: {e}"
        )

@require_auth
async def cmd_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khởi động Agent tự động hoàn thành một nhiệm vụ điều khiển."""
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    parts = text.split(None, 1)
    
    if len(parts) < 2:
        await send_message_safe(
            context.bot, 
            chat_id, 
            build(
                bold("🤖 Agent Điều Khiển Tự Động"),
                "",
                bold("Cú pháp:"),
                code("/control <nhiệm vụ>"),
                "",
                "Ví dụ: `/control mở Chrome và tìm kiếm tin tức AI`"
            ),
            parse_mode="HTML"
        )
        return
        
    task_instruction = parts[1].strip()
    
    if _running_tasks.get(chat_id):
        await send_message_safe(context.bot, chat_id, "⚠️ Hiện đang có một tác vụ Agent đang chạy. Vui lòng đợi hoặc dừng lại trước.")
        return
        
    _running_tasks[chat_id] = True
    
    status_msg = await send_message_safe(
        context.bot, 
        chat_id, 
        f"🚀 <b>Bắt đầu Agent</b>\nNhiệm vụ: <i>{escape(task_instruction)}</i>\n\nĐang chụp màn hình và phân tích...",
        parse_mode="HTML"
    )
    
    # Chạy Agent Loop trong một background task để tránh block Telegram polling
    asyncio.create_task(run_agent_loop(context.bot, chat_id, status_msg.message_id, task_instruction))

async def run_agent_loop(bot, chat_id, status_message_id, task_instruction):
    history = []
    max_steps = 10
    
    try:
        for step in range(1, max_steps + 1):
            if not _running_tasks.get(chat_id):
                await send_message_safe(bot, chat_id, "🛑 Agent đã bị dừng bởi người dùng.")
                break
                
            await edit_message_safe(
                bot, 
                chat_id, 
                status_message_id,
                f"🧠 <b>Bước {step}/{max_steps}</b>\nNhiệm vụ: <i>{escape(task_instruction)}</i>\n\nĐang gửi ảnh và bối cảnh lên Gemini...",
                parse_mode="HTML"
            )
            
            # Chạy bước agent
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: os_agent.run_os_agent_step(task_instruction, history)
            )
            
            action = result.get("action")
            thought = result.get("thought", "")
            step_desc = result.get("step_description", "")
            
            # Lưu lịch sử
            history.append(step_desc)
            
            # Gửi thông tin bước hiện tại
            log_text = build(
                f"🤖 <b>Bước {step}/{max_steps}</b>",
                f"💭 <b>Suy nghĩ:</b> <i>{escape(thought)}</i>",
                f"🎬 <b>Hành động:</b> <code>{escape(step_desc)}</code>",
                "",
                f"⌛ Chờ 3 giây để hệ thống phản hồi..."
            )
            
            await edit_message_safe(bot, chat_id, status_message_id, log_text, parse_mode="HTML")
            
            # Chờ để hệ thống thực thi và vẽ màn hình (3 giây)
            await asyncio.sleep(3)
            
            # Chụp màn hình cập nhật gửi cho user sau mỗi thao tác click/gõ quan trọng
            if action in ["click", "type", "press", "hotkey", "cmd", "applescript"]:
                try:
                    image = await loop.run_in_executor(None, os_agent.get_screenshot)
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)
                    img_byte_arr.name = f'step_{step}.png'
                    await send_message_safe(
                        bot,
                        chat_id,
                        f"📸 Kết quả sau <b>Bước {step}</b> ({escape(action)}):",
                        parse_mode="HTML"
                    )
                    await bot.send_photo(chat_id=chat_id, photo=img_byte_arr)
                except Exception as photo_err:
                    logger.error(f"Failed to send step photo: {photo_err}")
            
            # Kiểm tra trạng thái kết thúc
            if action == "done":
                await send_message_safe(
                    bot, 
                    chat_id, 
                    f"✅ <b>Nhiệm vụ hoàn thành!</b>\n\n{escape(step_desc)}",
                    parse_mode="HTML"
                )
                break
            elif action == "failed":
                await send_message_safe(
                    bot, 
                    chat_id, 
                    f"❌ <b>Agent báo cáo thất bại!</b>\nLý do: <i>{escape(step_desc)}</i>",
                    parse_mode="HTML"
                )
                break
                
        else:
            await send_message_safe(
                bot, 
                chat_id, 
                f"⚠️ <b>Hết số bước tối đa ({max_steps})!</b> Tác vụ chưa được hoàn thành hoàn toàn.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Error in run_agent_loop: {e}", exc_info=True)
        await send_message_safe(bot, chat_id, f"❌ Lỗi hệ thống trong Agent: {e}")
    finally:
        _running_tasks[chat_id] = False

@require_auth
async def cmd_stop_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dừng agent điều khiển tự động."""
    chat_id = update.effective_chat.id
    if _running_tasks.get(chat_id):
        _running_tasks[chat_id] = False
        await send_message_safe(context.bot, chat_id, "🛑 Đang gửi yêu cầu dừng Agent...")
    else:
        await send_message_safe(context.bot, chat_id, "ℹ️ Không có Agent nào đang hoạt động.")

@require_auth
async def cmd_manual_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mô phỏng thao tác click, type, press thủ công từ user."""
    chat_id = update.effective_chat.id
    text = update.effective_message.text
    parts = text.split(None, 1)
    
    if len(parts) < 2:
        await send_message_safe(
            context.bot,
            chat_id,
            build(
                bold("🎮 Thao tác điều khiển thủ công"),
                "",
                "/click <x> <y> — Click chuột",
                "/type <nội dung> — Nhập văn bản",
                "/press <phím> — Nhấn một phím (ví dụ: enter, space)",
                "/hotkey <phím1> <phím2> ... — Nhấn tổ hợp phím (ví dụ: command space)"
            ),
            parse_mode="HTML"
        )
        return
        
    cmd_name = parts[0].replace("/", "").lower()
    args_str = parts[1].strip()
    
    loop = asyncio.get_event_loop()
    
    try:
        if cmd_name == "click":
            coords = args_str.split()
            if len(coords) < 2:
                raise ValueError("Cần cung cấp cả x và y")
            x, y = int(coords[0]), int(coords[1])
            res = await loop.run_in_executor(None, lambda: os_agent.execute_helper_action("click", {"x": x, "y": y}))
            await send_message_safe(context.bot, chat_id, f"🖱️ Đã click chuột tại ({x}, {y})")
            
        elif cmd_name == "type":
            res = await loop.run_in_executor(None, lambda: os_agent.execute_helper_action("type", {"text": args_str}))
            await send_message_safe(context.bot, chat_id, f"⌨️ Đã gõ chữ: <code>{escape(args_str)}</code>", parse_mode="HTML")
            
        elif cmd_name == "press":
            res = await loop.run_in_executor(None, lambda: os_agent.execute_helper_action("press", {"key": args_str}))
            await send_message_safe(context.bot, chat_id, f"⌨️ Đã nhấn phím: {args_str}")
            
        elif cmd_name == "hotkey":
            keys = args_str.split()
            res = await loop.run_in_executor(None, lambda: os_agent.execute_helper_action("hotkey", {"keys": keys}))
            await send_message_safe(context.bot, chat_id, f"⌨️ Đã nhấn tổ hợp: {keys}")
            
        # Tự động gửi screenshot cập nhật sau thao tác thủ công
        await cmd_screen(update, context)
        
    except Exception as e:
        await send_message_safe(context.bot, chat_id, f"❌ Thao tác lỗi: {e}")

def register_computer_handlers(app):
    """Đăng ký handlers với Telegram Application."""
    app.add_handler(CommandHandler("screen", cmd_screen))
    app.add_handler(CommandHandler("cmd", cmd_run_command))
    app.add_handler(CommandHandler("control", cmd_control))
    app.add_handler(CommandHandler("stop", cmd_stop_agent))
    
    # Handlers thủ công
    app.add_handler(CommandHandler("click", cmd_manual_action))
    app.add_handler(CommandHandler("type", cmd_manual_action))
    app.add_handler(CommandHandler("press", cmd_manual_action))
    app.add_handler(CommandHandler("hotkey", cmd_manual_action))
    
    logger.info("✅ Đã đăng ký Computer/OS Control handlers (/screen, /cmd, /control...)")
