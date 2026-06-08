import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from config import ALLOWED_USER_IDS
from services.markdown import escape, bold, code, build, italic
from services.telegram_utils import send_message_safe, edit_message_safe
import services.docker_service as docker_service

logger = logging.getLogger(__name__)

def require_auth(fn):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            logger.warning(f"Unauthorized docker access attempt: {user_id}")
            return
        return await fn(update, context)
    return wrapper

def build_container_list_keyboard(containers):
    """Xây dựng bàn phím danh sách container."""
    keyboard = []
    # Thêm nút bấm cho từng container
    for c in containers:
        status_indicator = "🟢" if c["status"] == "running" else "🔴"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_indicator} {c['name']} ({c['id']})", 
                callback_data=f"docker:detail:{c['id']}"
            )
        ])
    
    # Nút làm mới
    keyboard.append([InlineKeyboardButton("🔄 Tải lại danh sách", callback_data="docker:list")])
    return InlineKeyboardMarkup(keyboard)

@require_auth
async def cmd_docker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh chính /docker liệt kê danh sách container."""
    chat_id = update.effective_chat.id
    
    try:
        containers = docker_service.list_containers()
        if not containers:
            await send_message_safe(
                context.bot, 
                chat_id, 
                "🐳 <b>Quản lý Docker Containers</b>\n\n⚠️ Không tìm thấy container nào hoặc lỗi kết nối Docker daemon.",
                parse_mode="HTML"
            )
            return
            
        text = build(
            f"🐳 {bold('Docker Container Dashboard')}",
            "",
            "Chọn một container bên dưới để điều khiển:",
        )
        
        reply_markup = build_container_list_keyboard(containers)
        await send_message_safe(
            context.bot, 
            chat_id, 
            text, 
            reply_markup=reply_markup, 
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Lỗi cmd_docker: {e}", exc_info=True)
        await send_message_safe(context.bot, chat_id, f"❌ Lỗi: {e}")

async def handle_docker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler xử lý các tương tác nút bấm của Docker."""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split(":")
    action = data_parts[1]
    container_id = data_parts[2] if len(data_parts) > 2 else None
    
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    try:
        if action == "list":
            # Hiển thị lại danh sách container
            containers = docker_service.list_containers()
            text = build(
                f"🐳 {bold('Docker Container Dashboard')}",
                "",
                "Chọn một container bên dưới để điều khiển:",
            )
            reply_markup = build_container_list_keyboard(containers)
            await edit_message_safe(context.bot, chat_id, message_id, text, reply_markup=reply_markup, parse_mode="HTML")
            
        elif action == "detail" and container_id:
            # Xem chi tiết container
            containers = docker_service.list_containers()
            container = next((c for c in containers if c["id"] == container_id), None)
            
            if not container:
                await edit_message_safe(
                    context.bot, 
                    chat_id, 
                    message_id, 
                    "❌ Không tìm thấy container hoặc container đã bị xóa.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="docker:list")]])
                )
                return
                
            status_indicator = "🟢 Đang chạy" if container["status"] == "running" else f"🔴 Đã dừng ({container['status']})"
            
            text = build(
                f"🐳 {bold('Chi tiết Container:')} {bold(container['name'])}",
                f"🆔 Short ID: {code(container['id'])}",
                f"📦 Image: {code(container['image'])}",
                f"⚡ Trạng thái: {status_indicator}",
                f"📅 Khởi tạo: {container['created']}",
                f"🔗 Cổng (Ports): {code(container['ports'])}",
                "",
                "Chọn hành động:"
            )
            
            # Xây dựng nút chức năng
            keyboard = []
            
            # Start / Stop tùy trạng thái
            control_row = []
            if container["status"] == "running":
                control_row.append(InlineKeyboardButton("⏸️ Stop", callback_data=f"docker:stop:{container_id}"))
            else:
                control_row.append(InlineKeyboardButton("▶️ Start", callback_data=f"docker:start:{container_id}"))
                
            control_row.append(InlineKeyboardButton("🔄 Restart", callback_data=f"docker:restart:{container_id}"))
            keyboard.append(control_row)
            
            # Logs / Redeploy
            keyboard.append([
                InlineKeyboardButton("📝 Logs", callback_data=f"docker:logs:{container_id}"),
                InlineKeyboardButton("🚀 Redeploy", callback_data=f"docker:redeploy:{container_id}")
            ])
            
            # Quay lại
            keyboard.append([InlineKeyboardButton("⬅️ Quay lại danh sách", callback_data="docker:list")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await edit_message_safe(context.bot, chat_id, message_id, text, reply_markup=reply_markup, parse_mode="HTML")
            
        elif action in ["start", "stop", "restart"] and container_id:
            # Thực thi start/stop/restart
            await edit_message_safe(context.bot, chat_id, message_id, f"⏳ Đang thực hiện <b>{action}</b> container {container_id}...", parse_mode="HTML")
            res = docker_service.manage_container(container_id, action)
            
            # Đợi 1 chút để container thay đổi trạng thái thực sự trước khi reload detail
            await asyncio.sleep(1)
            
            # Quay lại trang chi tiết
            # Ta giả lập query.data mới để gọi lại detail
            query.data = f"docker:detail:{container_id}"
            await handle_docker_callback(update, context)
            
        elif action == "logs" and container_id:
            # Lấy logs
            logs = docker_service.get_container_logs(container_id, tail=40)
            
            # Gửi tin nhắn mới thay vì ghi đè màn hình điều khiển
            log_title = f"📝 <b>Logs container: {container_id} (40 dòng cuối)</b>\n\n"
            log_body = f"<pre>{escape(logs[:3800])}</pre>" if logs.strip() else "<i>(Không có logs)</i>"
            
            keyboard = [[InlineKeyboardButton("🗑️ Đóng", callback_data="docker:closelogs")]]
            await query.message.reply_text(
                log_title + log_body,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif action == "redeploy" and container_id:
            # Hiển thị màn hình xác nhận redeploy
            containers = docker_service.list_containers()
            container = next((c for c in containers if c["id"] == container_id), None)
            name = container["name"] if container else container_id
            
            text = build(
                f"⚠️ {bold('Xác nhận Re-deploy container')}",
                "",
                f"Bạn có chắc chắn muốn re-deploy container {bold(name)}?",
                "Hệ thống sẽ kéo (pull) image mới nhất, dừng và xóa container cũ, sau đó tạo lại container với cấu hình tương tự.",
                "",
                f"{bold('Lưu ý:')} Container sẽ bị gián đoạn hoạt động trong vài giây."
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Đồng ý Redeploy", callback_data=f"docker:redeploy_confirm:{container_id}"),
                    InlineKeyboardButton("❌ Hủy bỏ", callback_data=f"docker:detail:{container_id}")
                ]
            ]
            await edit_message_safe(context.bot, chat_id, message_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            
        elif action == "redeploy_confirm" and container_id:
            # Thực thi redeploy
            await edit_message_safe(context.bot, chat_id, message_id, "⏳ Đang thực hiện kéo image mới và re-deploy container... Quá trình này có thể mất chút thời gian.", parse_mode="HTML")
            
            # Chạy trong executor để tránh blocking
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: docker_service.redeploy_container(container_id))
            
            if res.get("status") == "success":
                text = build(
                    f"✅ {bold('Re-deploy thành công!')}",
                    "",
                    res.get("message", ""),
                    f"ID mới: {code(res.get('new_id', ''))}"
                )
            else:
                text = build(
                    f"❌ {bold('Re-deploy thất bại!')}",
                    "",
                    f"Lỗi: {escape(res.get('error', ''))}"
                )
                
            keyboard = [[InlineKeyboardButton("⬅️ Quay lại chi tiết", callback_data=f"docker:detail:{container_id}")]]
            await edit_message_safe(context.bot, chat_id, message_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            
        elif action == "closelogs":
            # Xóa tin nhắn log
            await query.message.delete()
            
    except Exception as e:
        logger.error(f"Lỗi callback docker: {e}", exc_info=True)
        await send_message_safe(context.bot, chat_id, f"❌ Lỗi xử lý callback Docker: {e}")

def register_docker_handlers(app):
    """Đăng ký handlers với Telegram Application."""
    app.add_handler(CommandHandler("docker", cmd_docker))
    app.add_handler(CallbackQueryHandler(handle_docker_callback, pattern="^docker:"))
    logger.info("✅ Đã đăng ký Docker Controller handlers (/docker)")
