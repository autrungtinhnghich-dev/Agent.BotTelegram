import os
import logging
import requests
import json
import re
from PIL import Image
import io
from google import genai
import config

logger = logging.getLogger(__name__)

HELPER_BASE_URL = "http://host.docker.internal:8088"

# Khởi tạo Client cho Google GenAI SDK mới
client = None
if config.GEMINI_API_KEY:
    client = genai.Client(api_key=config.GEMINI_API_KEY)

def get_screenshot() -> Image.Image:
    """Gọi helper để chụp ảnh màn hình và trả về đối tượng PIL Image."""
    url = f"{HELPER_BASE_URL}/screenshot"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except Exception as e:
        logger.error(f"Failed to fetch screenshot from host helper: {e}")
        raise

def execute_helper_action(action: str, params: dict) -> dict:
    """Gửi hành động điều khiển đến helper."""
    url = f"{HELPER_BASE_URL}/{action}"
    try:
        response = requests.post(url, json=params, timeout=65)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to execute action {action} on host helper: {e}")
        return {"status": "failed", "error": str(e)}

def parse_ui_action(user_instruction: str, history: list = None) -> dict:
    """
    Chụp ảnh màn hình, gửi đến Gemini Vision kèm theo yêu cầu của người dùng,
    và trả về hành động tiếp theo cần thực hiện dưới dạng dict.
    """
    try:
        # 1. Chụp ảnh màn hình
        image = get_screenshot()
        width, height = image.size

        # 2. Xây dựng prompt cho Gemini
        # Chúng ta yêu cầu Gemini trả về JSON để thực hiện hành động tiếp theo
        system_prompt = (
            "You are a macOS computer control agent. Your goal is to help the user achieve their task by analyzing "
            "the screen and outputting the next single action. "
            "You will be given a screenshot of the current screen and the user's overall goal, along with history of recent actions.\n\n"
            f"Current screen resolution: {width}x{height} pixels.\n\n"
            "Respond ONLY with a JSON object. Do not wrap in ```json or any other formatting. "
            "The JSON must have the following structure:\n"
            "{\n"
            '  "thought": "Your reasoning about what you see and what the next step should be",\n'
            '  "action": "click" | "type" | "press" | "hotkey" | "applescript" | "cmd" | "wait" | "done" | "failed",\n'
            '  "x": 100, // (only for "click" action: absolute X pixel coordinate on the screen)\n'
            '  "y": 200, // (only for "click" action: absolute Y pixel coordinate on the screen)\n'
            '  "text": "text to type", // (only for "type" action: string to input)\n'
            '  "key": "enter", // (only for "press" action: key to press, e.g. enter, space, tab, backspace, esc)\n'
            '  "keys": ["command", "space"], // (only for "hotkey" action: list of keys to press together)\n'
            '  "script": "AppleScript code", // (only for "applescript" action: AppleScript string to run via osascript)\n'
            '  "command": "terminal command", // (only for "cmd" action: terminal command to run)\n'
            '  "message": "Final confirmation message for user" // (only for "done" or "failed" actions)\n'
            "}\n\n"
            "Rules:\n"
            "1. Only perform ONE action at a time.\n"
            "2. If you need to search or open an app, prefer using the Command+Space hotkey to open Spotlight search, type the app name, and press enter. Or use Applescript.\n"
            "3. If the task is finished, use action 'done'. If you are stuck or cannot proceed, use action 'failed'.\n"
            "4. Be very precise with coordinates. Remember the resolution of the screen."
        )

        history_str = ""
        if history:
            history_str = "\nAction History:\n" + "\n".join([f"- {h}" for h in history])

        user_prompt = f"User Goal: {user_instruction}\n{history_str}\n\nPlease output the next JSON action."

        # 3. Gọi Gemini API
        # Dùng model được cấu hình
        model_name = config.GEMINI_MODEL
        # Fallback về gemini-2.5-flash nếu gemini-3.5-flash bị lỗi hoặc không hỗ trợ
        try:
            # Khởi tạo client dự phòng nếu chưa có
            global client
            if not client:
                client = genai.Client(api_key=config.GEMINI_API_KEY)
            
            response = client.models.generate_content(
                model=model_name,
                contents=[image, system_prompt + "\n\n" + user_prompt]
            )
            response_text = response.text.strip()
        except Exception as e:
            logger.warning(f"Error calling configured model {model_name}: {e}. Trying fallback model gemini-2.5-flash.")
            if not client:
                client = genai.Client(api_key=config.GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[image, system_prompt + "\n\n" + user_prompt]
            )
            response_text = response.text.strip()

        logger.info(f"Gemini response: {response_text}")

        # 4. Parse JSON kết quả
        # Xóa markdown blocks nếu Gemini bao bọc JSON trong ```json ... ```
        if "```" in response_text:
            # Lấy phần text ở giữa ```json và ```
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if match:
                response_text = match.group(1)
            else:
                response_text = response_text.replace("```json", "").replace("```", "").strip()

        # Parse JSON
        action_data = json.loads(response_text)
        return action_data

    except Exception as e:
        logger.error(f"Error in parse_ui_action: {e}")
        return {
            "action": "failed",
            "message": f"Error interacting with Gemini: {str(e)}"
        }

def run_os_agent_step(user_instruction: str, history: list) -> dict:
    """Thực hiện một bước phân tích và chạy hành động tương ứng."""
    # 1. Gọi Gemini phân tích
    action_data = parse_ui_action(user_instruction, history)
    action = action_data.get("action")
    thought = action_data.get("thought", "")

    logger.info(f"Thought: {thought} | Action: {action}")

    # 2. Thực thi hành động tương ứng thông qua helper
    result = {"action": action, "thought": thought, "raw_action": action_data}
    
    if action in ["click", "type", "press", "hotkey", "cmd", "applescript"]:
        # Chuẩn bị params
        params = {}
        if action == "click":
            params = {"x": action_data.get("x"), "y": action_data.get("y")}
        elif action == "type":
            params = {"text": action_data.get("text")}
        elif action == "press":
            params = {"key": action_data.get("key")}
        elif action == "hotkey":
            params = {"keys": action_data.get("keys")}
        elif action == "cmd":
            params = {"command": action_data.get("command")}
        elif action == "applescript":
            params = {"script": action_data.get("script")}
            
        exec_result = execute_helper_action(action, params)
        result["execution"] = exec_result
        
        # Tạo mô tả lịch sử
        if action == "click":
            step_desc = f"Clicked at ({params['x']}, {params['y']})"
        elif action == "type":
            step_desc = f"Typed '{params['text']}'"
        elif action == "press":
            step_desc = f"Pressed key '{params['key']}'"
        elif action == "hotkey":
            step_desc = f"Pressed hotkey {params['keys']}"
        elif action == "cmd":
            step_desc = f"Ran command: {params['command']} (Status: {exec_result.get('status')})"
        elif action == "applescript":
            step_desc = f"Ran AppleScript (Status: {exec_result.get('status')})"
        
        result["step_description"] = step_desc
    else:
        result["step_description"] = action_data.get("message", f"Agent state: {action}")

    return result
