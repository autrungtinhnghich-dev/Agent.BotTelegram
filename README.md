# 🤖 Premium AI Assistant Suite (Multi-Bot, DevOps & OS Agent)

Dự án này là một hệ thống trợ lý **Multi-Bot Telegram** siêu cấp, tích hợp sâu giữa **Bộ não kiến thức (Personal AI Brain - RAG)**, **Trợ lý hội thoại nhóm (Chat Intelligence)**, **Quản lý dự án (Jira & SRS RAG)**, **Tự động hóa DevOps (GitLab, Code Review & Release)**, **Quản trị hệ thống (Docker & Deploy Dashboard)**, **Điều khiển máy tính từ xa (OS World Agent)**, và **Trợ lý lập trình tự động (Coding Agent - Google Antigravity SDK & OpenCode.ai)**.

Hệ thống được thiết kế theo kiến trúc **Đa Bot (Multi-Bot Architecture)** chạy đồng thời 3 Bot độc lập:
1. **Bot Chính (Main AI Bot)**: Tập trung vào cá nhân hóa, RAG kiến thức, Nhật ký, Học tập, OS Control, Docker, phân tích Chat nhóm, và tính toán tiện ích.
2. **Bot Phụ (Jira & DevOps Bot)**: Chuyên dụng cho Quản lý dự án, Jira worklog, AI Code Review, Automated GitLab Release, quản lý các bản Build và CI/CD.
3. **Bot Agent (Coding Agent)**: Robot lập trình AI kết nối qua Google Antigravity SDK hoặc Local OpenCode Server để trực tiếp đọc/sửa mã nguồn, quản lý tệp tin, kiểm tra Git và thực thi các yêu cầu lập trình trực tiếp trên workspace.

---

## ✨ Các Phân Hệ Tính Năng Chính

### 1. 🧠 Bộ Não Trí Tuệ Nhân Tạo (AI Brain & Knowledge RAG)
*   **Học tập tài liệu**: Gửi trực tiếp file PDF, hình ảnh, văn bản cho bot. AI sẽ tự động phân tích, trích xuất thông tin và lập chỉ mục vào SQLite Vector/FTS.
*   **Truy vấn kiến thức (`/ask`, `/brain`)**: Hỏi đáp trực tiếp nhiều lượt với AI dựa trên toàn bộ tài liệu đã học (RAG chuyên sâu).
*   **Lưu ghi chú nhanh (`/save`)**: Ghi chép nhanh các mẩu kiến thức vào bộ nhớ lâu dài của AI.

### 2. 📊 Trợ Lý Phân Tích Nhóm (Chat Intelligence & Spy Mode)
*   **Tóm tắt thông minh (`/sum`, `/tldr`)**: Sử dụng Telethon lấy lịch sử chat của bất kỳ group nào và tóm tắt nhanh hàng trăm tin nhắn.
*   **Phân tích không khí nhóm (`/vibe`, `/who`, `/sentiment`)**: Check "nhiệt độ" phòng chat, chấm điểm cảm xúc và phân tích vai trò/tính cách của từng thành viên trong cuộc đối thoại.
*   **Chế độ thám tử (`/spy`)**: Tổng hợp nhanh những gì bạn đã bỏ lỡ khi vắng mặt, làm nổi bật các quyết định, câu hỏi chưa trả lời và các mốc thời gian quan trọng.
*   **AI Debate (`/debate`)**: Giả lập cuộc tranh luận nảy lửa giữa hai phe AI về một chủ đề bất kỳ để bạn có cái nhìn đa chiều.

### 3. 📔 Nhật Ký Thông Minh & Học Tập (AI Journaling & Language Learning)
*   **Nhật ký AI (`/journal`, `/summary`)**: Tự động hẹn giờ nhắc nhở viết nhật ký. AI phân tích tâm trạng (sentiment), gắn tag chủ đề, và viết bản tổng kết tuần/tháng để thấu hiểu bản thân.
*   **Học ngoại ngữ hàng ngày (`/vocab`, `/quiz`)**: Tự học từ vựng hữu ích qua 3 ngôn ngữ Anh - Trung - Nhật, tích hợp **phát âm chuẩn (TTS)** và làm **Quiz trắc nghiệm** tương tác để ôn tập.

