import os
import logging
from config import LLM_API_URL, LLM_API_KEY
from services.summarizer import _call

logger = logging.getLogger(__name__)

REPOS_ROOT_DIR = "/Users/macmini/SourceCode"

# Các thư mục cần bỏ qua để tối ưu tốc độ quét code
IGNORE_DIRS = {
    ".git", ".svn", "node_modules", "build", "dist", "venv", "env",
    "android", "ios", ".idea", ".vscode", ".gradle", "bin", "obj",
    "__pycache__", "out", "target", "coverage"
}

# Các định dạng file code được ưu tiên tìm kiếm
CODE_EXTENSIONS = {
    ".py", ".dart", ".js", ".ts", ".tsx", ".jsx", ".go", ".java",
    ".cpp", ".h", ".c", ".kt", ".swift", ".rb", ".php", ".cs",
    ".sh", ".yml", ".yaml", ".json"
}


def get_local_path_for_project(project_path_with_namespace: str) -> str:
    """
    Ánh xạ path_with_namespace của GitLab sang đường dẫn thư mục cục bộ.
    Ví dụ: 'it5.ptgp.digo/vncitizens/svc.smarttown' -> '/Users/macmini/SourceCode/svc.smarttown'
           'vncitizens/flutter.vncitizens' -> '/Users/macmini/SourceCode/flutter.vncitizens'
    """
    # Lấy tên thư mục cuối cùng
    parts = project_path_with_namespace.split("/")
    repo_name = parts[-1]
    
    # Kiểm tra xem folder có tồn tại trong /Users/macmini/SourceCode không
    local_path = os.path.join(REPOS_ROOT_DIR, repo_name)
    if os.path.exists(local_path) and os.path.isdir(local_path):
        return local_path
        
    # Thử tìm kiếm mờ (fuzzy) xem có thư mục nào tương tự không
    try:
        for entry in os.scandir(REPOS_ROOT_DIR):
            if entry.is_dir() and entry.name.lower() == repo_name.lower():
                return entry.path
    except Exception:
        pass

    return ""


def search_local_repository(repo_path: str, keyword: str, limit: int = 3) -> list[dict]:
    """
    Tìm kiếm nhanh các file code chứa từ khóa trong thư mục cục bộ.
    """
    logger.info(f"Đang quét code cục bộ tại {repo_path} cho từ khóa: {keyword}")
    results = []
    
    # Chuẩn hóa từ khóa tìm kiếm (không phân biệt hoa thường)
    kw_lower = keyword.lower().strip()
    if not kw_lower:
        return []

    try:
        for root, dirs, files in os.walk(repo_path):
            # Lọc bỏ các thư mục rác/nặng trực tiếp trong lúc walk
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in CODE_EXTENSIONS:
                    continue
                    
                file_path = os.path.join(root, file)
                
                # Bỏ qua các file cấu hình lock hoặc file quá nặng (> 1MB) để tránh tràn memory
                try:
                    if os.path.getsize(file_path) > 1 * 1024 * 1024:
                        continue
                        
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        
                    # Kiểm tra xem file có chứa từ khóa không
                    if kw_lower in content.lower():
                        rel_path = os.path.relpath(file_path, repo_path)
                        results.append({
                            "file_path": rel_path,
                            "content": content
                        })
                        
                        if len(results) >= limit:
                            break
                except Exception as e:
                    logger.warning(f"Không thể đọc file {file_path}: {e}")
                    
            if len(results) >= limit:
                break
                
        logger.info(f"Tìm thấy {len(results)} file cục bộ khớp cho '{keyword}'")
        return results
    except Exception as e:
        logger.error(f"Lỗi khi quét repo cục bộ {repo_path}: {e}", exc_info=True)
        return []


