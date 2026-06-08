# 🤖 AI Coding Agent Bot (Google Antigravity SDK & OpenCode.ai)

Dự án này là một robot trợ lý lập trình tự động **AI Coding Agent** chạy trên nền tảng Telegram, tích hợp trực tiếp với **Google Antigravity SDK** hoặc **Local OpenCode Server**. Bot có khả năng chạy độc lập trên máy chủ/máy tính cá nhân của bạn, truy cập trực tiếp vào các thư mục mã nguồn được chỉ định và thực hiện các tác vụ kỹ thuật phần mềm tự động (coding, refactoring, debug) theo yêu cầu ngôn ngữ tự nhiên.

---

## ✨ Các Tính Năng Chính

### 1. 🤖 Lập Trình Tự Động (`/code <yêu cầu>`)
*   **Thực thi task**: Đọc hiểu yêu cầu của bạn, tự động tìm kiếm tệp tin, phân tích cấu trúc code, viết mã nguồn mới hoặc sửa đổi mã nguồn hiện có.
*   **Kích hoạt nhanh**: Trong phòng chat riêng tư 1-1, bạn chỉ cần nhắn tin yêu cầu thông thường, Bot sẽ tự động chuyển tiếp tới Coding Agent để xử lý mà không cần gõ lệnh.
*   **Hỗ trợ 2 kiến trúc**:
    - **Google Antigravity SDK**: Chạy trực tiếp agent cục bộ sử dụng mô hình Gemini API.
    - **Local OpenCode.ai Server**: Giao tiếp với máy chủ OpenCode đang chạy trên máy của bạn qua API.

### 2. ⚙️ Chế Độ Phê Duyệt An Toàn (`/interactive`)
*   **Kiểm soát hoàn toàn**: Khi bật chế độ tương tác (`interactive mode = True`), mọi hành động nhạy cảm của AI Agent trước khi thực thi đều gửi yêu cầu xác nhận về Telegram.
*   **Nút bấm trực quan**: Bot sẽ hiển thị nút **Approve (Cho phép)** hoặc **Deny (Từ chối)** kèm theo các tham số (ví dụ: dòng lệnh Terminal sắp chạy, nội dung file sắp sửa). Agent chỉ tiếp tục khi bạn nhấn nút đồng ý.

### 3. 📂 Quản Lý Workspace (`/repo` / `/setrepo`)
*   **Lựa chọn thư mục**: Quét toàn bộ các thư mục con trong thư mục nguồn `/Users/macmini/SourceCode` để hiển thị thành danh sách các dự án để bạn chọn làm workspace làm việc hiện tại.
*   **Cách ly an toàn**: Agent bị giới hạn hoạt động nghiêm ngặt bên trong workspace đã chọn, tránh can thiệp ngoài ý muốn vào các thư mục hệ thống khác.

### 4. 🛑 Dừng Khẩn Cấp & Làm Sạch Phiên (`/abort` & `/reset`)
*   **Hủy tác vụ (`/abort`)**: Dừng ngay lập tức tiến trình lập trình của Agent nếu phát hiện Agent đi sai hướng hoặc chạy các vòng lặp không mong muốn.
*   **Khởi động lại (`/reset`)**: Xóa sạch ngữ cảnh, lịch sử chat của phiên làm việc hiện tại của repo đó để bắt đầu một nhiệm vụ mới hoàn toàn sạch sẽ.

---

## 🛠 Danh Sách Lệnh (Commands)

| Nhóm | Lệnh | Chức năng |
| :--- | :--- | :--- |
| **Hệ thống** | `/start` | Chào mừng và hiển thị hướng dẫn sử dụng nhanh |
| **Workspace** | `/repo` / `/setrepo` | Xem danh sách các dự án cục bộ và chọn workspace làm việc |
| **Lập trình AI** | `/code [yêu cầu]` | Kích hoạt AI Agent xử lý công việc (hoặc reply tin nhắn + `/code`) |
| | `/abort` | Dừng khẩn cấp tiến trình chạy Coding Agent hiện tại |
| | `/reset` | Xóa sạch ngữ cảnh, lịch sử hội thoại của repo đang chọn |
| | `/interactive` | Bật/Tắt chế độ phê duyệt thủ công từng công cụ của Agent |
| **Chat riêng tư** | *Nhập text trực tiếp* | Tự động kích hoạt Agent xử lý (không cần gõ `/code`) |

