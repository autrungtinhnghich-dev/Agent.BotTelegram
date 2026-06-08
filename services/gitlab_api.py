import logging
import httpx
import re
import asyncio
from urllib.parse import quote_plus
from config import GITLAB_PAT, GITLAB_VERIFY_SSL

logger = logging.getLogger(__name__)
 
def _find_method_boundary(lines: list[str], change_start: int, change_end: int) -> tuple[int, int]:
    """
    Tìm ranh giới method/function bao quanh đoạn code thay đổi.
    Quét lên để tìm method signature, quét xuống để tìm closing brace.
    Trả về (method_start, method_end) dạng 1-indexed.
    """
    total = len(lines)
    if total == 0:
        return (1, 1)
        
    # Đảm bảo indices nằm trong vùng an toàn
    change_start = max(0, min(total - 1, change_start))
    change_end = max(0, min(total - 1, change_end))
    
    # Quét lên trên để tìm method signature
    # Pattern: access_modifier return_type methodName(...) {
    method_pattern = re.compile(
        r'^\s*(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*'
        r'(?:\w[\w<>\[\],\s]*\s+)?'
        r'\w+\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{?\s*$'
    )
    
    method_start = change_start
    for i in range(method_start, max(-1, method_start - 500), -1):
        if i >= total: continue
        line = lines[i].strip()
        if method_pattern.match(line):
            method_start = i
            break
        # Nếu gặp closing brace ở cùng indent level (kết thúc method trước đó), dừng
        if line == '}' and i < change_start:
            method_start = i + 1
            break
    else:
        method_start = max(0, change_start - 30)
    
    # Quét xuống dưới để tìm closing brace của method
    brace_depth = 0
    found_open = False
    method_end = change_end
    
    for i in range(method_start, min(total, change_end + 500)):
        line = lines[i]
        for ch in line:
            if ch == '{':
                brace_depth += 1
                found_open = True
            elif ch == '}':
                brace_depth -= 1
        
        if found_open and brace_depth <= 0:
            method_end = i
            break
    else:
        method_end = min(total - 1, change_end + 30)
    
    return (method_start + 1, method_end + 1)  # convert back to 1-indexed


def _find_imports_end(lines: list[str]) -> int:
    """Tìm dòng kết thúc phần import/package (0-indexed)."""
    last_import = 0
    for i, line in enumerate(lines[:200]):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('package ') or stripped.startswith('from ') or stripped.startswith('#include'):
            last_import = i
        elif stripped and not stripped.startswith('//') and not stripped.startswith('/*') and not stripped.startswith('*') and not stripped.startswith('*/') and last_import > 0:
            # Gặp code thực sự sau imports → dừng
            break
    return last_import


