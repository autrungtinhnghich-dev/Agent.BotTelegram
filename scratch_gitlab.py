import os
import httpx
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv('.env')
PAT = os.getenv('JIRA_PAT')

project_path = "it5.ptgp.digo/vncitizens/svc.smarttown"
encoded = quote_plus(project_path)
mr_iid = 341

url = f"https://scm.devops.vnpt.vn/api/v4/projects/{encoded}/merge_requests/{mr_iid}/changes"

print("Trying with PRIVATE-TOKEN:")
try:
    with httpx.Client(verify=False) as c:
        r1 = c.get(url, headers={"PRIVATE-TOKEN": PAT})
        print(r1.status_code, r1.text[:200])
except Exception as e:
    print(e)

print("\nTrying with Authorization: Bearer:")
try:
    with httpx.Client(verify=False) as c:
        r2 = c.get(url, headers={"Authorization": f"Bearer {PAT}"})
        print(r2.status_code, r2.text[:200])
except Exception as e:
    print(e)