---

## 📁 Cấu Trúc Thư Mục Dự Án

```text
.
├── main.py                     # Điểm khởi chạy hệ thống Bot Agent
├── config.py                   # Quản lý cấu hình môi trường đọc từ file .env
├── requirements.txt            # Danh sách thư viện Python cần thiết
├── Dockerfile                  # Cấu hình đóng gói Docker image
├── docker-compose.yml          # Cấu hình Docker Compose để chạy ứng dụng
├── handlers/                   # Chứa logic xử lý các lệnh Telegram
│   ├── agent_bot.py            # Logic Coding Agent, quản lý các session và hooks duyệt lệnh
│   └── calculator.py           # Tiện ích tính toán biểu thức an toàn (/calc)
├── services/                   # Chứa các dịch vụ nền kết nối
│   ├── opencode_service.py     # Giao tiếp với Local OpenCode.ai Server
│   ├── os_agent.py             # Interface điều khiển và chụp màn hình macOS
│   ├── telegram_utils.py       # Tiện ích gửi/sửa tin nhắn Telegram an toàn
│   └── markdown.py             # Định dạng và escape ký tự Telegram HTML/MDV2
└── data/                       # Thư mục lưu trữ database và lịch sử session của Agent
```

---

## 🚀 Hướng Dẫn Cài Đặt Nhanh

### 1. Chuẩn bị tài khoản
1. Chat với `@BotFather` trên Telegram để tạo một Bot mới chuyên dùng làm Agent và lấy `BOT_AGENT_TOKEN`.
2. Nhắn tin cho `@userinfobot` để lấy ID Telegram của bạn điền vào `ALLOWED_USER_IDS` (nhằm bảo mật hệ thống, chỉ cho phép bạn sử dụng).
3. **Lựa chọn bộ não xử lý**:
   - *Cách 1*: Lấy Gemini API Key miễn phí tại [Google AI Studio](https://aistudio.google.com/app/apikey) điền vào `GEMINI_API_KEY`.
   - *Cách 2*: Khởi chạy [OpenCode Local Server](http://localhost:4096) trên máy tính của bạn.

### 2. Cấu hình File Môi Trường
Sao chép `.env.example` thành `.env` và điền đầy đủ các thông tin:
```bash
cp .env.example .env
nano .env
```

**Các biến cấu hình quan trọng:**
*   `BOT_AGENT_TOKEN`: Token của Coding Agent Bot Telegram.
*   `ALLOWED_USER_IDS`: Danh sách ID Telegram của bạn (và những người được phép dùng bot), cách nhau bằng dấu phẩy.
*   `GEMINI_API_KEY`: API Key của Google Gemini (nếu dùng Antigravity SDK).
*   `USE_LOCAL_OPENCODE`: Thiết lập thành `true` nếu dùng OpenCode Server cục bộ, `false` nếu dùng Gemini.
*   `OPENCODE_LOCAL_URL`: Địa chỉ Local OpenCode Server (mặc định: `http://localhost:4096`).

### 3. Khởi chạy Hệ Thống

**Cách 1: Chạy bằng Docker Compose (Khuyên dùng)**
```bash
docker compose up -d
```

**Cách 2: Chạy trực tiếp bằng Python**
```bash
# Tạo môi trường ảo
python3 -m venv venv
source venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt

# Chạy ứng dụng
python3 main.py
```

---

## 🔐 Bảo Mật & Whitelist
*   **Whitelist (`ALLOWED_USER_IDS`)**: Hệ thống tự động kiểm tra ID người dùng gửi lệnh. Chỉ những ID nằm trong danh sách whitelist mới có quyền tương tác với bot. Bất kỳ tin nhắn nào từ người lạ sẽ bị bot từ chối ngay lập tức để bảo vệ an toàn cho máy tính và hệ thống của bạn.
*   **Session String & API Tokens**: File `.env` chứa toàn bộ khóa quyền lực truy cập hệ thống nội bộ của bạn. **TUYỆT ĐỐI KHÔNG** chia sẻ hoặc commit file này lên các repository công khai.

---
*Phát triển và nâng cấp toàn diện bởi [Hung Cuong](https://github.com/hungcuong1995ag-wq)*
