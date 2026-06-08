import asyncio
import os
import sys

# Thêm thư mục gốc vào path để import các dịch vụ
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv('.env')

# Ghi đè LLM_API_URL sang localhost để test local trên máy Mac
import os
os.environ['LLM_API_URL'] = 'http://127.0.0.1:8045/v1/chat/completions'

from services.jira_api import get_issue_full, get_active_issues
from services.summarizer import analyze_jira_issue_risk
from services.journal_db import init_db

async def main():
    print("Khởi tạo Database...")
    await init_db()
    
    print("\nLấy danh sách các task đang active trên Jira...")
    active_issues = await get_active_issues()
    print(f"Tìm thấy {len(active_issues)} active tasks.")
    for issue in active_issues[:3]:
        print(f"- {issue['key']}: {issue['summary']} (Updated: {issue['updated']})")
        
    if not active_issues:
        print("Không tìm thấy active task nào. Kết thúc kiểm thử.")
        return
        
    test_key = active_issues[0]['key']
    print(f"\n[TEST] Lấy thông tin đầy đủ cho task: {test_key}...")
    issue_data = await get_issue_full(test_key)
    if not issue_data:
        print("Không lấy được dữ liệu task. Có thể do lỗi kết nối hoặc phân quyền.")
        return
        
    print("\nDữ liệu task lấy được:")
    print(f"Key: {issue_data['key']}")
    print(f"Summary: {issue_data['summary']}")
    print(f"Assignee: {issue_data['assignee']}")
    print(f"Status: {issue_data['status']}")
    print(f"Comments count: {len(issue_data['comments'])}")
    print(f"History transitions: {len(issue_data['status_history'])}")
    
    print(f"\n[TEST] Gọi AI Phân tích rủi ro trễ hạn...")
    analysis = analyze_jira_issue_risk(issue_data)
    
    print("\n[AI ANALYSIS RESULT]")
    print(f"Risk Level: {analysis.get('risk_level')}")
    print(f"Risk Score: {analysis.get('risk_score')}%")
    print("Reasons:")
    for r in analysis.get('reasons', []):
        print(f"  - {r}")
    print("Recommendations:")
    for rec in analysis.get('recommendations', []):
        print(f"  - {rec}")
    print("\nMarkdown Report Preview:")
    print(analysis.get('markdown_report'))

if __name__ == "__main__":
    asyncio.run(main())
