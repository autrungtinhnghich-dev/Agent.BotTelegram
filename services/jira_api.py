import logging
import httpx
from config import JIRA_BASE_URL, JIRA_PAT, JIRA_VERIFY_SSL
from services.markdown import escape, bold, link, build, italic, code

logger = logging.getLogger(__name__)

async def get_issue(issue_key: str) -> str:
    """Fetch issue details from Jira and return a formatted MarkdownV2 string."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        return "⚠️ Chưa cấu hình JIRA_BASE_URL hoặc JIRA_PAT trong .env"

    url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, timeout=15.0)
            
            if resp.status_code == 404:
                return f"❌ Không tìm thấy task {escape(issue_key)} trên Jira."
            elif resp.status_code == 401 or resp.status_code == 403:
                return "❌ Lỗi xác thực Jira (Token hết hạn hoặc không có quyền)."
            
            resp.raise_for_status()
            data = resp.json()
            
            fields = data.get("fields", {})
            summary = fields.get("summary", "Không có tiêu đề")
            status = fields.get("status", {}).get("name", "Unknown")
            priority = fields.get("priority", {}).get("name", "Unknown")
            
            assignee_data = fields.get("assignee")
            assignee = assignee_data.get("displayName") if assignee_data else "Chưa giao"
            
            # Optionally get description but truncate it
            description = fields.get("description") or ""
            if len(description) > 500:
                description = description[:500] + "..."

            issue_link = f"{JIRA_BASE_URL}/browse/{issue_key}"
            
            # Build MarkdownV2 text
            text = build(
                f"🎫 {bold('Jira Task')} {link(issue_key, issue_link)}",
                f"📌 {bold('Tiêu đề:')} {escape(summary)}",
                f"📊 {bold('Trạng thái:')} {escape(status)}",
                f"👤 {bold('Người xử lý:')} {escape(assignee)}",
                f"⚡ {bold('Độ ưu tiên:')} {escape(priority)}",
            )
            
            if description:
                text = build(text, "", f"📝 {bold('Mô tả:')}", italic(description))

            return text
            
    except httpx.RequestError as e:
        logger.error(f"Jira API error: {e}")
        return f"❌ Lỗi kết nối Jira: {escape(str(e))}"
    except Exception as e:
        logger.error(f"Jira Parse error: {e}", exc_info=True)
        return "❌ Có lỗi xảy ra khi đọc dữ liệu từ Jira."


def format_seconds(seconds: int) -> str:
    if not seconds:
        return "0h"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "0h"


async def get_missing_logwork(assignee: str = None) -> str:
    """Fetch issues from Jira for assignee and report tasks missing logwork."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        return "⚠️ Chưa cấu hình JIRA_BASE_URL hoặc JIRA_PAT trong .env"

    if assignee:
        jql = f'assignee = "{assignee}" AND (statusCategory != Done OR updated >= -30d)'
        search_target = f"user '{escape(assignee)}'"
    else:
        jql = 'assignee = currentUser() AND (statusCategory != Done OR updated >= -30d)'
        search_target = "bản thân"

    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,timeoriginalestimate,timespent,timeestimate,assignee",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)

            if resp.status_code == 401 or resp.status_code == 403:
                return "❌ Lỗi xác thực Jira (Token hết hạn hoặc không có quyền)."
            
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])

            missing_list = []
            for issue in issues:
                fields = issue.get("fields", {})
                orig = fields.get("timeoriginalestimate") or 0
                spent = fields.get("timespent") or 0
                
                # Check if original estimate is configured, and spent is less than estimate
                if orig > 0 and spent < orig:
                    missing_seconds = orig - spent
                    missing_list.append({
                        "key": issue["key"],
                        "summary": fields.get("summary", "Không có tiêu đề"),
                        "status": fields.get("status", {}).get("name", "Unknown"),
                        "orig": orig,
                        "spent": spent,
                        "missing": missing_seconds
                    })

            if not missing_list:
                return f"🎉 Tuyệt vời! Không tìm thấy task nào thiếu logwork cho {bold(search_target)} trong 30 ngày gần đây."

            total_missing = sum(item["missing"] for item in missing_list)
            total_missing_str = format_seconds(total_missing)

            lines = [
                f"📋 {bold('Task thiếu logwork của')} {bold(search_target)}:",
                f"⏰ {bold('Tổng số giờ thiếu log:')} {bold(total_missing_str)}",
                ""
            ]
            for item in missing_list:
                issue_link = f"{JIRA_BASE_URL}/browse/{item['key']}"
                orig_str = format_seconds(item['orig'])
                spent_str = format_seconds(item['spent'])
                missing_str = format_seconds(item['missing'])
                
                lines.append(
                    f"🎫 {link(item['key'], issue_link)}: {escape(item['summary'])}\n"
                    f"   📊 Trạng thái: {italic(item['status'])}\n"
                    f"   ⏱ Estimate: {code(orig_str)} | Logged: {code(spent_str)} | ⚠️ Còn thiếu: {bold(missing_str)}\n"
                )

            return build(*lines)

    except httpx.RequestError as e:
        logger.error(f"Jira API search error: {e}")
        return f"❌ Lỗi kết nối Jira: {escape(str(e))}"
    except Exception as e:
        logger.error(f"Jira Search parse error: {e}", exc_info=True)
        return "❌ Có lỗi xảy ra khi đọc danh sách task từ Jira."


