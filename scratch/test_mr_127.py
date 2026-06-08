import sys
import os
import asyncio
import logging

# Thêm thư mục hiện tại vào path
sys.path.append(os.getcwd())

from services import gitlab_api, summarizer

logging.basicConfig(level=logging.INFO)

async def test_mr_127():
    mr_link = "https://scm.devops.vnpt.vn/it5.ptgp.digo/vncitizens/zalominiapp.vncitizens/-/merge_requests/127"
    print(f"Testing MR: {mr_link}")
    
    mr_data = await gitlab_api.get_mr_diff(mr_link)
    if mr_data.get("error"):
        print(f"GitLab Error: {mr_data['error']}")
        return
        
    print(f"Success! Title: {mr_data['title']}")
    print(f"Diff length: {len(mr_data['diff'])} chars")
    
    print("\nCalling AI for review...")
    review_result = summarizer.review_code_changes(mr_data['diff'])
    
    print("\n--- RAW AI REVIEW RESULT ---")
    print(review_result)
    
    from services.markdown import ai_to_mdv2
    html_out = ai_to_mdv2(review_result)
    
    print("\n--- HTML OUTPUT ---")
    print(html_out)

if __name__ == "__main__":
    asyncio.run(test_mr_127())
