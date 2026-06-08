"""
handlers/build.py

Tính năng /build-version:
  /build-version          → danh sách app dạng inline button
  Bấm app                 → hiển thị bảng build đẹp + nút quản lý
  Bấm ✏️ Sửa build       → ConversationHandler: cập nhật thông tin build
  Bấm ➕ Build mới       → ConversationHandler: thêm version mới
  Bấm 📱 Thêm app        → ConversationHandler: thêm app mới
  Bấm 🔙 Danh sách       → quay lại list

Chỉ ALLOWED_USER_IDS mới dùng được (require_auth).
Parse mode: MarkdownV2 (nhất quán với toàn bộ bot).
"""

from __future__ import annotations

import logging
import httpx
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
from telegram.constants import ChatAction

from config import ALLOWED_USER_IDS
from services.markdown import escape, bold, italic, code, build, link
from services.telegram_utils import send_message_safe, edit_message_safe
from services import build_db

logger = logging.getLogger(__name__)

MODE = "HTML"

# ─── ConversationHandler states ──────────────────────────────
# Thêm app mới
(
    ADD_APP_NAME,
    ADD_APP_ICON,
    ADD_APP_DESC,
) = range(3)

# Thêm version mới cho app đã chọn
(
    ADD_VER_VERSION,
    ADD_VER_TAG,
    ADD_VER_ENV,
    ADD_VER_APK,
    ADD_VER_TF_URL,
    ADD_VER_TF_VER,
    ADD_VER_NOTE,
) = range(10, 17)

# Sửa version hiện tại
(
    EDIT_VER_FIELD,
    EDIT_VER_VALUE,
) = range(20, 22)


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


def _fmt_build(app: dict, ver: dict | None) -> str:
    """Format tin nhắn hiển thị bảng build của một app."""
    icon = app.get("icon", "🚀")
    slug = app.get("slug", "").upper()
    desc = app.get("description", "")

    lines = [
        f"{escape(icon)} {bold('#BUILD')} {bold('#' + slug)}",
        f"📍 {bold(desc)}" if desc else "",
        "",
    ]

    if ver:
        if ver.get("git_tag"):
            lines.append(f"🏷 {bold('Git Tag')}: {code(ver['git_tag'])}")
        if ver.get("env"):
            lines.append(f"🌍 {bold('Môi trường')}: {code(ver['env'])}")

        if ver.get("apk_url"):
            lines.append(f"🤖 {bold('Android (APK)')}: {link('Tải về', ver['apk_url'])}")

        tf_ver = ver.get("testflight_ver", "")
        tf_url = ver.get("testflight_url", "")
        if tf_ver:
            if tf_url:
                lines.append(f"🍎 {bold('iOS (TestFlight)')}: {link(tf_ver, tf_url)}")
            else:
                lines.append(f"🍎 {bold('iOS (TestFlight)')}: {escape(tf_ver)}")

        if ver.get("note"):
            lines.append("")
            lines.append(f"📝 {bold('Ghi chú')}: {italic(ver['note'])}")
    else:
        lines.append(italic(escape("(Chưa có build nào)")))

    return build(*lines)


def _fmt_build_raw(app: dict, ver: dict | None) -> str:
    """Tạo text thuần để copy/chia sẻ (không có MarkdownV2 escape)."""
    icon = app.get("icon", "🚀")
    slug = app.get("slug", "").upper()
    desc = app.get("description", "")
    version = ver['version'] if ver else "(chưa có build)"

    lines = [
        f"{icon} #BUILD #{slug}",
        f"📍 {desc}" if desc else "",
        "",
        f"🏷 Git Tag: {ver['git_tag']}" if ver and ver.get("git_tag") else "",
    ]
    if ver:
        if ver.get("env"):
            lines.append(f"🌍 Môi trường: {ver['env']}")

        if ver.get("apk_url"):
            lines.append(f"🤖 Android (APK): {ver['apk_url']}")
        if ver.get("testflight_ver"):
            lines.append(f"🍎 iOS (TestFlight): {ver['testflight_ver']}")

        if ver.get("note"):
            lines.append("")
            lines.append(f"📝 Ghi chú: {ver['note']}")

    return "\n".join(lines)


def _apps_keyboard(apps: list[dict]) -> InlineKeyboardMarkup:
    """Tạo keyboard danh sách app — mỗi app 1 hàng."""
    rows = []
    for a in apps:
        label = f"{a.get('icon','🚀')} {a['name']}"
        if a.get("latest_git_tag"):
            label += f"  {a['latest_git_tag']}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bld:app:{a['id']}")])
    rows.append([InlineKeyboardButton("📱 Thêm app mới", callback_data="bld:add_app")])
    return InlineKeyboardMarkup(rows)


