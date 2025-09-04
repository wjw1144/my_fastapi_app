#app/utils/async_config_manager.py
import json
import asyncio
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # 定位到 app/
CONFIG_DIR = BASE_DIR / "net-conf"
CONFIG_FILE = CONFIG_DIR / "ssh_config.json"
_lock = asyncio.Lock()  # ✅ 模块级定义

async def _async_write_file(path: Path, data: str):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, path.write_text, data)

async def _async_read_file(path: Path) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, path.read_text)

async def _ensure_config_file():
    if not CONFIG_DIR.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        async with _lock:
            if not CONFIG_FILE.exists():
                await _async_write_file(CONFIG_FILE, json.dumps({}, indent=4))

async def read_config():
    await _ensure_config_file()
    async with _lock:
        try:
            content = await _async_read_file(CONFIG_FILE)
            return json.loads(content)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

async def write_config(config: dict):
    async with _lock:
        await _async_write_file(CONFIG_FILE, json.dumps(config, indent=4))

async def add_host_config(host_ip: str, username: str, password: str):
    config = await read_config()
    config[host_ip] = {"username": username, "password": password}
    await write_config(config)

async def get_host_config(host_ip: str):
    config = await read_config()
    return config.get(host_ip)

async def remove_host_config(host_ip: str):
    config = await read_config()
    if host_ip in config:
        del config[host_ip]
        await write_config(config)

async def update_host_config(host_ip: str, username: str = None, password: str = None):
    config = await read_config()
    if host_ip in config:
        if username is not None:
            config[host_ip]["username"] = username
        if password is not None:
            config[host_ip]["password"] = password
        await write_config(config)
