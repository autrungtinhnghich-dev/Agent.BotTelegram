import os
import httpx
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv('.env')
pat = os.getenv('GITLAB_PAT')
base_url = os.getenv('GITLAB_BASE_URL', 'https://scm.devops.vnpt.vn')

projects = {
    "smarttown": "it5.ptgp.digo/vncitizens/flutter.vncitizens.smarttown",
    "vncitizens": "it5.ptgp.digo/vncitizens/flutter.vncitizens"
}

headers = {"PRIVATE-TOKEN": pat} if pat else {}

print(f"GitLab URL: {base_url}")
print(f"Token exists: {bool(pat)}")

for name, path in projects.items():
    encoded = quote_plus(path)
    url = f"{base_url}/api/v4/projects/{encoded}/repository/tags"
    print(f"\n--- {name} ({path}) ---")
    try:
        with httpx.Client(verify=False) as client:
            resp = client.get(url, headers=headers, timeout=15)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                tags = resp.json()
                if tags:
                    print("Latest 3 tags:")
                    for t in tags[:3]:
                        print(f"  Tag: {t.get('name')}, Commit: {t.get('commit', {}).get('short_id')}")
                else:
                    print("No tags found.")
            else:
                print(resp.text[:300])
    except Exception as e:
        print(f"Error: {e}")