def _build_detail_keyboard(app_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Sửa build",  callback_data=f"bld:edit:{app_id}"),
            InlineKeyboardButton("➕ Build mới",   callback_data=f"bld:newver:{app_id}"),
        ],
        [
            InlineKeyboardButton("🔗 Chia sẻ",    callback_data=f"bld:share:{app_id}"),
            InlineKeyboardButton("📜 Lịch sử",    callback_data=f"bld:history:{app_id}"),
        ],
        [
            InlineKeyboardButton("🗑 Xoá app",     callback_data=f"bld:del_confirm:{app_id}"),
            InlineKeyboardButton("🔙 Danh sách",  callback_data="bld:list"),
        ],
    ])


def _skip_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏩ Bỏ qua", callback_data=callback_data)]
    ])


def _skip_keyboard_with_old(callback_data: str, old_val: str = None, old_label: str = None) -> InlineKeyboardMarkup:
    buttons = []
    if old_val:
        field = callback_data.split(":")[1]
        label = f"📋 Dùng bản cũ: {old_label or old_val}"
        if len(label) > 40:
            label = f"📋 {old_label or 'Dùng bản cũ'}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"bld_use_old:{field}")])
    buttons.append([InlineKeyboardButton("⏩ Bỏ qua", callback_data=callback_data)])
    return InlineKeyboardMarkup(buttons)


def _version_keyboard(app_id: int, old_version: str = None) -> InlineKeyboardMarkup:
    buttons = []
    if old_version:
        buttons.append([InlineKeyboardButton(f"📋 Dùng bản cũ: {old_version}", callback_data="bld_use_old:version")])
    buttons.append([InlineKeyboardButton("❌ Huỷ", callback_data=f"bld:app:{app_id}")])
    return InlineKeyboardMarkup(buttons)


# ─── /build-version ──────────────────────────────────────────

@require_auth
async def cmd_build_version(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/build-version — hiển thị danh sách app dạng inline button."""
    await _answer(update)
    msg = update.effective_message

    apps = await build_db.get_all_apps()

    if not apps:
        await send_message_safe(
            bot=update.get_bot(),
            chat_id=update.effective_chat.id,
            text=build(
                bold("📍 🚀 BUILD & HỆ THỐNG"),
                "",
                escape("Chưa có app nào. Bấm nút bên dưới để thêm."),
            ),
            parse_mode=MODE,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 Thêm app mới", callback_data="bld:add_app")]
            ]),
        )
        return

    await send_message_safe(
        bot=update.get_bot(),
        chat_id=update.effective_chat.id,
        text=build(
            bold("📍 🚀 BUILD & HỆ THỐNG"),
            "",
            escape("Chọn app để xem bảng build:"),
        ),
        parse_mode=MODE,
        reply_markup=_apps_keyboard(apps),
    )


# ─── Callback: danh sách ─────────────────────────────────────

async def cb_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quay về danh sách app (bấm 🔙)."""
    await _answer(update)
    apps = await build_db.get_all_apps()

    text = build(
        bold("📍 🚀 BUILD & HỆ THỐNG"),
        "",
        escape("Chọn app để xem bảng build:"),
    )
    keyboard = _apps_keyboard(apps) if apps else InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Thêm app mới", callback_data="bld:add_app")]
    ])

    try:
        await update.callback_query.edit_message_text(
            text=text, parse_mode=MODE, reply_markup=keyboard
        )
    except Exception:
        await send_message_safe(
            bot=update.get_bot(),
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard,
        )


# ─── Callback: xem chi tiết app ──────────────────────────────

async def cb_app_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bấm tên app → hiển thị bảng build đẹp."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])

    app = await build_db.get_app(app_id)
    ver = await build_db.get_latest_version(app_id)

    if not app:
        await update.callback_query.answer("App không tồn tại.", show_alert=True)
        return

    text = _fmt_build(app, ver)
    keyboard = _build_detail_keyboard(app_id)

    try:
        await update.callback_query.edit_message_text(
            text=text, parse_mode=MODE, reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"edit_message_text failed: {e}")
        await send_message_safe(
            bot=update.get_bot(),
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard,
        )


# ─── Callback: lịch sử build ─────────────────────────────────

