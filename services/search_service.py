import logging
import urllib.parse
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def search_duckduckgo(query: str, limit: int = 5) -> list[dict]:
    """
    Tìm kiếm thông tin trên DuckDuckGo HTML.
    Trả về list các dict: {"title": str, "url": str}
    """
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        params = {"q": query}
        
        logger.info(f"Đang tìm kiếm DuckDuckGo cho từ khóa: {query}")
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        results = []
        
        # Các kết quả tìm kiếm nằm trong thẻ class 'result__a'
        for a_tag in soup.find_all("a", class_="result__a"):
            title = a_tag.get_text().strip()
            raw_url = a_tag.get("href", "")
            
            # Giải mã link redirect của DuckDuckGo nếu có
            # Định dạng thường gặp: //duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com...
            actual_url = raw_url
            if "uddg=" in raw_url:
                parsed_url = urllib.parse.urlparse(raw_url)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if "uddg" in query_params:
                    actual_url = query_params["uddg"][0]
                    
            if actual_url.startswith("//"):
                actual_url = "https:" + actual_url
                
            # Loại bỏ các link nội bộ của DuckDuckGo (như cài đặt, quảng cáo)
            if "duckduckgo.com" in actual_url and "uddg=" not in raw_url:
                continue
                
            results.append({
                "title": title,
                "url": actual_url
            })
            
            if len(results) >= limit:
                break
                
        logger.info(f"Tìm thấy {len(results)} kết quả cho từ khóa: {query}")
        return results
    except Exception as e:
        logger.error(f"Lỗi khi tìm kiếm DuckDuckGo: {e}", exc_info=True)
        return []