def extract_smart_context(full_content: str, diff: str) -> str:
    """
    Trích xuất THÔNG MINH các đoạn code liên quan từ file gốc dựa trên diff.
    Đồng thời đánh dấu các dòng thực sự thay đổi để AI tập trung review.
    """
    if not full_content or not diff or full_content.startswith('('):
        return full_content
        
    lines = full_content.splitlines()
    total_lines = len(lines)
    
    # 1. Phân tích diff để xác định chính xác các dòng bị thay đổi trong file MỚI
    changed_line_nums = set()
    hunks = re.split(r"(@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@)", diff)
    
    # Hunks sẽ có dạng: [header, hunk1_content, header2, hunk2_content, ...]
    for i in range(1, len(hunks), 2):
        header = hunks[i]
        content = hunks[i+1]
        
        # Lấy new_start từ: @@ -old_start,old_len +new_start,new_len @@
        match = re.search(r"\+(\d+)", header)
        if not match: continue
        
        curr_line = int(match.group(1))
        for line in content.splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                changed_line_nums.add(curr_line)
                curr_line += 1
            elif line.startswith('-') and not line.startswith('---'):
                pass # Dòng bị xóa không xuất hiện trong full_content
            else:
                curr_line += 1

    # 2. Tìm các vùng cần trích xuất (imports + các method chứa thay đổi)
    hunk_headers = re.findall(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff)
    if not hunk_headers:
        return "\n".join(f"{i+1:5}: {lines[i]}" for i in range(min(50, total_lines)))
    
    ranges = []
    imports_end = _find_imports_end(lines)
    if imports_end > 0:
        ranges.append((1, imports_end + 1))
    
    for start_str, len_str in hunk_headers:
        start = int(start_str)
        length = int(len_str) if len_str else 1
        m_start, m_end = _find_method_boundary(lines, start - 1, start - 1 + length)
        ranges.append((m_start, m_end))
    
    ranges.sort()
    merged = []
    if ranges:
        curr_start, curr_end = ranges[0]
        for next_start, next_end in ranges[1:]:
            if next_start <= curr_end + 5:
                curr_end = max(curr_end, next_end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = next_start, next_end
        merged.append((curr_start, curr_end))
    
    # 3. Trích xuất code kèm số dòng và marker cho dòng thay đổi
    result_parts = []
    last_end = 0
    for start, end in merged:
        if start > last_end + 1 and last_end != 0:
            result_parts.append(f"\n... (đã ẩn {start - last_end - 1} dòng) ...\n")
        
        for i in range(start - 1, min(end, total_lines)):
            line_num = i + 1
            marker = ">>> " if line_num in changed_line_nums else "    "
            result_parts.append(f"{line_num:5}: {marker}{lines[i]}")
        last_end = end
        
    return "\n".join(result_parts)

async def _http_get_with_retry(url: str, headers: dict, timeout: float = 20.0, max_attempts: int = 4) -> httpx.Response:
    last_ex = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(verify=GITLAB_VERIFY_SSL) as client:
                resp = await client.get(url, headers=headers, timeout=timeout)
                if resp.status_code >= 500:
                    resp.raise_for_status()
                return resp
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"GitLab API request failed (attempt {attempt}/{max_attempts}): {e}")
            last_ex = e
            if attempt < max_attempts:
                await asyncio.sleep(0.5 * attempt)
    raise last_ex


async def get_mr_diff(url: str, include_full_file: bool = False) -> dict:
    """
    Parse a GitLab MR URL, fetch the MR details and diff, and return them.
    If include_full_file is True, fetch the entire content of changed files.
    Returns dict: {"title": str, "diff": str, "error": str}
    """
    # Regex to extract domain, project path, and MR IID
    # e.g. https://scm.devops.vnpt.vn/it5.ptgp.digo/vncitizens/svc.smarttown/-/merge_requests/341
    match = re.match(r"(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)", url)
    if not match:
        return {"error": "Link không đúng định dạng GitLab Merge Request."}

    base_url = match.group(1)
    project_path = match.group(2)
    mr_iid = match.group(3)

    encoded_project_path = quote_plus(project_path)
    api_url = f"{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/changes"

    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT

    try:
        resp = await _http_get_with_retry(api_url, headers=headers, timeout=20.0)
        
        if resp.status_code == 404:
            return {"error": "Không tìm thấy Merge Request (hoặc không có quyền truy cập)."}
        elif resp.status_code == 401 or resp.status_code == 403:
            return {"error": "Lỗi xác thực GitLab. Hãy kiểm tra lại GITLAB_PAT trong .env."}
        
        resp.raise_for_status()
        data = resp.json()

        title = data.get("title", "Untitled MR")
        sha = data.get("sha")
        project_id = data.get("project_id")
        changes = data.get("changes", [])

        # Gộp tất cả các diff lại thành một chuỗi với marker rõ ràng
        diff_lines = []
        
        # Nếu cần lấy toàn bộ file, chúng ta sẽ gọi API lấy từng file raw
        async def fetch_raw_file(file_path: str):
            encoded_path = quote_plus(file_path)
            raw_url = f"{base_url}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw?ref={sha}"
            try:
                raw_resp = await _http_get_with_retry(raw_url, headers=headers, timeout=10.0)
                if raw_resp.status_code == 200:
                    return raw_resp.text
                return f"(Không thể lấy nội dung file: {raw_resp.status_code})"
            except Exception as e:
                return f"(Lỗi khi lấy nội dung file: {str(e)})"

        for change in changes:
            old_path = change.get("old_path")
            new_path = change.get("new_path")
            diff = change.get("diff", "")
            
            # Xác định trạng thái file
            if change.get("new_file"):
                status = "[NEW FILE]"
            elif change.get("deleted_file"):
                status = "[DELETED]"
            elif change.get("renamed_file"):
                status = f"[RENAMED from {old_path}]"
            else:
                status = "[MODIFIED]"

            file_display_path = new_path or old_path
            diff_lines.append(f"\nFILE: {file_display_path} {status}")
            diff_lines.append("-" * 40)
            
            if include_full_file and not change.get("deleted_file"):
                # Lấy nội dung đầy đủ
                full_content = await fetch_raw_file(file_display_path)
                
                # Áp dụng Smart Context để tiết kiệm token mà vẫn đủ thông tin
                smart_content = extract_smart_context(full_content, diff)
                
                diff_lines.append(f"SMART CONTEXT OF {file_display_path} (Based on MR changes):")
                diff_lines.append(smart_content)
            else:
                diff_lines.append(diff)
                
            diff_lines.append("-" * 40)
        
        full_diff = "\n".join(diff_lines)

        # Limit diff size to prevent token explosion
        # Với Smart Context, dung lượng đã giảm đáng kể, nhưng vẫn giữ limit an toàn
        limit = 500000 
        if len(full_diff) > limit:
            full_diff = full_diff[:limit] + f"\n... (Nội dung quá dài, đã bị cắt bớt ở {limit} ký tự)"

        return {"title": title, "diff": full_diff, "error": None}

    except httpx.RequestError as e:
        logger.error(f"GitLab API error: {e}")
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}
    except Exception as e:
        logger.error(f"GitLab Parse error: {e}", exc_info=True)
        return {"error": "Có lỗi xảy ra khi đọc dữ liệu từ GitLab."}


