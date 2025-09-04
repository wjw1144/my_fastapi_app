# app/services/host_service.py
from pyzabbix import ZabbixAPI
import asyncio
from app.dependencies.zabbix import get_zapi
from app.services.ssh_service import verify_ssh_connection
import logging

def fetch_hosts_by_groupid(zapi: ZabbixAPI, groupid: str):
    hosts = zapi.host.get(
        groupids=groupid,
        output=["hostid", "host"],
        selectInterfaces=["interfaceid", "ip", "port", "available", "error"],
        selectInventory=["type"]
    )

    result = []
    for host in hosts:
        interfaces = [{
            'interfaceid': iface.get('interfaceid'),
            'ip': iface.get('ip'),
            'port': iface.get('port'),
            'available': iface.get('available'),
            'error': iface.get('error')
        } for iface in host.get('interfaces', [])]

        monitoring_option = host.get('inventory', {}).get('type', '未设置')

        result.append({
            'hostid': host.get('hostid'),
            'host': host.get('host'),
            'interfaces': interfaces,
            'monitoring_option': monitoring_option
        })

    return result

logger = logging.getLogger(__name__)

async def create_host(payload):
    zapi = get_zapi()

    ssh_host_ip = payload['interfaces'][0].get('ip')
    if not ssh_host_ip:
        raise ValueError("Invalid interfaces: missing IP")

    # 调用 ssh_service 的异步验证函数
    ssh_verified = await verify_ssh_connection(ssh_host_ip, payload['ssh_user'], payload['ssh_password'])
    if not ssh_verified:
        raise RuntimeError(f"SSH connection verification failed for {ssh_host_ip}")

    raw_templates = payload.get('templates') or []
    templates = [{"templateid": str(tid)} for tid in raw_templates] or [{"templateid": "10001"}]

    monitoring_option = payload['inventory'].get('monitoring_option')
    if monitoring_option is None:
        raise ValueError("monitoring_option is required in inventory")

    try:
        response = await asyncio.to_thread(
            zapi.host.create,
            host=payload['host'],
            groups=[{"groupid": str(gid)} for gid in payload['groups']],
            interfaces=payload['interfaces'],
            templates=templates,
            inventory={"type": str(monitoring_option)},
        )
        new_host_id = response['hostids'][0]
    except Exception as e:
        logger.error(f"Failed to create host in Zabbix: {e}")
        raise

    return new_host_id, ssh_host_ip

async def update_host(hostid: str, update_data: dict):
    zapi = get_zapi()

    def sync_update():
        zapi.host.update(**update_data)
    try:
        await asyncio.to_thread(sync_update)
    except Exception as e:
        logger.error(f"Failed to update host {hostid} in Zabbix: {e}")
        raise

async def delete_hosts(hostids: list):
    zapi = get_zapi()

    def sync_delete():
        return zapi.host.delete(*hostids)

    try:
        response = await asyncio.to_thread(sync_delete)
        return response
    except Exception as e:
        logger.error(f"Failed to delete hosts {hostids} in Zabbix: {e}")
        raise