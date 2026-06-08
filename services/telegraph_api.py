"""
services/telegraph_api.py

Dịch vụ đăng tải báo cáo/đặc tả lên Telegra.ph để hiển thị Webview Instant View cao cấp trên Telegram.
"""

import logging
import requests
import json
from bs4 import BeautifulSoup
from services.markdown import ai_to_mdv2

logger = logging.getLogger(__name__)

# Cache access token để tránh tạo tài khoản mới liên tục
_telegraph_access_token = None

def get_access_token() -> str:
    """Tạo hoặc lấy access token của Telegraph đã lưu."""
    global _telegraph_access_token
    if _telegraph_access_token:
        return _telegraph_access_token
        
    try:
        acc_url = "https://api.telegra.ph/createAccount?short_name=AIBot&author_name=AI_Solution_Architect"
        res = requests.get(acc_url, timeout=15).json()
        if res.get("ok") and "access_token" in res.get("result", {}):
            _telegraph_access_token = res["result"]["access_token"]
            logger.info("Đã tạo tài khoản Telegraph mới và lưu access token.")
            return _telegraph_access_token
    except Exception as e:
        logger.error(f"Lỗi khi tạo tài khoản Telegraph: {e}")
        
    # Token dự phòng mặc định nếu API lỗi
    return "9c8016b1b1e1c2d9db87962fa53ddc1686dbd3b7dd46f4a1e19f5c5caca6"

def html_to_nodes(element):
    """Chuyển đổi thẻ BeautifulSoup HTML sang cấu trúc Telegraph Node."""
    if element is None:
        return ""
    if isinstance(element, str):
        return element
    if getattr(element, "name", None) is None:
        return str(element)
    
    tag = element.name.lower()
    
    # Danh sách các tag được hỗ trợ chính thức bởi Telegraph
    supported_tags = {
        "a", "aside", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h3", "h4", "hr", "i", "iframe", "img", "li", "ol", "p", "pre", "s", "strong", "u", "ul", "video"
    }
    
    # Map các thẻ không được hỗ trợ sang thẻ tương đương
    if tag not in supported_tags:
        if tag in ("h1", "h2"):
            tag = "h3"
        elif tag in ("h5", "h6"):
            tag = "h4"
        elif tag in ("div", "section", "article"):
            tag = "p"
        elif tag == "span":
            tag = "em"
        else:
            tag = "p"
            
    node = {"tag": tag}
    attrs = {}
    if tag == "a" and element.get("href"):
        attrs["href"] = element.get("href")
    elif tag == "img" and element.get("src"):
        attrs["src"] = element.get("src")
        
    if attrs:
        node["attrs"] = attrs
        
    children = []
    for child in element.children:
        # Bỏ qua các chuỗi rỗng
        if isinstance(child, str) and not child.strip() and child == "\n":
            continue
        child_node = html_to_nodes(child)
        if child_node:
            children.append(child_node)
            
    if children:
        node["children"] = children
    else:
        text_content = element.get_text()
        if text_content:
            node["children"] = [text_content]
            
    return node

def publish_to_telegraph(title: str, markdown_content: str) -> str:
    """
    Đăng tải tài liệu Markdown lên Telegra.ph.
    Trả về: URL trang Webview (Instant View) hoặc None nếu có lỗi.
    """
    try:
        # 1. Chuyển Markdown sang HTML
        html_content = ai_to_mdv2(markdown_content)
        
        # 2. Parse HTML dùng BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        nodes = []
        for child in soup.contents:
            if isinstance(child, str) and not child.strip():
                continue
            node = html_to_nodes(child)
            if node:
                nodes.append(node)
                
        if not nodes:
            nodes = [{"tag": "p", "children": [markdown_content]}]
            
        token = get_access_token()
        
        # 3. Gửi yêu cầu lưu trang mới
        page_url = "https://api.telegra.ph/createPage"
        payload = {
            "access_token": token,
            "title": title,
            "author_name": "AI Solution Architect",
            "content": json.dumps(nodes),
            "return_content": False
        }
        
        res = requests.post(page_url, data=payload, timeout=20).json()
        if res.get("ok") and "url" in res.get("result", {}):
            url = res["result"]["url"]
            logger.info(f"Đã xuất bản thành công tài liệu lên Telegraph: {url}")
            return url
        else:
            logger.error(f"Lỗi API Telegraph: {res}")
            return None
            
    except Exception as e:
        logger.error(f"Lỗi hệ thống khi đăng tải Telegraph: {e}", exc_info=True)
        return None