async def get_mr_commits(url: str) -> dict:
    """
    Parse a GitLab MR URL, fetch the list of commits in the MR, and return them.
    Returns dict: {"commits": list[dict], "error": str}
    """
    match = re.match(r"(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)", url)
    if not match:
        return {"error": "Link không đúng định dạng GitLab Merge Request."}

    base_url = match.group(1)
    project_path = match.group(2)
    mr_iid = match.group(3)

    encoded_project_path = quote_plus(project_path)
    api_url = f"{base_url}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/commits"

    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT

    try:
        commits = []
        page = 1
        while True:
            page_url = f"{api_url}?page={page}&per_page=100"
            resp = await _http_get_with_retry(page_url, headers=headers, timeout=20.0)
            if resp.status_code == 404:
                return {"error": "Không tìm thấy danh sách commit của MR (hoặc không có quyền truy cập)."}
            elif resp.status_code in (401, 403):
                return {"error": "Lỗi xác thực GitLab. Hãy kiểm tra lại GITLAB_PAT trong .env."}
            resp.raise_for_status()
            page_commits = resp.json()
            if not page_commits:
                break
            commits.extend(page_commits)
            if len(page_commits) < 100:
                break
            page += 1
        return {"commits": commits, "error": None}
    except httpx.RequestError as e:
        logger.error(f"GitLab API error: {e}", exc_info=True)
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}
    except Exception as e:
        logger.error(f"GitLab Parse error: {e}", exc_info=True)
        return {"error": "Có lỗi xảy ra khi đọc dữ liệu commits từ GitLab."}


async def get_latest_project_tag(url: str) -> dict:
    """
    Parse a GitLab MR URL, fetch the list of project tags, and return the latest version tag.
    Returns dict: {"tag": str, "error": str}
    """
    match = re.match(r"(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)", url)
    if not match:
        return {"error": "Link không đúng định dạng GitLab Merge Request."}

    base_url = match.group(1)
    project_path = match.group(2)

    encoded_project_path = quote_plus(project_path)
    api_url = f"{base_url}/api/v4/projects/{encoded_project_path}/repository/tags"

    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT

    try:
        # Lấy danh sách tag, mặc định GitLab sắp xếp theo updated/created desc hoặc name desc
        resp = await _http_get_with_retry(f"{api_url}?limit=50", headers=headers, timeout=20.0)
        if resp.status_code == 404:
            return {"error": "Không tìm thấy danh sách tag (hoặc không có quyền truy cập)."}
        elif resp.status_code in (401, 403):
            return {"error": "Lỗi xác thực GitLab. Hãy kiểm tra lại GITLAB_PAT trong .env."}
        resp.raise_for_status()
        tags_data = resp.json()
        
        if not tags_data:
            return {"tag": None, "error": None}

        tag_names = [t.get("name") for t in tags_data if t.get("name")]
        
        # Hàm trích xuất và so sánh SemVer
        def semver_key(tag_name):
            clean_name = re.sub(r'^[vV]', '', tag_name)
            parts = []
            for p in clean_name.split('.'):
                m = re.match(r'^(\d+)', p)
                if m:
                    parts.append(int(m.group(1)))
                else:
                    parts.append(-1)
            return tuple(parts)

        # Lọc các tag giống định dạng phiên bản để tránh tag linh tinh
        version_tags = [t for t in tag_names if re.match(r'^[vV]?\d+(\.\d+)*', t)]
        if version_tags:
            latest_tag = max(version_tags, key=semver_key)
        else:
            latest_tag = tag_names[0]

        return {"tag": latest_tag, "error": None}
    except httpx.RequestError as e:
        logger.error(f"GitLab API error: {e}")
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}
    except Exception as e:
        logger.error(f"GitLab Parse error: {e}", exc_info=True)
        return {"error": "Có lỗi xảy ra khi đọc dữ liệu tags từ GitLab."}


