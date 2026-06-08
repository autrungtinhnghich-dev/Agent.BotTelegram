import json
import os

desktop_path = "/Users/macmini/Desktop/cookies.json"
output_path = "data/youtube_cookies.txt"

if not os.path.exists(desktop_path):
    print(f"Error: {desktop_path} does not exist!")
    exit(1)

with open(desktop_path, "r", encoding="utf-8") as f:
    json_data = json.load(f)

output_lines = [
    "# Netscape HTTP Cookie File",
    "# http://curl.haxx.se/rfc/cookie_spec.html",
    "# This is a generated file!  Do not edit.",
    ""
]

youtube_cookie_count = 0
for cookie in json_data:
    domain = cookie.get("domain", "")
    # Chỉ lọc các cookie thuộc domain youtube.com hoặc google.com
    if not (domain.endswith("youtube.com") or domain.endswith("google.com") or domain.endswith("youtube-nocookie.com")):
        continue
        
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    path = cookie.get("path", "/")
    secure = "TRUE" if cookie.get("secure", False) else "FALSE"
    
    exp = cookie.get("expirationDate", 0)
    if cookie.get("session", False) or exp is None:
        exp = 0
    else:
        exp = int(exp)
        
    name = cookie.get("name", "")
    value = cookie.get("value", "")
    
    line = f"{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{value}"
    output_lines.append(line)
    youtube_cookie_count += 1

# Đảm bảo thư mục data tồn tại
os.makedirs("data", exist_ok=True)

with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"Successfully generated {output_path} in Netscape format with {youtube_cookie_count} cookies!")
