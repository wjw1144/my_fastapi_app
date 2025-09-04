# app/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache
import os

class Settings(BaseSettings):
    ZABBIX_URL: str
    ZABBIX_USER: str
    ZABBIX_PASSWORD: str
    FLASK_ENV: str = "production"  # 保留兼容项，可删
    NET_CONF_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'net-conf'))

    class Config:
        env_file = ".env"  # 自动加载 .env 文件

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