### 4. 🛠️ Trợ Lý Dự Án & Nghiệp Vụ (Jira Integration & SRS RAG)
*   **Tra cứu Jira (`/jira`, `/missing_logwork`)**: Tra cứu thông tin task nhanh chóng. Tự động kiểm tra và nhắc nhở những thành viên quên logwork trên Jira.
*   **Đánh giá rủi ro (`/jira_risk`)**: AI phân tích mô tả task, bình luận để cảnh báo rủi ro chậm deadline hoặc nghẽn cổ chai.
*   **Phân tích nghiệp vụ với SRS (`/jira_analyze`)**: Nạp tài liệu đặc tả nghiệp vụ (SRS) bằng lệnh `/jira_srs_upload`. Khi phân tích một Jira task, AI sẽ tự động đối chiếu với đặc tả SRS liên quan để thiết kế giải pháp kỹ thuật và lên checklist kiểm thử.
*   **Ước lượng thời gian làm việc (`/estimate`, `/jira_estimate`)**: AI tự động so sánh task Jira hiện tại hoặc mô tả yêu cầu công việc với dữ liệu các task DONE lịch sử trong dự án để đưa ra báo cáo ước lượng thời gian (estimate) chi tiết.
*   **Báo cáo hiệu suất dev tuần (`/report`, `/jira_report`)**: Tổng hợp hoạt động làm việc trong tuần của một developer (hoặc bản thân), bao gồm danh sách task đã giải quyết, task đang làm và tổng thời gian logwork. AI sẽ phân tích hiệu suất và chỉ ra rủi ro dự án.
*   **Thiết kế kiến trúc hệ thống (`/arch`, `/arch_design`)**: Cho phép bạn nhập yêu cầu tính năng, AI sẽ tìm kiếm thông tin nghiệp vụ SRS liên quan (qua RAG) và đóng vai trò Solution Architect thiết kế tài liệu cấu trúc hệ thống chuyên nghiệp.

### 5. 🔍 Tự Động Hóa DevOps & Code Review (GitLab & Releases)
*   **AI Code Review (`/review`, `/review_full`)**: Đọc code thay đổi (diff) hoặc toàn bộ nội dung file từ link GitLab Merge Request (MR). AI sẽ phát hiện lỗi bảo mật, tối ưu thuật toán và đề xuất code tinh chỉnh.
*   **Automated Release (`/release`, `/release_mr`)**: Tự động merge MR từ `dev` sang `master`, quét các commits để AI soạn thảo Release Notes chuyên nghiệp và tạo tag phiên bản mới trên GitLab chỉ với 1 click xác nhận.
*   **Trigger CICD theo Branch (`/cicd_branch`)**: Giao diện tương tác trực quan cho phép bạn chọn branch (tự động load danh sách từ GitLab hoặc nhập tay), sau đó parse file `pubspec.yaml` để bạn chỉnh sửa Version của ứng dụng, Git Ref của các dependency, viết Commit message rồi đẩy trực tiếp lên GitLab API để trigger CI/CD pipeline tự động.

### 6. 📦 Quản Lý Build & Deploy (Dev & QA Deployment)
*   **Quản lý phiên bản (`/build_version`)**: Hệ thống quản lý các App, lưu lịch sử bản build (icon, link TestFlight, file APK, ghi chú thay đổi).
*   **Trigger Deployment**: Bấm nút triển khai (Deploy) ngay trên Telegram để tự động chạy các script CI/CD hoặc shell script deploy sản phẩm.

### 7. 🐳 Trình Quản Trị Hệ Thống (Docker Controller)
*   **Docker Panel (`/docker`)**: Dashboard quản lý các container Docker trực quan. Xem trạng thái realtime, bật, tắt, khởi động lại, xem log container và kích hoạt kéo image mới để **re-deploy** ngay lập tức.

