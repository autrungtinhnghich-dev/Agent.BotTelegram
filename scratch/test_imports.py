import os
import httpx
import asyncio

async def test_conn(label):
    headers = {"PRIVATE-TOKEN": "qrDaDA2tsCD6Y1Y3o1Q4"}
    try:
        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.get("https://scm.devops.vnpt.vn/api/v4/projects/it5.ptgp.digo%2Fvncitizens%2Fzalominiapp.vncitizens/repository/tags?limit=50", headers=headers)
            print(f"[{label}] Success:", resp.status_code)
    except Exception as e:
        print(f"[{label}] Error:", type(e).__name__, e)

async def main():
    await test_conn("Before imports")
    
    print("Importing config...")
    import config
    await test_conn("After config")
    
    print("Importing requests...")
    import requests
    await test_conn("After requests")
    
    print("Importing gitlab_api...")
    from services import gitlab_api
    await test_conn("After gitlab_api")
    
    print("Importing summarizer...")
    from services import summarizer
    await test_conn("After summarizer")

asyncio.run(main())