async def cb_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])
    app = await build_db.get_app(app_id)
    history = await build_db.get_version_history(app_id, limit=10)

    if not history:
        await update.callback_query.answer("Chưa có lịch sử build.", show_alert=True)
        return

    lines = [bold(f"📜 Lịch sử build — {app['name'] if app else app_id}"), ""]
    for i, v in enumerate(history):
        is_latest = "✅ " if v.get("is_latest") else ""
        date = v.get("created_at", "")[:10]
        lines.append(
            f"{is_latest}{bold(v['version'])} {escape('|')} "
            f"{escape(v.get('env',''))} {escape('|')} "
            f"{escape(date)}"
        )
        if v.get("note"):
            lines.append(f"   _{italic(v['note'])}_")

    try:
        await update.callback_query.edit_message_text(
            text=build(*lines),
            parse_mode=MODE,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Quay lại", callback_data=f"bld:app:{app_id}")]
            ]),
        )
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
# ConversationHandler: Thêm version mới
# ════════════════════════════════════════════════════════════

# ─── Helper functions for prompting with old build suggestions ───

def _get_tag_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE, version: str):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_tag = old_ver.get("git_tag", "")
    
    text_lines = [
        escape("✅ Version: ") + bold(version),
        ""
    ]
    if old_tag:
        text_lines.append(escape(f"Git Tag (VD: v1.1.2) [Bản cũ: {old_tag}] — bấm Bỏ qua để dùng chính số version:"))
    else:
        text_lines.append(escape("Git Tag (VD: v1.1.2) — bấm Bỏ qua để dùng chính số version:"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:git_tag", old_tag)
    return build(*text_lines), keyboard


def _get_env_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE, git_tag: str):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_env = old_ver.get("env", "")
    
    text_lines = [
        escape("✅ Tag: ") + bold(git_tag),
        ""
    ]
    if old_env:
        text_lines.append(escape(f"Môi trường (demo / staging / production) [Bản cũ: {old_env}] — bấm Bỏ qua để giữ 'demo':"))
    else:
        text_lines.append(escape("Môi trường (demo / staging / production) — bấm Bỏ qua để giữ 'demo':"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:env", old_env)
    return build(*text_lines), keyboard


def _get_apk_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_apk = old_ver.get("apk_url", "")
    
    text_lines = []
    if old_apk:
        text_lines.append(escape("Link APK ARMv8 (Google Drive…) — bấm Bỏ qua để tiếp tục:"))
        text_lines.append(escape(f"[Bản cũ: {old_apk}]"))
    else:
        text_lines.append(escape("Link APK ARMv8 (Google Drive…) — bấm Bỏ qua để tiếp tục:"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:apk", old_apk, old_label="Dùng APK cũ")
    return build(*text_lines), keyboard


def _get_tf_url_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_tf_url = old_ver.get("testflight_url", "")
    
    text_lines = []
    if old_tf_url:
        text_lines.append(escape("Link TestFlight — bấm Bỏ qua để tiếp tục:"))
        text_lines.append(escape(f"[Bản cũ: {old_tf_url}]"))
    else:
        text_lines.append(escape("Link TestFlight — bấm Bỏ qua để tiếp tục:"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:tf_url", old_tf_url, old_label="Dùng TF URL cũ")
    return build(*text_lines), keyboard


def _get_tf_ver_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_tf_ver = old_ver.get("testflight_ver", "")
    
    text_lines = []
    if old_tf_ver:
        text_lines.append(escape(f"Version TestFlight (VD: 1.2.5 (1)) [Bản cũ: {old_tf_ver}] — bấm Bỏ qua để tiếp tục:"))
    else:
        text_lines.append(escape("Version TestFlight (VD: 1.2.5 (1)) — bấm Bỏ qua để tiếp tục:"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:tf_ver", old_tf_ver)
    return build(*text_lines), keyboard


def _get_note_prompt_and_keyboard(ctx: ContextTypes.DEFAULT_TYPE):
    old_ver = ctx.user_data.get("bld_latest_ver", {})
    old_note = old_ver.get("note", "")
    
    text_lines = []
    if old_note:
        text_lines.append(escape(f"Ghi chú (note) [Bản cũ: {old_note}] — bấm Bỏ qua để tiếp tục:"))
    else:
        text_lines.append(escape("Ghi chú (note) — bấm Bỏ qua để tiếp tục:"))
        
    keyboard = _skip_keyboard_with_old("bld_skip_ver:note", old_note, old_label="Dùng note cũ")
    return build(*text_lines), keyboard


async def cb_use_old_ver(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bấm nút 'Dùng bản cũ' trong quá trình nhập version mới."""
    await _answer(update)
    field = update.callback_query.data.split(":")[1]
    old_ver = ctx.user_data.get("bld_latest_ver", {})

    if field == "version":
        val = old_ver.get("version", "")
        ctx.user_data["bld_ver_version"] = val
        text, keyboard = _get_tag_prompt_and_keyboard(ctx, val)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_TAG

    elif field == "git_tag":
        val = old_ver.get("git_tag", "")
        ctx.user_data["bld_ver_tag"] = val
        text, keyboard = _get_env_prompt_and_keyboard(ctx, val)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_ENV

    elif field == "env":
        val = old_ver.get("env", "demo")
        ctx.user_data["bld_ver_env"] = val
        text, keyboard = _get_apk_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_APK

    elif field == "apk":
        val = old_ver.get("apk_url", "")
        ctx.user_data["bld_ver_apk"] = val
        text, keyboard = _get_tf_url_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_TF_URL

    elif field == "tf_url":
        val = old_ver.get("testflight_url", "")
        ctx.user_data["bld_ver_tf_url"] = val
        text, keyboard = _get_tf_ver_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_TF_VER

    elif field == "tf_ver":
        val = old_ver.get("testflight_ver", "")
        ctx.user_data["bld_ver_tf_ver"] = val
        text, keyboard = _get_note_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_NOTE

    elif field == "note":
        val = old_ver.get("note", "")
        ctx.user_data["bld_ver_note"] = val
        
        # Lưu bản build mới luôn
        app_id      = ctx.user_data["bld_app_id"]
        version     = ctx.user_data["bld_ver_version"]
        git_tag     = ctx.user_data.get("bld_ver_tag", version)
        env         = ctx.user_data.get("bld_ver_env", "demo")
        apk_url     = ctx.user_data.get("bld_ver_apk", "")
        tf_url      = ctx.user_data.get("bld_ver_tf_url", "")
        tf_ver      = ctx.user_data.get("bld_ver_tf_ver", "")
        note        = ctx.user_data.get("bld_ver_note", "")
        user_id     = update.effective_user.id

        await build_db.add_version(
            app_id=app_id,
            version=version,
            git_tag=git_tag,
            env=env,
            apk_url=apk_url,
            testflight_url=tf_url,
            testflight_ver=tf_ver,
            note=note,
            created_by=user_id,
        )

        app = await build_db.get_app(app_id)
        ver = await build_db.get_latest_version(app_id)
        text = build(
            escape("✅ Đã lưu build mới!"),
            "",
            _fmt_build(app, ver),
        )
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=_build_detail_keyboard(app_id),
        )
        _clear_ver_data(ctx)
        return ConversationHandler.END


async def cb_new_version_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point: bấm ➕ Build mới."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])
    app = await build_db.get_app(app_id)
    ctx.user_data["bld_app_id"] = app_id

    ver = await build_db.get_latest_version(app_id)
    if ver:
        ctx.user_data["bld_latest_ver"] = ver

    text_lines = [
        bold(f"➕ Thêm build mới — {app['name'] if app else ''}"),
        ""
    ]
    if ver:
        text_lines.append(escape(f"Bản cũ: {ver['version']} (Tag: {ver.get('git_tag') or 'không có'}, Env: {ver.get('env') or 'không có'})"))
        text_lines.append("")
    text_lines.append(escape("Nhập số version mới (VD: v1.2.0):"))

    keyboard = _version_keyboard(app_id, ver.get("version") if ver else None)

    await update.callback_query.edit_message_text(
        text=build(*text_lines),
        parse_mode=MODE,
        reply_markup=keyboard,
    )
    return ADD_VER_VERSION


async def add_ver_version(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    version = update.effective_message.text.strip()
    ctx.user_data["bld_ver_version"] = version
    text, keyboard = _get_tag_prompt_and_keyboard(ctx, version)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_TAG


async def add_ver_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_ver_tag"] = val
    text, keyboard = _get_env_prompt_and_keyboard(ctx, val)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_ENV


async def add_ver_env(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_ver_env"] = val if val != "." else "demo"
    text, keyboard = _get_apk_prompt_and_keyboard(ctx)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_APK


async def add_ver_apk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_ver_apk"] = val if val != "." else ""
    text, keyboard = _get_tf_url_prompt_and_keyboard(ctx)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_TF_URL


async def add_ver_tf_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_ver_tf_url"] = val if val != "." else ""
    text, keyboard = _get_tf_ver_prompt_and_keyboard(ctx)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_TF_VER


async def add_ver_tf_ver(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_ver_tf_ver"] = val if val != "." else ""
    text, keyboard = _get_note_prompt_and_keyboard(ctx)
    await update.effective_message.reply_text(
        text=text,
        parse_mode=MODE,
        reply_markup=keyboard
    )
    return ADD_VER_NOTE


async def add_ver_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "bld_ver_note" not in ctx.user_data:
        val = update.effective_message.text.strip()
        ctx.user_data["bld_ver_note"] = val if val != "." else ""

    app_id      = ctx.user_data["bld_app_id"]
    version     = ctx.user_data["bld_ver_version"]
    git_tag     = ctx.user_data.get("bld_ver_tag", version)
    env         = ctx.user_data.get("bld_ver_env", "demo")
    apk_url     = ctx.user_data.get("bld_ver_apk", "")
    tf_url      = ctx.user_data.get("bld_ver_tf_url", "")
    tf_ver      = ctx.user_data.get("bld_ver_tf_ver", "")
    note        = ctx.user_data.get("bld_ver_note", "")
    user_id     = update.effective_user.id

    await build_db.add_version(
        app_id=app_id,
        version=version,
        git_tag=git_tag,
        env=env,
        apk_url=apk_url,
        testflight_url=tf_url,
        testflight_ver=tf_ver,
        note=note,
        created_by=user_id,
    )

    app = await build_db.get_app(app_id)
    ver = await build_db.get_latest_version(app_id)
    text = build(
        escape("✅ Đã lưu build mới!"),
        "",
        _fmt_build(app, ver),
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=_build_detail_keyboard(app_id)
        )
    else:
        await send_message_safe(
            bot=update.get_bot(),
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode=MODE,
            reply_markup=_build_detail_keyboard(app_id),
        )
    _clear_ver_data(ctx)
    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
# ConversationHandler: Sửa version hiện tại
# ════════════════════════════════════════════════════════════

async def cb_edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point: bấm ✏️ Sửa build."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])
    ctx.user_data["bld_app_id"] = app_id

    ver = await build_db.get_latest_version(app_id)
    if not ver:
        await update.callback_query.answer("Chưa có build nào để sửa.", show_alert=True)
        return ConversationHandler.END

    ctx.user_data["bld_ver_id"] = ver["id"]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔢 Version",     callback_data="bld_field:version"),
            InlineKeyboardButton("🏷 Git Tag",     callback_data="bld_field:git_tag"),
        ],
        [
            InlineKeyboardButton("🌍 ENV",         callback_data="bld_field:env"),
            InlineKeyboardButton("🤖 APK URL",     callback_data="bld_field:apk_url"),
        ],
        [
            InlineKeyboardButton("🍎 TF URL",      callback_data="bld_field:testflight_url"),
            InlineKeyboardButton("🍎 TF Version",  callback_data="bld_field:testflight_ver"),
        ],
        [
            InlineKeyboardButton("📝 Note",         callback_data="bld_field:note"),
            InlineKeyboardButton("❌ Huỷ", callback_data=f"bld:app:{app_id}"),
        ],
    ])

    await update.callback_query.edit_message_text(
        text=build(
            bold("✏️ Chọn trường muốn sửa:"),
            "",
            escape(f"Build hiện tại: {ver['version']} ({ver['env']})"),
        ),
        parse_mode=MODE,
        reply_markup=keyboard,
    )
    return EDIT_VER_FIELD


async def edit_ver_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User chọn field để sửa."""
    await _answer(update)
    field = update.callback_query.data.split(":")[1]
    ctx.user_data["bld_edit_field"] = field

    labels = {
        "version":         "Version (VD: v1.2.3)",
        "git_tag":         "Git Tag (VD: v1.1.2)",
        "env":             "ENV (demo / staging / production)",
        "apk_url":         "Link APK",
        "testflight_url":  "Link TestFlight",
        "testflight_ver":  "Version TestFlight (VD: 1.2.5 (1))",
        "note":            "Ghi chú",
    }
    prompt = labels.get(field, field)

    await update.callback_query.edit_message_text(
        text=build(
            bold(f"✏️ Sửa: {prompt}"),
            "",
            escape("Nhập giá trị mới:"),
        ),
        parse_mode=MODE,
    )
    return EDIT_VER_VALUE


async def edit_ver_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Nhận giá trị mới, lưu vào DB."""
    new_val  = update.effective_message.text.strip()
    field    = ctx.user_data.get("bld_edit_field")
    ver_id   = ctx.user_data.get("bld_ver_id")
    app_id   = ctx.user_data.get("bld_app_id")

    await build_db.update_version(ver_id, **{field: new_val})

    app = await build_db.get_app(app_id)
    ver = await build_db.get_latest_version(app_id)
    text = build(
        escape("✅ Đã cập nhật!"),
        "",
        _fmt_build(app, ver),
    )
    await send_message_safe(
        bot=update.get_bot(),
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=MODE,
        reply_markup=_build_detail_keyboard(app_id),
    )
    _clear_ver_data(ctx)
    return ConversationHandler.END


async def cb_deploy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bấm 🚀 Deploy → gọi URL deploy."""
    await _answer(update)
    
    data = update.callback_query.data
    is_main = data == "bld:deploy_main"

    if is_main:
        # Tự động lấy text hiện tại, xoá phần status cũ nếu có
        current_text = update.callback_query.message.text_markdown_v2 or update.callback_query.message.text or ""
        if current_text:
            parts = current_text.split("\n\n")
            # Loại bỏ các phần có chứa icon trạng thái của deploy cũ
            filtered_parts = [p for p in parts if not any(icon in p for icon in ["⏳", "✅", "❌", "⚠️"])]
            base_text = "\n\n".join(filtered_parts)
        else:
            base_text = bold("📍 🚀 BUILD & HỆ THỐNG")
        
        reply_markup = update.callback_query.message.reply_markup
    else:
        # Fallback cho các callback cũ nếu có (bld:deploy:app_id)
        app_id = int(data.split(":")[2])
        app = await build_db.get_app(app_id)
        ver = await build_db.get_latest_version(app_id)
        base_text = _fmt_build(app, ver)
        reply_markup = update.callback_query.message.reply_markup

    # 1. Update status
    try:
        await edit_message_safe(
            bot=ctx.bot,
            chat_id=update.effective_chat.id,
            message_id=update.callback_query.message.message_id,
            text=base_text + f"\n\n⏳ {italic(escape('Đang deploy service...'))}",
            parse_mode=MODE,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning(f"Sơ suất khi edit status: {e}")

    url = "http://10.82.117.40:3579/smarttown-deploy"
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=30.0)
            
            if resp.status_code == 200:
                data_json = resp.json()
                if data_json.get("message") == "Triggered jobs.":
                    jobs = data_json.get("jobs", {})
                    job_id = "N/A"
                    if jobs:
                        first_job = next(iter(jobs.values()))
                        job_id = first_job.get("id", "N/A")
                    
                    status_text = f"✅ {bold('Deploy thành công!')}\n   Job ID: {code(str(job_id))}"
                else:
                    status_text = f"⚠️ {bold('Kết quả lạ')}: {escape(str(data_json.get('message')))}"
            else:
                status_text = f"❌ {bold('Deploy thất bại')} (HTTP {resp.status_code})"
                
    except Exception as e:
        logger.error(f"Deploy error: {e}")
        status_text = f"❌ {bold('Lỗi khi deploy')}: {escape(str(e))}"

    await edit_message_safe(
        bot=ctx.bot,
        chat_id=update.effective_chat.id,
        message_id=update.callback_query.message.message_id,
        text=base_text + f"\n\n{status_text}",
        parse_mode=MODE,
        reply_markup=reply_markup
    )


# ─── Callback: chia sẻ ───────────────────────────────────────

async def cb_share(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gửi text thuần trong code block để user copy/chia sẻ."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])

    app = await build_db.get_app(app_id)
    ver = await build_db.get_latest_version(app_id)

    if not app or not ver:
        await update.callback_query.answer("Không có build để chia sẻ.", show_alert=True)
        return

    raw_text = _fmt_build_raw(app, ver)

    import urllib.parse
    share_url = f"https://t.me/share/url?url=&text={urllib.parse.quote(raw_text)}"

    await send_message_safe(
        bot=update.get_bot(),
        chat_id=update.effective_chat.id,
        text=build(
            escape("📝 Nhấn vào nội dung bên dưới để copy:"),
            "",
            code(raw_text),
        ),
        parse_mode=MODE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Gửi vào nhóm/người khác", url=share_url)],
            [InlineKeyboardButton("🔙 Quay lại", callback_data=f"bld:app:{app_id}")]
        ])
    )


# ─── Callback: xoá app ───────────────────────────────────────

async def cb_delete_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Hiện xác nhận xoá app."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])
    app = await build_db.get_app(app_id)

    if not app:
        await update.callback_query.answer("App không tồn tại.", show_alert=True)
        return

    text = build(
        bold(f"⚠️ XÁC NHẬN XOÁ APP: {app['name']}"),
        "",
        escape("Hành động này sẽ xoá vĩnh viễn app và toàn bộ lịch sử build của nó."),
        escape("Bạn có chắc chắn muốn thực hiện?"),
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Không, quay lại", callback_data=f"bld:app:{app_id}"),
            InlineKeyboardButton("✅ Có, XOÁ NGAY",  callback_data=f"bld:del_perform:{app_id}"),
        ]
    ])

    await update.callback_query.edit_message_text(
        text=text, parse_mode=MODE, reply_markup=keyboard
    )


async def cb_delete_perform(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Thực hiện xoá app."""
    await _answer(update)
    app_id = int(update.callback_query.data.split(":")[2])
    app = await build_db.get_app(app_id)

    if app:
        await build_db.delete_app(app_id)
        await update.callback_query.answer(f"Đã xoá app {app['name']}", show_alert=True)
    else:
        await update.callback_query.answer("App không tồn tại.")

    # Quay lại danh sách app
    return await cb_list(update, ctx)


# ─── Callbacks: Bỏ qua trong conversation ────────────────────

async def cb_skip_ver(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bấm nút 'Bỏ qua' trong quá trình nhập version mới."""
    await _answer(update)
    field = update.callback_query.data.split(":")[1]

    if field == "git_tag":
        # Dùng luôn version làm tag
        val = ctx.user_data.get("bld_ver_version", "")
        ctx.user_data["bld_ver_tag"] = val
        text, keyboard = _get_env_prompt_and_keyboard(ctx, val)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_ENV
    elif field == "env":
        ctx.user_data["bld_ver_env"] = "demo"
        text, keyboard = _get_apk_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_APK
    elif field == "apk":
        ctx.user_data["bld_ver_apk"] = ""
        text, keyboard = _get_tf_url_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_TF_URL
    elif field == "tf_url":
        ctx.user_data["bld_ver_tf_url"] = ""
        text, keyboard = _get_tf_ver_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_TF_VER
    elif field == "tf_ver":
        ctx.user_data["bld_ver_tf_ver"] = ""
        text, keyboard = _get_note_prompt_and_keyboard(ctx)
        await update.callback_query.edit_message_text(
            text=text,
            parse_mode=MODE,
            reply_markup=keyboard
        )
        return ADD_VER_NOTE
    elif field == "note":
        ctx.user_data["bld_ver_note"] = ""
        # Kết thúc và lưu luôn
        return await add_ver_note(update, ctx)

    return ConversationHandler.END


async def cb_skip_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bấm nút 'Bỏ qua' trong quá trình thêm app mới."""
    await _answer(update)
    field = update.callback_query.data.split(":")[1]

    if field == "icon":
        ctx.user_data["bld_new_app_icon"] = "🚀"
        await update.callback_query.edit_message_text(
            escape("Mô tả ngắn (VD: Điều hành khu phố, ấp) — bấm Bỏ qua để tiếp tục:"),
            parse_mode=MODE,
            reply_markup=_skip_keyboard("bld_skip_app:desc")
        )
        return ADD_APP_DESC
    elif field == "desc":
        # Kết thúc và lưu luôn
        return await add_app_desc(update, ctx)

    return ConversationHandler.END


# ════════════════════════════════════════════════════════════
# ConversationHandler: Thêm app mới
# ════════════════════════════════════════════════════════════

async def cb_add_app_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _answer(update)
    await update.callback_query.edit_message_text(
        text=build(
            bold("📱 Thêm app mới"),
            "",
            escape("Tên app (VD: SmartTown Demo):"),
        ),
        parse_mode=MODE,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Huỷ", callback_data="bld:list")]
        ]),
    )
    return ADD_APP_NAME


async def add_app_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["bld_new_app_name"] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        escape("Icon cho app (VD: 🚀) — bấm Bỏ qua để dùng 🚀:"),
        parse_mode=MODE,
        reply_markup=_skip_keyboard("bld_skip_app:icon")
    )
    return ADD_APP_ICON


async def add_app_icon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.effective_message.text.strip()
    ctx.user_data["bld_new_app_icon"] = val if val != "." else "🚀"
    await update.effective_message.reply_text(
        escape("Mô tả ngắn (VD: Điều hành khu phố, ấp) — bấm Bỏ qua để tiếp tục:"),
        parse_mode=MODE,
        reply_markup=_skip_keyboard("bld_skip_app:desc")
    )
    return ADD_APP_DESC


async def add_app_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val  = update.effective_message.text.strip()
    desc = val if val != "." else ""
    name = ctx.user_data["bld_new_app_name"]
    icon = ctx.user_data.get("bld_new_app_icon", "🚀")

    # Tạo slug từ tên (lowercase, thay space bằng _)
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    app_id = await build_db.add_app(
        name=name,
        slug=slug,
        icon=icon,
        description=desc,
        created_by=update.effective_user.id,
    )

    apps = await build_db.get_all_apps()
    await send_message_safe(
        bot=update.get_bot(),
        chat_id=update.effective_chat.id,
        text=build(
            escape(f"✅ Đã thêm app {icon} {name}!"),
            "",
            escape("Chọn app để thêm build đầu tiên:"),
        ),
        parse_mode=MODE,
        reply_markup=_apps_keyboard(apps),
    )
    _clear_app_data(ctx)
    return ConversationHandler.END


# ─── Cancel chung ────────────────────────────────────────────

async def conv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Gõ /cancel hoặc /build-version để thoát conversation."""
    _clear_ver_data(ctx)
    _clear_app_data(ctx)
    if update.effective_message:
        await update.effective_message.reply_text(
            escape("Đã huỷ."), parse_mode=MODE
        )
    return ConversationHandler.END


async def cb_conv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Huỷ conversation qua callback (nút Huỷ)."""
    await _answer(update)
    _clear_ver_data(ctx)
    _clear_app_data(ctx)

    data = update.callback_query.data
    if data.startswith("bld:app:"):
        await cb_app_detail(update, ctx)
    elif data == "bld:list":
        await cb_list(update, ctx)

    return ConversationHandler.END


def _clear_ver_data(ctx: ContextTypes.DEFAULT_TYPE):
    for k in ("bld_app_id", "bld_ver_id", "bld_ver_version", "bld_ver_tag",
              "bld_ver_env", "bld_ver_apk", "bld_ver_tf_url", "bld_ver_tf_ver",
              "bld_ver_note", "bld_edit_field", "bld_latest_ver"):
        ctx.user_data.pop(k, None)


def _clear_app_data(ctx: ContextTypes.DEFAULT_TYPE):
    for k in ("bld_new_app_name", "bld_new_app_icon"):
        ctx.user_data.pop(k, None)


# ─── Register ────────────────────────────────────────────────

def register_build_handlers(app: Application):
    """Gọi hàm này trong main.py sau register_journal_handlers(app)."""

    # ── ConversationHandler: Thêm version mới ────────────────
    new_ver_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_new_version_start, pattern=r"^bld:newver:\d+$")],
        states={
            ADD_VER_VERSION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_version),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:version$"),
            ],
            ADD_VER_TAG:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_tag),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:git_tag$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:git_tag$"),
            ],
            ADD_VER_ENV:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_env),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:env$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:env$"),
            ],
            ADD_VER_APK:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_apk),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:apk$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:apk$"),
            ],
            ADD_VER_TF_URL:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_tf_url),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:tf_url$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:tf_url$"),
            ],
            ADD_VER_TF_VER:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_tf_ver),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:tf_ver$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:tf_ver$"),
            ],
            ADD_VER_NOTE:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_ver_note),
                CallbackQueryHandler(cb_skip_ver, pattern=r"^bld_skip_ver:note$"),
                CallbackQueryHandler(cb_use_old_ver, pattern=r"^bld_use_old:note$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CommandHandler("build_version", conv_cancel),
            CallbackQueryHandler(cb_conv_cancel, pattern=r"^(bld:app:\d+|bld:list)$"),
        ],
        per_user=True,
        per_chat=True,
    )

    # ── ConversationHandler: Sửa version ─────────────────────
    edit_ver_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_edit_start, pattern=r"^bld:edit:\d+$")],
        states={
            EDIT_VER_FIELD: [CallbackQueryHandler(edit_ver_field, pattern=r"^bld_field:")],
            EDIT_VER_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_ver_value)],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CommandHandler("build_version", conv_cancel),
            CallbackQueryHandler(cb_conv_cancel, pattern=r"^(bld:app:\d+|bld:list)$"),
        ],
        per_user=True,
        per_chat=True,
    )

    # ── ConversationHandler: Thêm app mới ────────────────────
    add_app_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_add_app_start, pattern=r"^bld:add_app$")],
        states={
            ADD_APP_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_app_name)],
            ADD_APP_ICON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_app_icon),
                CallbackQueryHandler(cb_skip_app, pattern=r"^bld_skip_app:icon$"),
            ],
            ADD_APP_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_app_desc),
                CallbackQueryHandler(cb_skip_app, pattern=r"^bld_skip_app:desc$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", conv_cancel),
            CommandHandler("build_version", conv_cancel),
            CallbackQueryHandler(cb_conv_cancel, pattern=r"^(bld:app:\d+|bld:list)$"),
        ],
        per_user=True,
        per_chat=True,
    )

    # ── Đăng ký tất cả ───────────────────────────────────────
    app.add_handler(CommandHandler("build_version", cmd_build_version))
    app.add_handler(new_ver_conv)
    app.add_handler(edit_ver_conv)
    app.add_handler(add_app_conv)

    # Simple callbacks (không cần conversation)
    app.add_handler(CallbackQueryHandler(cb_list,       pattern=r"^bld:list$"))
    app.add_handler(CallbackQueryHandler(cb_app_detail, pattern=r"^bld:app:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_history,    pattern=r"^bld:history:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_share,      pattern=r"^bld:share:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_deploy,     pattern=r"^bld:deploy"))
    app.add_handler(CallbackQueryHandler(cb_delete_confirm, pattern=r"^bld:del_confirm:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_delete_perform, pattern=r"^bld:del_perform:\d+$"))

    logger.info("✅ Build handlers đã được đăng ký (/build_version)")
