import os
import subprocess
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
import pyautogui
from PIL import ImageGrab
import io

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mac_helper")

# Tắt fail-safe của pyautogui nếu muốn (được khuyến khích nếu bot chạy từ xa không cần fail-safe cản trở)
pyautogui.FAILSAFE = False

app = FastAPI(title="macOS Control Helper")

class ClickRequest(BaseModel):
    x: int
    y: int

class TypeRequest(BaseModel):
    text: str

class PressRequest(BaseModel):
    key: str

class HotkeyRequest(BaseModel):
    keys: list[str]

class CmdRequest(BaseModel):
    command: str

class AppleScriptRequest(BaseModel):
    script: str

@app.get("/screenshot")
def get_screenshot():
    try:
        # Chụp màn hình
        screenshot = ImageGrab.grab()
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return Response(content=img_byte_arr.getvalue(), media_type="image/png")
    except Exception as e:
        logger.error(f"Error capturing screenshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/click")
def post_click(req: ClickRequest):
    try:
        pyautogui.click(req.x, req.y)
        logger.info(f"Clicked at coordinates: ({req.x}, {req.y})")
        return {"status": "success", "message": f"Clicked at ({req.x}, {req.y})"}
    except Exception as e:
        logger.error(f"Error performing click: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/type")
def post_type(req: TypeRequest):
    try:
        # Sử dụng pyautogui.write để nhập văn bản
        pyautogui.write(req.text, interval=0.01)
        logger.info(f"Typed text: {req.text}")
        return {"status": "success", "message": f"Typed text successfully"}
    except Exception as e:
        logger.error(f"Error performing typing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/press")
def post_press(req: PressRequest):
    try:
        pyautogui.press(req.key)
        logger.info(f"Pressed key: {req.key}")
        return {"status": "success", "message": f"Pressed key {req.key}"}
    except Exception as e:
        logger.error(f"Error pressing key: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/hotkey")
def post_hotkey(req: HotkeyRequest):
    try:
        pyautogui.hotkey(*req.keys)
        logger.info(f"Pressed hotkeys: {req.keys}")
        return {"status": "success", "message": f"Pressed hotkeys {req.keys}"}
    except Exception as e:
        logger.error(f"Error pressing hotkey: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cmd")
def post_cmd(req: CmdRequest):
    try:
        logger.info(f"Executing command: {req.command}")
        res = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "status": "success" if res.returncode == 0 else "failed",
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
    except subprocess.TimeoutExpired:
        logger.error(f"Command execution timed out: {req.command}")
        return {
            "status": "failed",
            "returncode": -1,
            "stdout": "",
            "stderr": "Command execution timed out (60s limit)"
        }
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/applescript")
def post_applescript(req: AppleScriptRequest):
    try:
        logger.info(f"Executing AppleScript: {req.script}")
        # Chạy script qua osascript
        res = subprocess.run(
            ['osascript', '-e', req.script],
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "status": "success" if res.returncode == 0 else "failed",
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
    except subprocess.TimeoutExpired:
        logger.error("AppleScript execution timed out")
        return {
            "status": "failed",
            "returncode": -1,
            "stdout": "",
            "stderr": "AppleScript execution timed out (60s limit)"
        }
    except Exception as e:
        logger.error(f"Error executing AppleScript: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Bind to all interfaces so docker container can call host.docker.internal:8088
    uvicorn.run(app, host="0.0.0.0", port=8088)
