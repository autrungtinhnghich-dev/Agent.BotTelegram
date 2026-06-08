import re
import html

test_markdown = """📦 **ĐỀ XUẤT VERSION:** `v0.1.0` (MINOR) - Từ: `v0.0.1`

📋 **Nhấp vào khung dưới đây để sao chép Markdown (dán vào GitLab Release):**
```markdown
📌 **Release Notes – SmartTown**

🚀 **Tính năng mới**

* **Thêm form cập nhật địa chỉ** cho người dùng.
* **Tích hợp menu điều hướng** mới trên ứng dụng.
```"""

def trace_conversion(text):
    print("[0] Input length:", len(text))
    
    code_blocks = []
    def stash_code(m):
        lang = m.group(1) or ""
        content = m.group(2)
        code_blocks.append((lang, content))
        return f"@@@BLOCK_{len(code_blocks)-1}@@@"
    
    processed = re.sub(r"```(\w+)?\n?([\s\S]*?)```", stash_code, text)
    print("[1] After stashing code blocks:\n", repr(processed))
    
    inline_codes = []
    def stash_inline(m):
        inline_codes.append(m.group(1))
        return f"@@@INLINE_{len(inline_codes)-1}@@@"
    
    processed = re.sub(r"`([^`\n]+)`", stash_inline, processed)
    print("[2] After stashing inline code:\n", repr(processed))
    
    processed = html.escape(processed, quote=True)
    print("[3] After HTML escape:\n", repr(processed))
    
    processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed, flags=re.DOTALL)
    print("[4] After bold replacement:\n", repr(processed))
    
    processed = re.sub(r"^\s*[\-\*]\s+", "• ", processed, flags=re.MULTILINE)
    print("[5] After bullet point replacement:\n", repr(processed))
    
    for i in range(len(inline_codes) - 1, -1, -1):
        processed = processed.replace(f"@@@INLINE_{i}@@@", f"<code>{html.escape(inline_codes[i])}</code>")
    
    for i in range(len(code_blocks) - 1, -1, -1):
        lang, content = code_blocks[i]
        lang_attr = f' class="language-{lang}"' if lang else ""
        processed = processed.replace(f"@@@BLOCK_{i}@@@", f'<pre><code{lang_attr}>{html.escape(content)}</code></pre>')
    print("[6] After restoring code blocks:\n", repr(processed))

trace_conversion(test_markdown)