def analyze_api_with_gemini(repo_name: str, keyword: str, files_data: list[dict]) -> str:
    """
    Gọi Gemini phân tích API, cấu trúc tham số (params) và tính khả dụng của tham số dựa trên context code.
    """
    if not files_data:
        return f"❌ Không tìm thấy đoạn code nguồn nào chứa từ khóa `{keyword}` trong dự án này để phân tích."

    # Xây dựng nội dung context code
    code_context_parts = []
    for idx, item in enumerate(files_data):
        path = item["file_path"]
        content = item["content"]
        
        # Chỉ lấy tối đa 400 dòng đầu của file hoặc trích xuất thông minh xung quanh từ khóa để tránh token limit
        lines = content.splitlines()
        if len(lines) > 400:
            # Tìm dòng chứa từ khóa
            match_line_idx = 0
            for i, line in enumerate(lines):
                if keyword.lower() in line.lower():
                    match_line_idx = i
                    break
            
            # Trích xuất 100 dòng trước và 250 dòng sau dòng khớp
            start_idx = max(0, match_line_idx - 100)
            end_idx = min(len(lines), match_line_idx + 250)
            extracted_lines = lines[start_idx:end_idx]
            
            header = f"--- [TRÍCH XUẤT] File: {path} (Dòng {start_idx + 1} đến {end_idx}) ---"
            file_code = "\n".join(extracted_lines)
        else:
            header = f"--- File: {path} ---"
            file_code = content
            
        code_context_parts.append(f"{header}\n{file_code}\n")

    code_context = "\n".join(code_context_parts)

    system_prompt = (
        "Bạn là một lập trình viên cao cấp, kiến trúc sư phần mềm và chuyên gia thiết kế API. "
        "Nhiệm vụ của bạn là đọc và phân tích các tệp mã nguồn được cung cấp để giải thích chi tiết cách sử dụng của API/hàm liên quan đến từ khóa của người dùng, "
        "đặc biệt là kiểm tra tính khả dụng và cấu trúc của các tham số (parameters)."
    )

    user_prompt = (
        f"Dự án (Repository): **{repo_name}**\n"
        f"Từ khóa API cần tra cứu: `{keyword}`\n\n"
        f"=== BỐI CẢNH MÃ NGUỒN KHỚP ĐƯỢC ===\n"
        f"{code_context}\n"
        f"====================================\n\n"
        f"Dựa trên mã nguồn trên, hãy phân tích kỹ và viết báo cáo trả lời chi tiết theo đúng cấu trúc sau (Luôn viết bằng tiếng Việt, ngắn gọn, súc tích và có tính hành động cao):\n\n"
        f"📁 **VỊ TRÍ ĐỊNH NGHĨA:**\n"
        f"(Liệt kê đường dẫn file nguồn và chỉ ra dòng/hàm định nghĩa API đó)\n\n"
        f"⚡ **CÁCH DÙNG API / HÀM:**\n"
        f"• **Endpoint/Cú pháp:** (e.g. POST `/api/v1/auth` hoặc tên hàm kèm tham số)\n"
        f"• **Headers/Cấu hình:** (nếu có, e.g. Content-Type, Authorization)\n"
        f"• **Dữ liệu đầu vào (Request Body / Arguments):** (Mô tả cấu trúc dữ liệu truyền vào)\n\n"
        f"⚙️ **KIỂM TRA THAM SỐ (PARAMS AUDIT):**\n"
        f"• **Các tham số khả dụng:** (Liệt kê tất cả các tham số được hỗ trợ trong code và kiểu dữ liệu của chúng)\n"
        f"• **Tham số bạn hỏi có khả dụng không?:** (Trả lời và khẳng định rõ ràng xem tham số cụ thể mà người dùng hỏi hoặc từ khóa có được hỗ trợ hay không. Ví dụ: 'Tham số `userId` CÓ KHẢ DỤNG trong API này dưới dạng Query Parameter, nhưng tham số `email` KHÔNG khả dụng')\n\n"
        f"📝 **VÍ DỤ GỌI API (CODE SNIPPET):**\n"
        f"(Viết 1 đoạn code mẫu cực kỳ sạch sẽ, chuẩn chỉ để gọi API hoặc hàm này bằng ngôn ngữ tương ứng của dự án, ví dụ Dart/Flutter nếu là dự án mobile, TypeScript/NodeJS nếu là frontend/backend, Python nếu là AI...)\n"
    )

    try:
        logger.info(f"Đang gọi Gemini phân tích API cho từ khóa '{keyword}'")
        analysis_result = _call(system_prompt, user_prompt)
        return analysis_result
    except Exception as e:
        logger.error(f"Lỗi khi gọi AI phân tích API: {e}")
        return f"❌ Lỗi khi phân tích mã nguồn bằng AI: {str(e)}"
