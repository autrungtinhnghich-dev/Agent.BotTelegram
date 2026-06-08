import os
import httpx
from dotenv import load_dotenv

load_dotenv('.env')

JIRA_BASE_URL = os.getenv('JIRA_BASE_URL', '').rstrip('/')
JIRA_PAT = os.getenv('JIRA_PAT')

url = f"{JIRA_BASE_URL}/rest/api/2/issue/G038-18744"
headers = {"Authorization": f"Bearer {JIRA_PAT}"}

print(f"Fetching {url}")
try:
    with httpx.Client(verify=False) as client:
        r = client.get(url, headers=headers)
        print("Status:", r.status_code)
        if r.status_code == 200:
            data = r.json()
            fields = data.get('fields', {})
            print("Summary:", fields.get('summary'))
            print("Status:", fields.get('status', {}).get('name'))
        else:
            print(r.text[:500])
except Exception as e:
    print("Error:", e)
