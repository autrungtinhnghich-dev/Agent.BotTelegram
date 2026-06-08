import asyncio
import sys
import os

# Đảm bảo import được các module của dự án
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import logging
logging.basicConfig(level=logging.INFO)

from services.gitlab_api import get_user_projects, search_remote_repository
from services.code_search import get_local_path_for_project, search_local_repository, analyze_api_with_gemini

async def test_all():
    print("--- 1. Kiểm thử lấy danh sách dự án từ SCM (GitLab) ---")
    projects = await get_user_projects(limit=5)
    print(f"Số lượng project lấy được: {len(projects)}")
    for p in projects:
        print(f"- Project: {p['name']} | Path: {p['path_with_namespace']} | ID: {p['id']}")
    
    # Lấy thử một project đang hoạt động để chạy test tiếp theo
    if not projects:
        print("⚠️ Không có dự án nào từ SCM GitLab. Bỏ qua các bước kiểm thử API GitLab.")
        return

    target_project = projects[0]
    project_id = target_project["id"]
    project_name = target_project["name"]
    project_path = target_project["path_with_namespace"]
    
    print("\n--- 2. Kiểm thử ánh xạ thư mục cục bộ ---")
    local_path = get_local_path_for_project(project_path)
    print(f"Path với namespace: {project_path}")
    print(f"Thư mục cục bộ tương ứng: {local_path or '❌ Chưa clone cục bộ'}")

    # Chúng ta sử dụng chính repo AI.BotTelegram cục bộ để test search cục bộ
    test_local_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print(f"\n--- 3. Kiểm thử quét code cục bộ (trong repo bot hiện tại: {test_local_repo}) ---")
    test_kw = "GEMINI_API_KEY"
    results = search_local_repository(test_local_repo, test_kw, limit=2)
    print(f"Số lượng file khớp cục bộ với từ khóa '{test_kw}': {len(results)}")
    for r in results:
        print(f"- File khớp: {r['file_path']} (Độ dài code: {len(r['content'])} ký tự)")

    print(f"\n--- 4. Kiểm thử tìm kiếm từ xa qua GitLab API cho project '{project_name}' ---")
    remote_kw = "api"
    remote_results = await search_remote_repository(project_id, remote_kw, limit=1)
    print(f"Số lượng file khớp từ xa trên SCM với từ khóa '{remote_kw}': {len(remote_results)}")
    for r in remote_results:
        print(f"- File khớp từ xa: {r['file_path']} (Độ dài code: {len(r['content'])} ký tự)")

    if results:
        print("\n--- 5. Kiểm thử gọi Gemini phân tích API ---")
        # Gọi thử AI phân tích file đầu tiên khớp cục bộ
        print("Đang gọi AI phân tích thử file đầu tiên...")
        report = analyze_api_with_gemini(project_name, test_kw, [results[0]])
        print("--- KẾT QUẢ PHÂN TÍCH CỦA GEMINI ---")
        print(report[:800] + "\n... (Bản tin đã được cắt bớt trong lúc test) ...")
    else:
        print("Bỏ qua test gọi Gemini do không tìm thấy file cục bộ nào khớp.")

if __name__ == "__main__":
    asyncio.run(test_all())