async def check_existing_mr(project_path: str, source: str = "dev", target: str = "master") -> dict:
    """
    Kiểm tra xem đã có MR nào đang mở từ source sang target hay chưa.
    """
    encoded_project_path = quote_plus(project_path)
    from config import GITLAB_BASE_URL
    api_url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_project_path}/merge_requests?state=opened&source_branch={source}&target_branch={target}"
    
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
        
    try:
        resp = await _http_get_with_retry(api_url, headers=headers, timeout=20.0)
        if resp.status_code == 200:
            mrs = resp.json()
            if mrs:
                return {"mr": mrs[0], "error": None}
            return {"mr": None, "error": None}
        return {"error": f"Lỗi check MR: HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error checking MR: {e}", exc_info=True)
        return {"error": f"Lỗi check MR: {str(e)}"}


async def create_mr(project_path: str, source: str = "dev", target: str = "master", title: str = "Release dev to master") -> dict:
    """
    Tạo Merge Request mới từ source sang target.
    """
    encoded_project_path = quote_plus(project_path)
    from config import GITLAB_BASE_URL
    api_url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_project_path}/merge_requests"
    
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
        
    payload = {
        "source_branch": source,
        "target_branch": target,
        "title": title
    }
    
    try:
        async with httpx.AsyncClient(verify=GITLAB_VERIFY_SSL) as client:
            resp = await client.post(api_url, headers=headers, json=payload, timeout=20.0)
            if resp.status_code in (200, 201):
                return {"mr": resp.json(), "error": None}
            return {"error": f"Lỗi tạo MR: HTTP {resp.status_code} - {resp.text}"}
    except Exception as e:
        logger.error(f"Error creating MR: {e}", exc_info=True)
        return {"error": f"Lỗi tạo MR: {str(e)}"}


async def merge_mr(project_path: str, mr_iid: int) -> dict:
    """
    Thực hiện merge Merge Request.
    """
    encoded_project_path = quote_plus(project_path)
    from config import GITLAB_BASE_URL
    api_url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_project_path}/merge_requests/{mr_iid}/merge"
    
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
        
    try:
        async with httpx.AsyncClient(verify=GITLAB_VERIFY_SSL) as client:
            resp = await client.put(api_url, headers=headers, timeout=20.0)
            if resp.status_code == 200:
                return {"result": resp.json(), "error": None}
            return {"error": f"Lỗi merge MR: HTTP {resp.status_code} - {resp.text}"}
    except Exception as e:
        logger.error(f"Error merging MR: {e}", exc_info=True)
        return {"error": f"Lỗi merge MR: {str(e)}"}


async def create_tag(project_path: str, tag_name: str, ref: str = "master", description: str = "") -> dict:
    """
    Tạo release tag trên GitLab.
    """
    encoded_project_path = quote_plus(project_path)
    from config import GITLAB_BASE_URL
    api_url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_project_path}/repository/tags"
    
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
        
    payload = {
        "tag_name": tag_name,
        "ref": ref
    }
    if description:
        payload["release_description"] = description
        
    try:
        async with httpx.AsyncClient(verify=GITLAB_VERIFY_SSL) as client:
            resp = await client.post(api_url, headers=headers, json=payload, timeout=20.0)
            if resp.status_code in (200, 201):
                return {"tag": resp.json(), "error": None}
            return {"error": f"Lỗi tạo tag: HTTP {resp.status_code} - {resp.text}"}
    except Exception as e:
        logger.error(f"Error creating tag: {e}", exc_info=True)
        return {"error": f"Lỗi tạo tag: {str(e)}"}


