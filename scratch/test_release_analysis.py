import sys
import os
import asyncio
import logging

# Thêm thư mục hiện tại vào python path
sys.path.append(os.getcwd())

from services import gitlab_api, summarizer

logging.basicConfig(level=logging.INFO)

async def test_release_analysis():
    # Sử dụng link MR mẫu để test (có thể thay bằng link thực tế khác nếu cần)
    mr_link = "https://scm.devops.vnpt.vn/it5.ptgp.digo/vncitizens/zalominiapp.vncitizens/-/merge_requests/127"
    print(f"=== TESTING RELEASE ANALYSIS FOR MR: {mr_link} ===")
    
    # 1. Test lấy latest tag
    print("\n[1] Lấy tag mới nhất hiện tại...")
    tag_result = await gitlab_api.get_latest_project_tag(mr_link)
    if tag_result.get("error"):
        print(f"GitLab Tag Error: {tag_result['error']}")
        return
    current_tag = tag_result.get("tag")
    print(f"Tag hiện tại: {current_tag}")

    # 2. Test lấy commits
    print("\n[2] Lấy danh sách commits trong MR...")
    commits_result = await gitlab_api.get_mr_commits(mr_link)
    if commits_result.get("error"):
        print(f"GitLab Commits Error: {commits_result['error']}")
        return
    
    commits = commits_result.get("commits", [])
    print(f"Đã lấy thành công {len(commits)} commits.")
    for c in commits[:3]:
        print(f" - [{c.get('author_name')}]: {c.get('title')}")
    if len(commits) > 3:
        print(" ... và các commit khác.")

    if not commits:
        print("Không có commit nào để phân tích.")
        return

    # 3. Test gọi LLM phân tích release
    print("\n[3] Gọi AI phân tích release...")
    try:
        release_proposal = summarizer.analyze_release_commits(commits, current_tag)
        print("\n--- KẾT QUẢ ĐỀ XUẤT RELEASE TỪ AI ---")
        print(release_proposal)
    except Exception as e:
        print(f"AI Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_release_analysis())
