#app/services/ssh_service.py
from app.services.async_ssh_pool import ssh_pool
import logging

logger = logging.getLogger(__name__)

async def verify_ssh_connection(host_ip: str, username: str, password: str) -> bool:
    conn = await ssh_pool.get_connection(host_ip, username, password)
    if not conn:
        logger.error(f"[SSH_SERVICE] Failed to get SSH connection for {host_ip}")
        return False
    try:
        result = await conn.run('echo SSH_OK', check=True)
        return result.stdout.strip() == "SSH_OK"
    except Exception as e:
        logger.error(f"[SSH_SERVICE] SSH verification failed for {host_ip}: {e}")
        return False

