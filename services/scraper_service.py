import re
import logging
import requests
from bs4 import BeautifulSoup
import yt_dlp
import glob

import config
import os

logger = logging.getLogger(__name__)

def extract_youtube_video_id(url: str) -> str | None:
    """Trích xuất ID video từ các định dạng URL YouTube khác nhau."""
    url_lower = url.lower()
    if "youtube.com" not in url_lower and "youtu.be" not in url_lower:
        return None
        
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})(?:\?|&|$)',
        r'(?:embed\/|shorts\/|v\/|watch\?v=|youtu\.be\/)([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_video_title(video_id: str) -> str:
    """Lấy tiêu đề video YouTube thông qua oEmbed API công khai (tránh bị chặn IP)."""
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            title = data.get("title")
            author = data.get("author_name")
            if title and author:
                return f"{title} (kênh {author})"
            elif title:
                return title
    except Exception as e:
        logger.error(f"Không lấy được tiêu đề video {video_id} qua oEmbed: {e}")
    return f"Video YouTube {video_id}"

def parse_vtt_file(vtt_path: str) -> str:
    """Đọc và phân tích file WebVTT để lấy nội dung văn bản sạch, loại bỏ lặp từ."""
    if not os.path.exists(vtt_path):
        return ""
    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        blocks = content.split("\n\n")
        parsed_lines = []
        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if not lines:
                continue
            if "-->" in lines[0]:
                text_lines = lines[1:]
                clean_text_lines = []
                for line in text_lines:
                    cleaned = re.sub(r'<[^>]+>', '', line).strip()
                    if cleaned:
                        clean_text_lines.append(cleaned)
                if clean_text_lines:
                    # Lấy dòng cuối cùng của cue để tránh lặp từ cuộn của YouTube
                    parsed_lines.append(clean_text_lines[-1])
                    
        # Loại bỏ các dòng trùng lặp liên tiếp
        final_lines = []
        for line in parsed_lines:
            if not final_lines or line != final_lines[-1]:
                final_lines.append(line)
                
        full_text = " ".join(final_lines)
        return re.sub(r'\s+', ' ', full_text).strip()
    except Exception as e:
        logger.error(f"Lỗi phân tích file VTT {vtt_path}: {e}")
        return ""

def get_youtube_transcript(video_id: str) -> str:
    """Lấy phụ đề (transcript) của video YouTube bằng yt-dlp.
    Ưu tiên tiếng Việt, sau đó là tiếng Anh."""
    out_prefix = f"scratch/tmp_subs_{video_id}_{os.getpid()}"
    
    cookies_file = getattr(config, "YOUTUBE_COOKIES_FILE", "youtube_cookies.txt")
    proxy = getattr(config, "YOUTUBE_PROXY", "")
    
    ydl_opts = {
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['vi', 'en'],
        'skip_download': True,
        'ignore_no_formats_error': True,
        'outtmpl': out_prefix,
        'quiet': True,
        'no_warnings': True,
        'js_runtimes': {'node': {}},
    }

    
    if cookies_file and os.path.exists(cookies_file):
        ydl_opts['cookiefile'] = cookies_file
        logger.info(f"Sử dụng file cookies: {cookies_file}")
        
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"Sử dụng proxy: {proxy}")
        
    # Đảm bảo thư mục scratch tồn tại
    os.makedirs("scratch", exist_ok=True)
    
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # Tìm các file phụ đề được tải về
        downloaded_files = glob.glob(f"{out_prefix}*")
        
        # Lọc tìm file phụ đề tiếng Việt trước
        vi_file = next((f for f in downloaded_files if f.endswith(".vi.vtt")), None)
        en_file = next((f for f in downloaded_files if f.endswith(".en.vtt")), None)
        
        transcript_text = ""
        chosen_file = vi_file or en_file or (downloaded_files[0] if downloaded_files else None)
        
        if chosen_file:
            transcript_text = parse_vtt_file(chosen_file)
            
        # Dọn dẹp các file tạm
        for f in downloaded_files:
            try:
                os.remove(f)
            except Exception as e:
                logger.warning(f"Không thể xóa file tạm {f}: {e}")
                
        if not transcript_text:
            raise Exception("Không tìm thấy phụ đề phù hợp (tiếng Việt hoặc tiếng Anh) cho video này.")
            
        return transcript_text
        
    except yt_dlp.utils.DownloadError as de:
        err_msg = str(de)
        logger.error(f"yt-dlp DownloadError cho video {video_id}: {err_msg}")
        if "confirm you are not a bot" in err_msg.lower() or "sign in" in err_msg.lower():
            raise Exception(
                "YouTube đang chặn máy chủ này truy cập phụ đề do nghi ngờ bot.\n\n"
                "👉 *Cách khắc phục*:\n"
                "1. Cập nhật lại file `youtube_cookies.txt` (đã đăng nhập tài khoản Google) trong thư mục chạy bot.\n"
                "2. Hoặc cấu hình biến `YOUTUBE_PROXY` trong file `.env` (sử dụng Residential Proxy)."
            )
        elif "unavailable" in err_msg.lower() or "private" in err_msg.lower():
            raise Exception("Video YouTube này không tồn tại, đã bị xóa hoặc ở chế độ riêng tư.")
        else:
            raise Exception(f"Không thể tải phụ đề từ YouTube: {err_msg.split(';')[0]}")
    except Exception as e:
        logger.error(f"Lỗi không xác định khi lấy transcript cho video {video_id}: {e}")
        # Đảm bảo dọn dẹp file tạm nếu có lỗi khác
        for f in glob.glob(f"{out_prefix}*"):
            try:
                os.remove(f)
            except Exception:
                pass
        raise e



def scrape_web_link(url: str) -> tuple[str, str]:
    """Cào nội dung bài viết từ một đường link web bất kỳ.
    Trả về tiêu đề và nội dung văn bản đã được làm sạch."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Lấy tiêu đề
        title = soup.title.string.strip() if soup.title else "Trang web không có tiêu đề"
        
        # Loại bỏ các thẻ rác
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "iframe", "aside", "form"]):
            tag.decompose()
            
        # Tìm vùng chứa nội dung chính
        main_content = None
        # Thử tìm các thẻ thông dụng trước
        for selector in ['article', 'main', '[role="main"]']:
            found = soup.select_one(selector)
            if found:
                main_content = found
                break
                
        if not main_content:
            # Thử tìm div có class liên quan đến nội dung chính
            for class_keyword in ['article', 'content', 'post', 'body', 'main']:
                found = soup.find('div', class_=re.compile(f'.*{class_keyword}.*', re.IGNORECASE))
                if found:
                    main_content = found
                    break
                    
        if not main_content:
            main_content = soup.body
            
        if not main_content:
            return title, ""
            
        # Trích xuất văn bản có cấu trúc
        text_blocks = []
        for element in main_content.find_all(['h1', 'h2', 'h3', 'p', 'li']):
            # Bỏ qua các phần tử con nằm trong các tag rác khác nếu lọt lưới
            text = element.get_text().strip()
            if not text or len(text) < 15:
                continue
                
            # Đánh dấu tiêu đề để LLM dễ nhận biết cấu trúc bài viết
            if element.name.startswith('h'):
                text_blocks.append(f"\n\n### {text}\n")
            else:
                text_blocks.append(text)
                
        clean_text = "\n".join(text_blocks).strip()
        return title, clean_text
        
    except Exception as e:
        logger.error(f"Lỗi khi cào link {url}: {e}")
        raise e
