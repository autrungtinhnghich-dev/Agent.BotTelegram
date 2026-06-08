import asyncio
import sys
import os

# Thêm thư mục gốc vào PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.search_service import search_duckduckgo

async def main():
    print("=== KIỂM THỬ DUCKDUCKGO SEARCH ===")
    results = search_duckduckgo("FastAPI WebSockets tutorial", limit=2)
    if results:
        for idx, r in enumerate(results):
            print(f"{idx+1}. Tiêu đề: {r['title']}")
            print(f"   URL: {r['url']}")
    else:
        print("❌ Không tìm thấy kết quả DuckDuckGo nào!")

    print("\n=== KIỂM THỬ DOCKER SERVICE ===")
    try:
        import docker
        import services.docker_service as docker_service
        containers = docker_service.list_containers()
        print(f"Tìm thấy {len(containers)} containers trên host:")
        for c in containers:
            print(f"- Tên: {c['name']} | ID: {c['id']} | Trạng thái: {c['status']} | Image: {c['image']}")
    except ImportError:
        print("❌ Thư viện 'docker' chưa được cài đặt trong môi trường chạy thử này.")
    except Exception as e:
        print(f"⚠️ Docker daemon không phản hồi hoặc không có quyền truy cập socket: {e}")

if __name__ == "__main__":
    asyncio.run(main())