async def get_upcoming_due_issues() -> list[dict]:
    """Fetch unresolved issues assigned to current user that have a duedate."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        logger.warning("Jira not configured. Cannot check due dates.")
        return []

    # Get unresolved issues with a due date assigned to current user
    jql = "assignee = currentUser() AND resolution = Unresolved AND duedate is not EMPTY"
    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,duedate",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            
            result = []
            for issue in issues:
                fields = issue.get("fields", {})
                result.append({
                    "key": issue["key"],
                    "summary": fields.get("summary", "Không có tiêu đề"),
                    "status": fields.get("status", {}).get("name", "Unknown"),
                    "duedate": fields.get("duedate")
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching upcoming due issues from Jira: {e}", exc_info=True)
        return []


async def get_issue_full(issue_key: str) -> dict | None:
    """Fetch full issue details from Jira including comments and changelog."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        logger.warning("Jira not configured.")
        return None

    url = f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "expand": "changelog,comments"
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)
            if resp.status_code == 404:
                logger.warning(f"Task {issue_key} not found on Jira.")
                return None
            resp.raise_for_status()
            data = resp.json()
            
            fields = data.get("fields", {})
            
            # Parse comments
            comments_data = fields.get("comment", {}).get("comments", [])
            comments = []
            for c in comments_data:
                author = c.get("author", {}).get("displayName", "Ẩn danh")
                comments.append({
                    "author": author,
                    "created": c.get("created"),
                    "body": c.get("body")
                })
            
            # Parse status history from changelog
            histories = data.get("changelog", {}).get("histories", [])
            status_history = []
            for h in histories:
                author = h.get("author", {}).get("displayName", "Hệ thống")
                created = h.get("created")
                for item in h.get("items", []):
                    if item.get("field") == "status":
                        status_history.append({
                            "author": author,
                            "created": created,
                            "from": item.get("fromString"),
                            "to": item.get("toString")
                        })
            
            return {
                "key": issue_key,
                "summary": fields.get("summary", "Không có tiêu đề"),
                "description": fields.get("description", ""),
                "status": fields.get("status", {}).get("name", "Unknown"),
                "priority": fields.get("priority", {}).get("name", "Unknown"),
                "assignee": fields.get("assignee", {}).get("displayName", "Chưa giao") if fields.get("assignee") else "Chưa giao",
                "created": fields.get("created"),
                "updated": fields.get("updated"),
                "duedate": fields.get("duedate"),
                "timeoriginalestimate": fields.get("timeoriginalestimate"),
                "timespent": fields.get("timespent"),
                "timeestimate": fields.get("timeestimate"),
                "comments": comments,
                "status_history": status_history
            }
    except Exception as e:
        logger.error(f"Error fetching full issue details for {issue_key}: {e}", exc_info=True)
        return None


async def get_active_issues(assignee: str = None) -> list[dict]:
    """Fetch unresolved issues assigned to assignee or current user."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        logger.warning("Jira not configured.")
        return []

    if assignee:
        jql = f'assignee = "{assignee}" AND statusCategory != Done'
    else:
        jql = 'assignee = currentUser() AND statusCategory != Done'

    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,updated,duedate",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            
            for issue in issues:
                fields = issue.get("fields", {})
                result.append({
                    "key": issue["key"],
                    "summary": fields.get("summary", "Không có tiêu đề"),
                    "status": fields.get("status", {}).get("name", "Unknown"),
                    "updated": fields.get("updated"),
                    "duedate": fields.get("duedate")
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching active issues: {e}", exc_info=True)
        return []


async def get_myself() -> dict | None:
    """Fetch details of the currently authenticated user."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        return None
    url = f"{JIRA_BASE_URL}/rest/api/2/myself"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.error(f"Error fetching myself details: {e}")
    return None