### 8. 🖥️ OS World Agent & Remote Desktop (Điều Khiển Máy Tính Từ Xa)
*   **Screenshot & Shell (`/screen`, `/cmd`)**: Chụp ảnh màn hình máy tính đang chạy bot thời gian thực và thực thi các lệnh Terminal (bash/zsh) một cách an toàn.
*   **OS Automation (`/control`)**: Gửi yêu cầu bằng ngôn ngữ tự nhiên (ví dụ: *"Mở Chrome tìm kiếm thời tiết"*), AI sẽ phân tích ảnh màn hình và tự động thực hiện các thao tác di chuột, click, gõ phím.
*   **Thao tác thủ công (`/click`, `/type`, `/press`, `/hotkey`)**: Điều khiển chuột và bàn phím máy tính từ xa qua các lệnh Telegram.

### 9. 📋 Ủy Thác Nghiên Cứu Chạy Ngầm (AI Task Delegator)
*   **Nghiên cứu sâu (`/delegate`, `/delegates`)**: Khi cần nghiên cứu một chủ đề phức tạp, hãy ủy thác cho Agent chạy ngầm. AI sẽ tự động duyệt web, thu thập thông tin và trả về một bản báo cáo chi tiết, chuyên sâu sau vài phút mà không làm nghẽn bot chính.

### 10. 🌐 Cào & Tóm Tắt Liên Kết (Scraper & YouTube Summarizer)
*   **Tóm tắt link (`/sumlink`)**: Cào dữ liệu bài viết từ website hoặc transcript của video YouTube và tóm tắt lại.
*   **Nạp vào bộ não**: Cho phép lưu nhanh bản tóm tắt hoặc toàn bộ bài viết đã cào vào Bộ não cá nhân (RAG) chỉ bằng 1 nút bấm để truy vấn lại sau này.

### 11. 🦊 Tra Cứu API & Codebase Explorer (Local & Remote SCM)
*   **Tra cứu nhanh API (`/search_code`, `/search_api`)**: Bạn chọn một repository (chương trình hỗ trợ cả folder local lẫn lấy remote qua GitLab API) và gõ từ khóa tìm kiếm (hàm, endpoint, class, param).
*   **Tạo báo cáo Webview**: Bot tìm kiếm các tệp mã nguồn liên quan và gọi AI phân tích toàn diện, sau đó xuất ra một trang Webview Telegraph vô cùng trực quan và dễ đọc để review nhanh.

### 13. 🤖 Robot Lập Trình Tự Động (Coding Agent)
*   **Lập trình tự động (`/code <yêu cầu>`)**: Thực hiện các yêu cầu code, debug, refactor trực tiếp trên mã nguồn dự án bằng cách sử dụng bộ công cụ thông minh qua Google Antigravity SDK hoặc Local OpenCode Server. Bạn có thể chat trực tiếp với bot để kích hoạt nhanh Agent.
*   **Chế độ phê duyệt an toàn (`/interactive`)**: Khi được kích hoạt, mọi hành động gọi công cụ sửa đổi file hoặc chạy Terminal Command của AI Agent đều phải qua bạn phê duyệt thủ công (nút bấm Approve / Deny) giúp kiểm soát hoàn toàn hệ thống.
*   **Hủy tác vụ khẩn cấp (`/abort` & `/reset`)**: Lệnh `/abort` để dừng ngay lập tức Agent khi đang chạy và lệnh `/reset` để làm sạch toàn bộ ngữ cảnh/lịch sử cũ để bắt đầu tác vụ mới.


---

## 🛠 Danh Sách Lệnh (Commands)

### 1. Bot Chính (Main Bot)

