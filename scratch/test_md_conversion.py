import sys
import os

sys.path.append(os.getcwd())

from services.markdown import ai_to_mdv2

test_markdown = """📦 **ĐỀ XUẤT VERSION:** `v0.1.0` (MINOR) - Từ: `v0.0.1`

📋 **Nhấp vào khung dưới đây để sao chép Markdown (dán vào GitLab Release):**
```markdown
📌 **Release Notes – SmartTown**

🚀 **Tính năng mới**

* **Thêm form cập nhật địa chỉ** cho người dùng.
* **Tích hợp menu điều hướng** mới trên ứng dụng.

🔧 **Cải tiến & điều chỉnh**

* **Tái cấu trúc thư mục nguồn (src)** để tối ưu cấu trúc mã nguồn.
* **Cập nhật giao diện người dùng (UI)** và cấu hình **routing**.
```"""

print("=== RAW INPUT ===")
print(test_markdown)

print("\n=== CONVERTED HTML ===")
print(ai_to_mdv2(test_markdown))
