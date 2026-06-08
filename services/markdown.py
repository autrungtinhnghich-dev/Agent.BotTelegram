"""
services/markdown.py

Tiện ích format tin nhắn cho Telegram.
Chuyển sang dùng HTML thay vì MarkdownV2 để tránh lỗi parse nghiêm trọng với các ký tự đặc biệt.
"""

import re
import html

def escape(text: str) -> str:
    """Escape text để an toàn trong HTML mode của Telegram."""
    if not text:
        return ""
    # Telegram HTML yêu cầu escape <, >, &
    return html.escape(str(text), quote=True)


def bold(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def italic(text: str) -> str:
    return f"<i>{escape(text)}</i>"


def code(text: str) -> str:
    """Inline code."""
    return f"<code>{escape(text)}</code>"


def pre(text: str) -> str:
    """Code block."""
    return f"<pre>{escape(text)}</pre>"


def link(label: str, url: str) -> str:
    """Tạo link HTML."""
    if not url:
        return escape(label)
    # URL trong href phải được escape các ký tự như & thành &amp;
    safe_url = html.escape(url, quote=True)
    return f'<a href="{safe_url}">{escape(label)}</a>'


def build(*parts: str, sep: str = "\n") -> str:
    """Nối nhiều phần đã được escape/format sẵn."""
    return sep.join(p for p in parts if p)


def ai_to_mdv2(text: str) -> str:
    """
    Convert output markdown của AI → HTML Telegram.
    Hỗ trợ: **bold**, *italic*, `inline code`, ```code block```, [link](url).
    """
    if not text:
        return ""

    # 1. Bảo vệ các khối code block trước
    code_blocks = [] # Lưu (language, content)
    def stash_code(m):
        lang = m.group(1) or ""
        content = m.group(2)
        code_blocks.append((lang, content))
        return f"@@@BLOCK_{len(code_blocks)-1}@@@"
    
    # Regex bắt group 1 là language (tùy chọn), group 2 là nội dung
    processed = re.sub(r"```(\w+)?\n?([\s\S]*?)```", stash_code, text)

    # ... (giữ nguyên phần trung gian) ...

    # 2. Bảo vệ inline code
    inline_codes = []
    def stash_inline(m):
        inline_codes.append(m.group(1))
        return f"@@@INLINE_{len(inline_codes)-1}@@@"
    
    processed = re.sub(r"`([^`\n]+)`", stash_inline, processed)

    # 3. Escape phần text còn lại
    processed = escape(processed)

    # 4. Convert formatting tags sang HTML
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed, flags=re.DOTALL)
    processed = re.sub(r"__(.+?)__", r"<b>\1</b>", processed, flags=re.DOTALL)
    processed = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", processed, flags=re.DOTALL)
    processed = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", processed, flags=re.DOTALL)

    # Link: [label](url)
    def convert_link(m):
        label = m.group(1)
        url = m.group(2)
        safe_url = html.escape(html.unescape(url), quote=True)
        return f'<a href="{safe_url}">{label}</a>'

    processed = re.sub(r"\[(.+?)\]\((.+?)\)", convert_link, processed)

    # 5. Thay thế Bullet point (sử dụng [ \t] thay vì \s để tránh nuốt mất dòng trống, chạy trước khi khôi phục code block)
    processed = re.sub(r"^[ \t]*[\-\*][ \t]+", "• ", processed, flags=re.MULTILINE)

    # 6. Khôi phục code blocks và inline code
    for i in range(len(inline_codes) - 1, -1, -1):
        processed = processed.replace(f"@@@INLINE_{i}@@@", f"<code>{escape(inline_codes[i])}</code>")
    
    for i in range(len(code_blocks) - 1, -1, -1):
        lang, content = code_blocks[i]
        lang_attr = f' class="language-{lang}"' if lang else ""
        processed = processed.replace(f"@@@BLOCK_{i}@@@", f'<pre><code{lang_attr}>{escape(content)}</code></pre>')

    return processed
