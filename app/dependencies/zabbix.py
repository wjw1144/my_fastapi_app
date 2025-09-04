# app/dependencies/zabbix.py
import asyncio
from pyzabbix import ZabbixAPI
from app.core.config import settings

_zapi = None

async def init_zapi_client():
    global _zapi
    def sync_init():
        zapi = ZabbixAPI(settings.ZABBIX_URL)
        zapi.login(settings.ZABBIX_USER, settings.ZABBIX_PASSWORD)
        return zapi
    _zapi = await asyncio.to_thread(sync_init)

def get_zapi():
    if _zapi is None:
        raise RuntimeError("ZabbixAPI client not initialized, call init_zapi_client first.")
    return _zapi
