import json
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

app = FastAPI()
client = httpx.AsyncClient()

TARGET_URL = "http://127.0.0.1:8045"

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy(path: str, request: Request):
    url = f"{TARGET_URL}/{path}"
    
    # Get request body
    body = await request.body()
    
    # Forward headers (excluding Host)
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    
    # Forward query params
    params = dict(request.query_params)
    
    # Check if the request expects event-stream
    accept_header = request.headers.get("accept", "")
    is_stream = "text/event-stream" in accept_header
    if not is_stream and request.method == "POST" and body:
        try:
            req_data = json.loads(body.decode("utf-8", errors="ignore"))
            if req_data.get("stream") is True:
                is_stream = True
        except Exception:
            pass
    
    if is_stream:
        req = client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            params=params,
            content=body
        )
        resp = await client.send(req, stream=True)
        
        async def stream_generator():
            async for line in resp.aiter_lines():
                # Filter out lines containing __cloudCodeMeta
                if "__cloudCodeMeta" in line:
                    continue
                yield f"{line}\n"
                
        # Forward response headers
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ["content-length", "transfer-encoding"]}
        return StreamingResponse(stream_generator(), status_code=resp.status_code, headers=resp_headers)
    else:
        resp = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=params,
            content=body
        )
        resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in ["content-length", "transfer-encoding"]}
        return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
