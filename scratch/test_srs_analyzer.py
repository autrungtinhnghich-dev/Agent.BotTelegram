import asyncio
import os
import sys

# Thêm root path vào PYTHONPATH để import được các package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.brain_service import process_srs_file
from services.journal_db import check_srs_file_exists, delete_srs_file, init_db, search_srs_knowledge

async def test_duplicate_and_overwrite():
    print("=== Khởi chạy test Trùng Lặp & Ghi Đè SRS ===")
    
    # 1. Khởi tạo Database
    await init_db()
    
    file_name = "test_duplicate_srs.txt"
    file_path = os.path.join("scratch", file_name)
    
    # Tạo nội dung đặc tả
    srs_content = (
        "ĐẶC TẢ CHI TIẾT VỀ MẬT KHẨU USER\n"
        "Mật khẩu của người dùng bắt buộc phải có độ dài tối thiểu là 8 ký tự,\n"
        "chứa ít nhất 1 chữ hoa, 1 chữ thường và 1 số."
    )
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(srs_content)
        
    print(f"1. Đã tạo file đặc tả test: {file_name}")
    
    # 2. Kiểm tra xem file đã có trong DB chưa (Kỳ vọng: False)
    exists_before = await check_srs_file_exists(file_name)
    print(f"2. Kiểm tra sự tồn tại trước khi nạp: {exists_before} (Kỳ vọng: False)")
    
    # 3. Lập chỉ mục file lần đầu
    user_id = 999999
    chunks_saved = await process_srs_file(user_id, file_path, file_name)
    print(f"3. Đã lập chỉ mục lần đầu. Số chunks lưu: {chunks_saved}")
    
    # 4. Kiểm tra lại sự tồn tại (Kỳ vọng: True)
    exists_after = await check_srs_file_exists(file_name)
    print(f"4. Kiểm tra sự tồn tại sau khi nạp: {exists_after} (Kỳ vọng: True)")
    
    # 5. Thử tìm kiếm FTS xem đã có chưa
    results = await search_srs_knowledge("mật khẩu user", limit=2)
    print(f"5. Tìm kiếm thử: Thấy {len(results)} kết quả.")
    if results:
         print(f"   Nội dung: {results[0]['content']}")
         
    # 6. Thực hiện xóa / ghi đè (Xóa dữ liệu cũ)
    deleted_rows = await delete_srs_file(file_name)
    print(f"6. Thực hiện xóa file {file_name} khỏi database. Số dòng đã xóa: {deleted_rows} (Kỳ vọng: {chunks_saved})")
    
    # 7. Kiểm tra lại sự tồn tại sau khi xóa (Kỳ vọng: False)
    exists_final = await check_srs_file_exists(file_name)
    print(f"7. Kiểm tra sự tồn tại cuối cùng: {exists_final} (Kỳ vọng: False)")
    
    # Dọn dẹp file tạm
    if os.path.exists(file_path):
        os.remove(file_path)
    print("8. Đã dọn dẹp file tạm.")

if __name__ == "__main__":
    asyncio.run(test_duplicate_and_overwrite())
