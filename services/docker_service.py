import logging
import socket
import docker

logger = logging.getLogger(__name__)

def _is_self(c) -> bool:
    """Kiểm tra xem container được thao tác có phải là chính container đang chạy bot không."""
    try:
        hostname = socket.gethostname()
        return c.id.startswith(hostname) or hostname in c.id
    except Exception:
        return False

def _get_client():
    """Khởi tạo Docker Client từ môi trường."""
    try:
        # Mặc định sử dụng socket unix:///var/run/docker.sock mount từ host
        return docker.from_env()
    except Exception as e:
        logger.error(f"Không thể kết nối Docker Daemon: {e}")
        raise RuntimeError("Không thể kết nối Docker Daemon. Hãy chắc chắn /var/run/docker.sock đã được mount đúng cách.")

def list_containers() -> list[dict]:
    """Lấy danh sách tất cả các containers trên host."""
    try:
        client = _get_client()
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            # Lấy thông tin cổng (Ports)
            ports_info = []
            raw_ports = c.attrs.get('HostConfig', {}).get('PortBindings', {}) or {}
            for c_port, h_ports in raw_ports.items():
                if h_ports:
                    h_port = h_ports[0].get('HostPort')
                    ports_info.append(f"{h_port}->{c_port}")
                else:
                    ports_info.append(c_port)
            
            result.append({
                "id": c.short_id,
                "name": c.name,
                "image": c.attrs.get('Config', {}).get('Image', 'unknown'),
                "status": c.status, # running, exited, paused, etc.
                "ports": ", ".join(ports_info) if ports_info else "none",
                "created": c.attrs.get('Created', '')[:19].replace('T', ' ')
            })
        return result
    except Exception as e:
        logger.error(f"Lỗi khi list containers: {e}")
        return []

def get_container_logs(container_id: str, tail: int = 50) -> str:
    """Lấy log mới nhất của một container."""
    try:
        client = _get_client()
        c = client.containers.get(container_id)
        logs = c.logs(tail=tail, stdout=True, stderr=True)
        return logs.decode('utf-8', errors='replace')
    except Exception as e:
        logger.error(f"Lỗi khi lấy log container {container_id}: {e}")
        return f"Lỗi khi lấy log: {str(e)}"

def manage_container(container_id: str, action: str) -> dict:
    """
    Điều khiển trạng thái container.
    action: 'start', 'stop', 'restart'
    """
    try:
        client = _get_client()
        c = client.containers.get(container_id)
        
        if action in ["stop", "restart"] and _is_self(c):
            return {
                "status": "failed", 
                "error": "Đây là container của chính Bot đang chạy. Để tránh sập bot hoàn toàn, bạn không thể dừng hoặc khởi động lại chính nó qua Telegram."
            }
            
        if action == "start":
            c.start()
        elif action == "stop":
            c.stop(timeout=10)
        elif action == "restart":
            c.restart(timeout=10)
        else:
            return {"status": "failed", "error": f"Hành động không hợp lệ: {action}"}
            
        return {"status": "success", "message": f"Đã thực hiện {action} container {c.name} thành công."}
    except Exception as e:
        logger.error(f"Lỗi khi thực hiện {action} trên container {container_id}: {e}")
        return {"status": "failed", "error": str(e)}

def redeploy_container(container_id: str) -> dict:
    """
    Kéo image mới nhất và khởi chạy lại container với cấu hình cũ.
    """
    try:
        client = _get_client()
        c = client.containers.get(container_id)
        name = c.name
        
        if _is_self(c):
            return {
                "status": "failed", 
                "error": "Đây là container của chính Bot đang chạy. Việc tự dừng container để tái triển khai sẽ làm sập tiến trình của bot. Vui lòng cập nhật trên server bằng lệnh: docker compose up -d --build"
            }
            
        # 1. Thu thập cấu hình hiện tại để tái tạo
        attrs = c.attrs
        image_name = attrs.get('Config', {}).get('Image')
        if not image_name:
            return {"status": "failed", "error": "Không tìm thấy tên Image của container."}
            
        environment = attrs.get('Config', {}).get('Env', [])
        command = attrs.get('Config', {}).get('Cmd', None)
        entrypoint = attrs.get('Config', {}).get('Entrypoint', None)
        
        # Xử lý port bindings
        ports = {}
        raw_ports = attrs.get('HostConfig', {}).get('PortBindings', {}) or {}
        for container_port, host_bindings in raw_ports.items():
            if host_bindings:
                binding = host_bindings[0]
                host_port = binding.get('HostPort')
                host_ip = binding.get('HostIp', '')
                if host_ip:
                    ports[container_port] = (host_ip, host_port)
                else:
                    ports[container_port] = host_port
                    
        # Xử lý volumes (Binds)
        volumes = attrs.get('HostConfig', {}).get('Binds', [])
        
        # Xử lý Restart Policy
        restart_policy = attrs.get('HostConfig', {}).get('RestartPolicy', {})
        network_mode = attrs.get('HostConfig', {}).get('NetworkMode', 'default')
        labels = attrs.get('Config', {}).get('Labels', {})
        
        logger.info(f"Đang kéo (pull) image mới nhất cho: {image_name}...")
        # 2. Pull image mới nhất
        try:
            client.images.pull(image_name)
        except Exception as pull_err:
            logger.warning(f"Lỗi khi pull image {image_name} (Có thể do offline hoặc private registry): {pull_err}")
            # Vẫn tiếp tục redeploy với image local hiện tại nếu không pull được
            
        logger.info(f"Đang dừng container cũ: {name}...")
        # 3. Dừng và xóa container cũ
        try:
            c.stop(timeout=15)
            c.remove()
        except Exception as rm_err:
            logger.error(f"Lỗi khi xóa container cũ {name}: {rm_err}")
            return {"status": "failed", "error": f"Lỗi khi xóa container cũ: {str(rm_err)}"}
            
        logger.info(f"Đang khởi tạo container mới: {name} với image {image_name}...")
        # 4. Tạo và chạy container mới
        new_container = client.containers.run(
            image=image_name,
            name=name,
            detach=True,
            environment=environment,
            ports=ports,
            volumes=volumes,
            restart_policy=restart_policy,
            network_mode=network_mode,
            command=command,
            entrypoint=entrypoint,
            labels=labels
        )
        
        return {
            "status": "success", 
            "message": f"Đã tái triển khai (re-deploy) container {name} thành công.",
            "new_id": new_container.short_id
        }
    except Exception as e:
        logger.error(f"Lỗi khi redeploy container {container_id}: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}
