import os
import httpx
import asyncio
import traceback

async def main():
    headers = {"PRIVATE-TOKEN": "qrDaDA2tsCD6Y1Y3o1Q4"}
    try:
        async with httpx.AsyncClient(verify=True) as client:
            resp = await client.get("https://scm.devops.vnpt.vn/api/v4/projects/it5.ptgp.digo%2Fvncitizens%2Fzalominiapp.vncitizens/repository/tags?limit=50", headers=headers)
            print("Tags status:", resp.status_code)
    except Exception as e:
        print("Tags error:")
        traceback.print_exc()

asyncio.run(main())