async def get_latest_merged_mr(project_path: str, source: str = "dev", target: str = "master") -> dict:
    """
    Lấy Merge Request đã merge gần đây nhất từ source sang target.
    """
    encoded_project_path = quote_plus(project_path)
    from config import GITLAB_BASE_URL
    api_url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_project_path}/merge_requests?state=merged&source_branch={source}&target_branch={target}&order_by=updated_at&sort=desc&per_page=1"
    
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
        
    try:
        resp = await _http_get_with_retry(api_url, headers=headers, timeout=20.0)
        if resp.status_code == 200:
            mrs = resp.json()
            if mrs:
                return {"mr": mrs[0], "error": None}
            return {"mr": None, "error": None}
        return {"error": f"Lỗi lấy MR đã merge: HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error getting latest merged MR: {e}", exc_info=True)
        return {"error": f"Lỗi lấy MR đã merge: {str(e)}"}


async def get_user_projects(limit: int = 50) -> list[dict]:
    """
    Lấy danh sách các project từ SCM GitLab mà user có quyền truy cập.
    """
    from config import GITLAB_BASE_URL
    if not GITLAB_BASE_URL or not GITLAB_PAT:
        logger.warning("Jira/GitLab config missing: GITLAB_BASE_URL hoặc GITLAB_PAT chưa cấu hình.")
        return []

    # API lấy projects của user
    url = f"{GITLAB_BASE_URL}/api/v4/projects?membership=true&simple=true&per_page={limit}&order_by=last_activity_at"
    headers = {"PRIVATE-TOKEN": GITLAB_PAT}

    try:
        resp = await _http_get_with_retry(url, headers=headers, timeout=15.0)
        if resp.status_code == 200:
            projects = resp.json()
            result = []
            for p in projects:
                result.append({
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "path": p.get("path"),
                    "path_with_namespace": p.get("path_with_namespace"),
                    "web_url": p.get("web_url")
                })
            return result
        else:
            logger.error(f"GitLab API returned status code {resp.status_code} while fetching projects")
            return []
    except Exception as e:
        logger.error(f"Error fetching projects from SCM GitLab: {e}", exc_info=True)
        return []


async def search_remote_repository(project_id: int, keyword: str, limit: int = 3) -> list[dict]:
    """
    Tìm kiếm từ khóa trong repo GitLab từ xa (SCM Remote Mode) và trả về nội dung của các file khớp.
    """
    from config import GITLAB_BASE_URL
    if not GITLAB_BASE_URL or not GITLAB_PAT:
        return []

    # 1. Tìm kiếm code blob chứa từ khóa
    search_url = f"{GITLAB_BASE_URL}/api/v4/projects/{project_id}/search?scope=blobs&search={quote_plus(keyword)}"
    headers = {"PRIVATE-TOKEN": GITLAB_PAT}

    try:
        resp = await _http_get_with_retry(search_url, headers=headers, timeout=15.0)
        if resp.status_code != 200:
            logger.error(f"GitLab search blobs failed: HTTP {resp.status_code}")
            return []

        blobs = resp.json()
        if not blobs:
            return []

        # Chỉ lấy tối đa limit files khớp nhất để tránh quá tải
        unique_paths = []
        for b in blobs:
            path = b.get("path")
            if path and path not in unique_paths:
                # Bỏ qua các file ảnh hoặc thư mục rác nếu có
                if not any(path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar.gz"]):
                    unique_paths.append(path)
            if len(unique_paths) >= limit:
                break

        # 2. Tải nội dung thô (raw content) của từng file
        result = []
        for file_path in unique_paths:
            encoded_path = quote_plus(file_path)
            # Mặc định lấy từ master/main branch của project
            raw_url = f"{GITLAB_BASE_URL}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw?ref=master"
            
            try:
                raw_resp = await _http_get_with_retry(raw_url, headers=headers, timeout=10.0)
                if raw_resp.status_code == 200:
                    result.append({
                        "file_path": file_path,
                        "content": raw_resp.text
                    })
                else:
                    # Nếu master không có, thử lấy từ main
                    raw_url_main = f"{GITLAB_BASE_URL}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw?ref=main"
                    raw_resp_main = await _http_get_with_retry(raw_url_main, headers=headers, timeout=10.0)
                    if raw_resp_main.status_code == 200:
                        result.append({
                            "file_path": file_path,
                            "content": raw_resp_main.text
                        })
            except Exception as e:
                logger.error(f"Error fetching raw file content for {file_path}: {e}")
                
        return result
    except Exception as e:
        logger.error(f"Error searching remote repository {project_id} for '{keyword}': {e}", exc_info=True)
        return []


async def get_project_branches(project_path: str, timeout: float = 15.0, max_attempts: int = 4) -> dict:
    """
    Lấy danh sách branch từ xa của một dự án trên GitLab SCM.
    Returns dict: {"branches": list[str], "error": str}
    """
    from config import GITLAB_BASE_URL
    encoded_path = quote_plus(project_path)
    url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_path}/repository/branches?per_page=100"
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
    try:
        resp = await _http_get_with_retry(url, headers=headers, timeout=timeout, max_attempts=max_attempts)
        if resp.status_code == 200:
            branches = [b.get("name") for b in resp.json() if b.get("name")]
            return {"branches": branches, "error": None}
        return {"error": f"Lỗi lấy danh sách branch: HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error fetching branches: {e}", exc_info=True)
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}