| Nhóm | Lệnh | Chức năng |
| :--- | :--- | :--- |
| **Phân Tích Chat** | `/chats` | Liệt kê các cuộc hội thoại/nhóm chat |
| | `/sum [N]` | Tóm tắt nhanh N tin nhắn gần nhất |
| | `/tldr` | Tóm tắt cực ngắn nội dung chat |
| | `/vibe` | Phân tích không khí & cảm xúc phòng chat |
| | `/who` | Phân tích ai nói nhiều nhất và cá tính của họ |
| | `/search [key]` | Tìm kiếm nội dung chat theo từ khóa |
| | `/sentiment` | Chấm điểm cảm xúc các tin nhắn gần nhất |
| | `/draft [ý]` | AI soạn thảo hộ tin nhắn phản hồi |
| | `/reply [tên]` | AI đề xuất cách trả lời tin nhắn của ai đó |
| | `/debate A vs B`| Giả lập cuộc tranh biện AI giữa 2 luồng quan điểm |
| | `/spy` | Tổng hợp tin nhắn bỏ lỡ khi vắng mặt |
| **Bộ Não & RAG** | `/ask` / `/brain`| Vào chế độ chat & truy vấn dữ liệu đã học (RAG) |
| | `/save [text]` | Lưu trực tiếp ghi chú/kiến thức vào bộ não |
| | *Gửi File/Ảnh* | Nhấn nút "Học file này" để bot tự lập chỉ mục tài liệu |
| **Tra Cứu Code** | `/search_code` / `/search_api` | Tra cứu codebase, API, tham số (Cục bộ & GitLab) |
| **Nghiên Cứu** | `/delegate [ý]` | Tạo task nghiên cứu chạy ngầm chuyên sâu |
| | `/delegates` | Xem danh sách các task nghiên cứu đang chạy/hoàn thành |
| **Nhật Ký & Học**| `/journal [text]`| Ghi nhật ký nhanh trong ngày |
| | `/vocab` | Xem từ vựng hôm nay + phát âm chuẩn (TTS) |
| | `/quiz` | Làm bài trắc nghiệm nhanh từ vựng đã học |
| | `/streak` | Xem chuỗi ngày viết nhật ký liên tiếp |
| | `/history` | Xem lại các trang nhật ký cũ |
| | `/summary` | AI viết bản tổng kết nhật ký tuần qua |
| **Hệ Thống** | `/settime HH:mm`| Thay đổi khung giờ nhắc nhở nhật ký hàng ngày |
| | `/checkjobs` | Xem danh sách các job lịch trình đang hoạt động |
| | `/docker` | Bảng điều khiển quản lý container Docker |
| | `/calc [biểu thức]`| Tính toán biểu thức toán học an toàn (ví dụ: `/calc 1+2*3`) |
| **OS Agent** | `/screen` | Chụp và gửi ảnh màn hình máy tính realtime |
| | `/cmd [lệnh]` | Thực thi lệnh Shell (bash/zsh) trên máy |
| | `/control [ý]` | AI tự động điều khiển máy tính theo yêu cầu |
| | `/stop` | Dừng khẩn cấp hành động tự động của OS Agent |
| | `/click x y` | Click chuột thủ công vào tọa độ x, y |
| | `/type [text]` | Gõ phím chuỗi văn bản |
| | `/press [key]` | Nhấn một phím trên bàn phím (ví dụ: `enter`) |
| | `/hotkey [keys]`| Nhấn tổ hợp phím (ví dụ: `command space`) |
| **AI Chat 1-1** | `/chat [câu]` | Chat nhanh 1-1 với AI ngoài ngữ cảnh RAG |
| | `/endchat` | Thoát khỏi chế độ chat 1-1 |

### 2. Bot Phụ (Jira & DevOps Bot)

