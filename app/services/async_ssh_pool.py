#app/services/async_ssh_pool.py
import asyncio
import asyncssh
import time
import traceback
import logging
from app.utils import async_config_manager as cfg_mgr

logger = logging.getLogger(__name__)

class ManagedSSHConnection:
    def __init__(self, host_ip, username, password):
        self.host_ip = host_ip
        self.username = username
        self.password = password
        self.conn = None
        self.lock = asyncio.Lock()
        self._keepalive_task = None
        self._closed = False
        self.channel_lock = asyncio.Lock()  # 新增channel访问锁

    async def connect(self):
        async with self.lock:
            if self.conn and not self.conn._transport.is_closing():
                return
            try:
                logger.info(f"[SSH_POOL] Connecting to {self.host_ip} as {self.username}")
                self.conn = await asyncssh.connect(
                    host=self.host_ip,
                    username=self.username,
                    password=self.password,
                    known_hosts=None,
                    keepalive_interval=30,
                    keepalive_count_max=3,
                )
                logger.info(f"[SSH_POOL] Connected to {self.host_ip}")
                if self._keepalive_task is None or self._keepalive_task.done():
                    self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            except Exception as e:
                logger.error(f"[SSH_POOL] Failed to connect to {self.host_ip}: {e}")
                self.conn = None
                raise

    async def _keepalive_loop(self):
        try:
            while not self._closed:
                await asyncio.sleep(20)
                async with self.lock:
                    if self.conn is None or self.conn._transport.is_closing():
                        logger.warning(f"[SSH_POOL] Connection lost to {self.host_ip}, reconnecting...")
                        try:
                            await self.connect()
                        except Exception as e:
                            logger.error(f"[SSH_POOL] Reconnection failed for {self.host_ip}: {e}")
                    else:
                        try:
                            result = await self.conn.run('echo keepalive', check=True)
                            if result.stdout.strip() != 'keepalive':
                                logger.warning(f"[SSH_POOL] Unexpected keepalive response from {self.host_ip}: {result.stdout}")
                        except Exception as e:
                            logger.warning(f"[SSH_POOL] Keepalive command failed for {self.host_ip}: {e}, reconnecting...")
                            await self.connect()
        except asyncio.CancelledError:
            logger.info(f"[SSH_POOL] Keepalive loop cancelled for {self.host_ip}")

    async def get_connection(self):
        async with self.lock:
            if self.conn is None or self.conn._transport.is_closing():
                logger.info(f"[SSH_POOL] Connection invalid for {self.host_ip}, reconnecting...")
                await self.connect()
            return self.conn

    async def close(self):
        self._closed = True
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            if self.conn:
                self.conn.close()
                await self.conn.wait_closed()
                logger.info(f"[SSH_POOL] Closed connection to {self.host_ip}")
                self.conn = None

class AsyncSSHConnectionPool:
    def __init__(self, idle_timeout=3600, cleanup_interval=300):
        self.pool = {}  # host_ip -> ManagedSSHConnection
        self.lock = asyncio.Lock()
        self.idle_timeout = idle_timeout  # 延长空闲超时，避免频繁关闭
        self.cleanup_interval = cleanup_interval
        self._cleanup_task = asyncio.create_task(self._cleanup_idle_connections_loop())
        logger.info(f"[SSH_POOL] Initialized with idle_timeout={idle_timeout}s, cleanup_interval={cleanup_interval}s")

    async def _cleanup_idle_connections_loop(self):
        while True:
            await asyncio.sleep(self.cleanup_interval)
            await self._cleanup_idle_connections()

    async def _cleanup_idle_connections(self):
        # 你可以保留关闭空闲连接逻辑，这里简化为只关闭连接超过idle_timeout的连接
        async with self.lock:
            now = time.time()
            to_close = []
            for host_ip, conn_obj in self.pool.items():
                # 这里可以增加额外判断是否空闲，比如记录最后使用时间，示例略
                # 如果需要，也可以直接不关闭连接，保持常连接状态
                pass
            # 如果不想关闭任何连接，这里留空即可

    async def get_connection(self, host_ip, username=None, password=None):
        async with self.lock:
            if not (username and password):
                host_cfg = await cfg_mgr.get_host_config(host_ip)
                if host_cfg:
                    username = host_cfg.get("username")
                    password = host_cfg.get("password")
                    logger.info(f"[SSH_POOL] Loaded credentials from config for {host_ip}")
                else:
                    logger.warning(f"[SSH_POOL] No credentials for {host_ip}")
                    raise ValueError(f"No credentials found for {host_ip}")

            if host_ip not in self.pool:
                managed_conn = ManagedSSHConnection(host_ip, username, password)
                try:
                    await managed_conn.connect()
                    self.pool[host_ip] = managed_conn
                    await cfg_mgr.add_host_config(host_ip, username, password)
                except Exception:
                    return None
            else:
                managed_conn = self.pool[host_ip]
                # 确保配置是最新的
                if managed_conn.username != username or managed_conn.password != password:
                    logger.info(f"[SSH_POOL] Credentials changed for {host_ip}, reconnecting")
                    await managed_conn.close()
                    managed_conn = ManagedSSHConnection(host_ip, username, password)
                    try:
                        await managed_conn.connect()
                        self.pool[host_ip] = managed_conn
                        await cfg_mgr.add_host_config(host_ip, username, password)
                    except Exception:
                        return None

            try:
                conn = await managed_conn.get_connection()
                return conn
            except Exception as e:
                logger.error(f"[SSH_POOL] Failed to get connection for {host_ip}: {e}")
                return None

    async def close_connection(self, host_ip):
        async with self.lock:
            managed_conn = self.pool.get(host_ip)
            if managed_conn:
                await managed_conn.close()
                self.pool.pop(host_ip, None)
                await cfg_mgr.remove_host_config(host_ip)
                logger.info(f"[SSH_POOL] Removed connection for {host_ip}")

    async def close_all(self):
        logger.info("[SSH_POOL] Closing all SSH connections")
        async with self.lock:
            conns = list(self.pool.values())
            self.pool.clear()
        for conn in conns:
            await conn.close()

# 全局单例
ssh_pool = AsyncSSHConnectionPool(idle_timeout=3600, cleanup_interval=300)