async def get_project_historical_issues(project_key: str = None, assignee: str = None, limit: int = 8) -> list[dict]:
    """Fetch completed issues from Jira for project or assignee as historical reference."""
    if not JIRA_BASE_URL or not JIRA_PAT:
        logger.warning("Jira not configured.")
        return []

    if project_key:
        jql = f'project = "{project_key}" AND statusCategory = Done AND timeoriginalestimate > 0'
    else:
        target = assignee if assignee else "currentUser()"
        jql = f'assignee = "{target}" AND statusCategory = Done AND timeoriginalestimate > 0'

    jql += " ORDER BY updated DESC"
    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "jql": jql,
        "maxResults": limit,
        "fields": "key,summary,description,timeoriginalestimate,timespent",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            
            result = []
            for issue in issues:
                fields = issue.get("fields", {})
                result.append({
                    "key": issue["key"],
                    "summary": fields.get("summary", ""),
                    "description": fields.get("description", ""),
                    "orig": fields.get("timeoriginalestimate") or 0,
                    "spent": fields.get("timespent") or 0,
                })
            return result
    except Exception as e:
        logger.error(f"Error fetching historical issues: {e}", exc_info=True)
        return []


async def get_weekly_dev_issues(assignee: str = None) -> dict:
    """Fetch active and resolved weekly issues, and compute total logged seconds for the week."""
    from datetime import datetime, timedelta

    if not JIRA_BASE_URL or not JIRA_PAT:
        return {"resolved": [], "active": [], "total_logged_seconds": 0, "target_display": "Chưa rõ"}

    # Define target and build JQL
    if assignee:
        jql = f'(assignee = "{assignee}" AND (statusCategory != Done OR resolved >= -7d)) OR (worklogAuthor = "{assignee}" AND worklogDate >= -7d)'
        target_username = assignee
        target_display = assignee
        target_user_info = None
    else:
        jql = '(assignee = currentUser() AND (statusCategory != Done OR resolved >= -7d)) OR (worklogAuthor = currentUser() AND worklogDate >= -7d)'
        target_user_info = await get_myself()
        target_username = target_user_info.get("name") if target_user_info else None
        target_display = target_user_info.get("displayName") if target_user_info else "bản thân"

    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    headers = {
        "Authorization": f"Bearer {JIRA_PAT}",
        "Content-Type": "application/json",
    }
    params = {
        "jql": jql,
        "maxResults": 100,
        "fields": "key,summary,status,timeoriginalestimate,timespent,timeestimate,assignee,updated,duedate,worklog",
    }

    try:
        async with httpx.AsyncClient(verify=JIRA_VERIFY_SSL) as client:
            resp = await client.get(url, headers=headers, params=params, timeout=20.0)
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            
            resolved_issues = []
            active_issues = []
            total_logged_seconds = 0
            
            # Date 7 days ago
            seven_days_ago_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

            for issue in issues:
                fields = issue.get("fields", {})
                issue_key = issue["key"]
                summary = fields.get("summary", "")
                status = fields.get("status", {}).get("name", "Unknown")
                
                status_cat_data = fields.get("status", {}).get("statusCategory", {})
                status_cat_name = status_cat_data.get("name", "").lower()
                status_cat_key = status_cat_data.get("key", "").lower()
                is_done = (status_cat_name == "done" or status_cat_key == "done")
                
                orig = fields.get("timeoriginalestimate") or 0
                spent = fields.get("timespent") or 0
                remaining = fields.get("timeestimate") or 0
                duedate = fields.get("duedate")
                
                issue_data = {
                    "key": issue_key,
                    "summary": summary,
                    "status": status,
                    "orig": orig,
                    "spent": spent,
                    "remaining": remaining,
                    "duedate": duedate
                }
                
                if is_done:
                    resolved_issues.append(issue_data)
                else:
                    active_issues.append(issue_data)
                    
                # Parse worklogs to calculate weekly logged seconds
                worklog_data = fields.get("worklog", {})
                worklogs = worklog_data.get("worklogs", [])
                
                for entry in worklogs:
                    author_info = entry.get("author", {})
                    author_name = author_info.get("name")
                    author_key = author_info.get("key")
                    author_display = author_info.get("displayName")
                    
                    is_match = False
                    if target_username:
                        if author_name == target_username or author_key == target_username:
                            is_match = True
                    if not is_match and target_user_info:
                        if (author_display == target_user_info.get("displayName") or 
                            author_name == target_user_info.get("name")):
                            is_match = True
                            
                    if is_match:
                        started = entry.get("started", "")[:10]
                        if started >= seven_days_ago_date:
                            total_logged_seconds += entry.get("timeSpentSeconds") or 0
                            
            return {
                "resolved": resolved_issues,
                "active": active_issues,
                "total_logged_seconds": total_logged_seconds,
                "target_display": target_display
            }
    except Exception as e:
        logger.error(f"Error fetching weekly dev issues: {e}", exc_info=True)
        return {"resolved": [], "active": [], "total_logged_seconds": 0, "target_display": target_display}