| Nhóm | Lệnh | Chức năng |
| :--- | :--- | :--- |
| **Jira & SRS** | `/jira [mã]` | Xem nhanh thông tin chi tiết của task trên Jira |
| | `/jira_risk [mã]`| AI phân tích rủi ro chậm deadline của task |
| | `/missing_logwork` / `/logwork`| Tra cứu các task chưa logwork đủ tuần này |
| | `/jira_estimate` / `/estimate`| AI phân tích & đề xuất estimate dựa trên các task Done mẫu |
| | `/jira_report` / `/report`| AI lập báo cáo hiệu suất dev tuần và đánh giá rủi ro |
| | `/arch` / `/arch_design` / `/jira_arch`| AI Architect thiết kế giải pháp kiến trúc đối chiếu SRS RAG |
| | `/jira_srs_upload`| Bắt đầu phiên gửi file đặc tả nghiệp vụ SRS để AI học |
| | `/jira_srs_list` | Giao diện Dashboard xem và xóa tài liệu SRS đã nạp |
| | `/jira_srs_delete`| Xóa một tài liệu đặc tả nghiệp vụ theo tên |
| | `/jira_analyze [mã]`| AI đối chiếu SRS để thiết kế giải pháp kỹ thuật & checklist |
| **Code Explorer** | `/search_code` / `/search_api` | Tra cứu codebase, API, tham số (Cục bộ & GitLab) |
| **Code Review** | `/review [linkMR]`| AI review diff code thay đổi của Merge Request GitLab |
| | `/review_full [link]`| AI review toàn bộ nội dung file có thay đổi trong MR |
| | `/release_mr [link]`| AI phân tích commits để lập đề xuất Release Notes |
| **Release & Build**| `/release` | Khởi chạy quy trình merge tự động & tạo tag release |
| | `/cicd_branch` | Cấu hình branch, sửa version & ref để trigger GitLab CI/CD |
| | `/build_version`| Dashboard quản lý App, lưu lịch sử build & trigger deploy |
| **System** | `/docker` | Bảng điều khiển Docker container (chạy trên Bot Jira) |
| | `/delegate` | Ủy thác nghiên cứu chạy ngầm (chạy trên Bot Jira) |

### 3. Bot Agent (Coding Agent)

| Nhóm | Lệnh | Chức năng |
| :--- | :--- | :--- |
| **Workspace & Repo** | `/repo` / `/setrepo` | Hiển thị danh sách các repository cục bộ để chọn workspace làm việc |
| **Lập Trình AI** | `/code [yêu cầu]` | Kích hoạt Coding Agent thực hiện yêu cầu lập trình (hoặc reply tin nhắn + `/code`) |
| | `/abort` | Dừng khẩn cấp tác vụ Coding Agent đang chạy |
| | `/reset` | Xóa sạch lịch sử/context cũ của phiên làm việc hiện tại |
| | `/interactive` | Bật/Tắt chế độ phê duyệt thủ công từng công cụ (Approve / Deny) |
| **Chat Trực Tiếp** | *Tin nhắn thường* | Trong chat 1-1, gửi tin nhắn văn bản sẽ tự động kích hoạt Agent xử lý |

---

## 📁 Cấu Trúc Thư Mục Dự Án