async def get_branch_detail(project_path: str, branch: str, timeout: float = 15.0, max_attempts: int = 4) -> dict:
    """
    Lấy chi tiết một branch (gồm tin nhắn commit mới nhất) trên GitLab SCM.
    Returns dict: {"branch": dict, "error": str}
    """
    from config import GITLAB_BASE_URL
    encoded_path = quote_plus(project_path)
    encoded_branch = quote_plus(branch)
    url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_path}/repository/branches/{encoded_branch}"
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
    try:
        resp = await _http_get_with_retry(url, headers=headers, timeout=timeout, max_attempts=max_attempts)
        if resp.status_code == 200:
            return {"branch": resp.json(), "error": None}
        return {"error": f"Lỗi lấy thông tin branch {branch}: HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error fetching branch detail: {e}", exc_info=True)
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}


async def get_file_content(project_path: str, file_path: str, ref: str, timeout: float = 15.0, max_attempts: int = 4) -> dict:
    """
    Tải nội dung thô (raw text) của một file từ branch/ref nhất định trên GitLab SCM.
    Returns dict: {"content": str, "error": str}
    """
    from config import GITLAB_BASE_URL
    encoded_path = quote_plus(project_path)
    encoded_file = quote_plus(file_path)
    url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_path}/repository/files/{encoded_file}/raw?ref={ref}"
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
    try:
        resp = await _http_get_with_retry(url, headers=headers, timeout=timeout, max_attempts=max_attempts)
        if resp.status_code == 200:
            return {"content": resp.text, "error": None}
        return {"error": f"Lỗi tải file {file_path} (ref: {ref}): HTTP {resp.status_code}"}
    except Exception as e:
        logger.error(f"Error fetching file content: {e}", exc_info=True)
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}


async def update_file_content(project_path: str, file_path: str, branch: str, content: str, commit_message: str) -> dict:
    """
    Cập nhật (commit) nội dung file mới trực tiếp lên branch nhất định trên GitLab SCM.
    Returns dict: {"result": dict, "error": str}
    """
    from config import GITLAB_BASE_URL
    encoded_path = quote_plus(project_path)
    encoded_file = quote_plus(file_path)
    url = f"{GITLAB_BASE_URL}/api/v4/projects/{encoded_path}/repository/files/{encoded_file}"
    headers = {}
    if GITLAB_PAT:
        headers["PRIVATE-TOKEN"] = GITLAB_PAT
    
    payload = {
        "branch": branch,
        "commit_message": commit_message,
        "content": content
    }
    try:
        async with httpx.AsyncClient(verify=GITLAB_VERIFY_SSL) as client:
            resp = await client.put(url, headers=headers, json=payload, timeout=20.0)
            if resp.status_code in (200, 201):
                return {"result": resp.json(), "error": None}
            return {"error": f"Lỗi commit file: HTTP {resp.status_code} - {resp.text}"}
    except Exception as e:
        logger.error(f"Error updating file content: {e}", exc_info=True)
        return {"error": f"Lỗi kết nối GitLab: {str(e)}"}