```text
.
├── main.py                     # Điểm khởi chạy hệ thống (chạy đồng thời Telethon + 3 PTB Bots)
├── config.py                   # Đọc và quản lý tất cả cấu hình môi trường (.env)
├── setup_session.py            # Script chạy 1 lần để đăng nhập Telethon và lấy SESSION_STRING
├── requirements.txt            # Danh sách thư viện Python cần thiết
├── Dockerfile                  # Cấu hình đóng gói Docker image cho ứng dụng
├── docker-compose.yml          # Cấu hình chạy ứng dụng bằng Docker Compose
├── deploy.sh                   # Script hỗ trợ deploy ứng dụng nhanh
├── handlers/                   # Chứa logic xử lý các lệnh Telegram (Handlers)
│   ├── commands.py             # Logic chat analysis, Jira, GitLab, Code Review, Release
│   ├── journal.py              # Logic nhật ký (Journal), Vocab, Quiz trắc nghiệm
│   ├── brain.py                # Logic RAG bộ não kiến thức, xử lý file/ảnh tài liệu nạp vào db
│   ├── build.py                # Dashboard quản lý các bản Build, App Versioning & Deploy
│   ├── computer.py             # OS Agent điều khiển máy tính, click, type, screenshot, control
│   ├── delegate_handler.py     # Quản lý các task nghiên cứu chạy ngầm (AI Task Delegator)
│   ├── docker_handler.py       # Quản trị Docker container trực quan qua nút bấm
│   ├── cicd_branch.py          # Quy trình CI/CD theo branch, sửa version & ref trực tiếp qua GitLab API
│   ├── code_search.py          # Tra cứu codebase, API, tham số cục bộ/remote và viết tài liệu qua AI
│   ├── agent_bot.py            # Logic Coding Agent kết nối Google Antigravity SDK & OpenCode local
│   ├── calculator.py           # Tính toán biểu thức toán học an toàn
│   └── scraper.py              # Cào dữ liệu bài viết, YouTube và tóm tắt link gửi private
├── services/                   # Chứa các dịch vụ nền và API kết nối (Services)
│   ├── summarizer.py           # Core gọi LLM (Gemini API) để tóm tắt, review, lập báo cáo
│   ├── brain_service.py        # Logic truy vấn RAG bộ não cá nhân
│   ├── journal_db.py           # Quản lý SQLite cho nhật ký, cài đặt người dùng, RAG knowledge
│   ├── build_db.py             # SQLite lưu trữ danh sách App, phiên bản Build & Deploy
│   ├── search_service.py       # Tìm kiếm FTS5 hỗ trợ RAG tài liệu nghiệp vụ
│   ├── code_search.py          # Hỗ trợ tìm kiếm, định tuyến repository cục bộ và gọi AI phân tích API/codebase
│   ├── opencode_service.py     # Giao tiếp API với Local OpenCode.ai Server
│   ├── telegraph_api.py        # Tích hợp Telegraph API để publish các báo cáo phân tích dài thành trang webview dễ đọc
│   ├── fetcher.py              # Sử dụng Telethon thu thập tin nhắn từ group Telegram và đồng bộ lượt tag (owner mentions)
│   ├── jira_api.py             # Kết nối API Jira (lấy ticket, kiểm tra logwork, rủi ro)
│   ├── gitlab_api.py           # Kết nối API GitLab (lấy diff, commits, merge MR, tạo tag)
│   ├── docker_service.py       # Giao tiếp với Docker Engine (start/stop/logs/redeploy container)
│   ├── os_agent.py             # Logic xử lý hành động OS (click, gõ phím, tổ hợp phím)
│   ├── scraper_service.py      # Cào trang web, lấy phụ đề YouTube tự động
│   ├── journal_ai.py           # AI phân tích nhật ký (tâm trạng, chủ đề)
│   ├── journal_quiz.py         # AI sinh câu hỏi Quiz từ vựng
│   ├── journal_scheduler.py    # Lên lịch nhắc nhở nhật ký tự động hàng ngày
│   ├── telegram_utils.py       # Các hàm tiện ích gửi/sửa tin nhắn Telegram an toàn
│   ├── markdown.py             # Định dạng và escape ký tự đặc biệt cho Telegram HTML/MDV2
│   ├── vocab_ai.py             # Sinh từ vựng học ngoại ngữ mỗi ngày
│   └── tts.py                  # Chuyển đổi văn bản thành giọng nói (phát âm từ vựng)
├── questions/                  # Ngân hàng câu hỏi gợi ý viết nhật ký
├── data/                       # Thư mục lưu trữ cơ sở dữ liệu SQLite (journal.db, build.db, agent_sessions)
└── scratch/                    # Thư mục chứa các file tạm thời trong quá trình hoạt động
```

---

## 🚀 Hướng Dẫn Cài Đặt Nhanh

### 1. Chuẩn bị tài khoản
1. Truy cập [my.telegram.org](https://my.telegram.org) để lấy `TELEGRAM_API_ID` và `TELEGRAM_API_HASH` của tài khoản cá nhân (dành cho Telethon đọc lịch sử chat).
2. Chat với `@BotFather` trên Telegram để tạo 3 bot mới:
   *   **Main Bot** -> lấy `BOT_TOKEN`.
   *   **Jira Bot** -> lấy `BOT_JIRA_TOKEN`.
   *   **Agent Bot** -> lấy `BOT_AGENT_TOKEN`.
3. Lấy API Key miễn phí từ [Google AI Studio](https://aistudio.google.com/app/apikey) điền vào `GEMINI_API_KEY`.
4. Nhắn tin cho `@userinfobot` để lấy ID Telegram của bạn điền vào `ALLOWED_USER_IDS` (nhằm bảo mật hệ thống, chỉ cho phép bạn sử dụng).

### 2. Cấu hình File Môi Trường
Sao chép `.env.example` thành `.env` và điền đầy đủ các thông tin:
```bash
cp .env.example .env
nano .env
```

**Các biến cấu hình quan trọng cần lưu ý:**
*   `BOT_USERNAME`: Username của Main Bot (không bao gồm dấu `@`), dùng để lắng nghe sự kiện bot bị tag trong nhóm chat.
*   `OWNER_USERNAME`: Username Telegram của bạn (không bao gồm dấu `@`), giúp Telethon phát hiện khi bạn bị tag trong các nhóm chat để gửi cảnh báo kèm gợi ý phản hồi về private bot.
*   `ALLOWED_USER_IDS`: Danh sách ID Telegram của bạn (và những người được phép dùng bot), phân tách bằng dấu phẩy.
*   `BOT_AGENT_TOKEN`: Token của Coding Agent Bot vừa tạo ở trên.
*   `USE_LOCAL_OPENCODE` & `OPENCODE_LOCAL_URL`: Thiết lập thành `true` và trỏ URL nếu bạn muốn sử dụng Local OpenCode Server thay thế cho Gemini API trong việc chạy Agent lập trình.
*   `JIRA_BASE_URL` & `JIRA_PAT`: Địa chỉ Jira Server của công ty và Personal Access Token của bạn để thực hiện các chức năng về task Jira, logwork, estimate và Solution Architect.
*   `GITLAB_PAT`: Personal Access Token GitLab có quyền write/api để AI Code Review, tự động release và chạy CI/CD theo branch.

### 3. Tạo Session Telegram (Chỉ chạy 1 lần duy nhất)
Để Telethon có quyền đọc lịch sử nhóm chat dưới danh nghĩa tài khoản của bạn, hãy chạy script sau:
```bash
python setup_session.py
```
Nhập số điện thoại đăng ký Telegram và mã xác nhận gửi về ứng dụng của bạn. Sau khi đăng nhập thành công, script sẽ sinh ra một chuỗi dài. Hãy copy chuỗi này và điền vào biến `SESSION_STRING` trong file `.env`.

### 4. Khởi chạy Hệ Thống

**Cách 1: Chạy bằng Docker Compose (Khuyên dùng - cực nhanh và ổn định)**
```bash
docker compose up -d
```

**Cách 2: Chạy trực tiếp trên máy**
```bash
# Tạo môi trường ảo
python -m venv venv
source venv/bin/activate

# Cài đặt thư viện
pip install -r requirements.txt

# Chạy ứng dụng
python main.py
```

---

## 🔐 Bảo Mật & Whitelist
*   **Session String & API Tokens**: File `.env` chứa toàn bộ khóa quyền lực truy cập tài khoản Telegram và hệ thống nội bộ của bạn. **TUYỆT ĐỐI KHÔNG** chia sẻ hoặc commit file này lên GitHub.
*   **Whitelist (`ALLOWED_USER_IDS`)**: Hệ thống tự động kiểm tra ID người dùng gửi lệnh. Chỉ những ID nằm trong danh sách whitelist mới có quyền tương tác với bot. Bất kỳ tin nhắn nào từ người lạ sẽ bị bot từ chối ngay lập tức để bảo vệ an toàn cho máy tính và hệ thống của bạn.

---
*Phát triển và nâng cấp toàn diện bởi [Hung Cuong](https://github.com/hungcuong1995ag-wq)*
