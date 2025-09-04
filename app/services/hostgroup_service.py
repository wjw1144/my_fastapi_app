#app/services/hostgroup_service.py
from pyzabbix import ZabbixAPI
from app.core.config import settings
from app.utils.file_ops import ensure_dir, write_json_file
from typing import Dict, Any
import os

def create_hostgroup(zapi: ZabbixAPI, group_name: str, node_id: str) -> Dict[str, Any]:
    ensure_dir(settings.NET_CONF_DIR)

    existing_groups = zapi.hostgroup.get(filter={"name": group_name}, output="extend")

    if existing_groups:
        group_id = existing_groups[0]['groupid']
        return {
            "status": "exists",
            "message": f"Host group '{group_name}' already exists",
            "hostgroupid": group_id
        }

    response = zapi.hostgroup.create(name=group_name)
    new_group_id = response['groupids'][0]

    conf_path = os.path.join(settings.NET_CONF_DIR, f"{group_name}.json")
    config = {
        "group_id": int(new_group_id),
        "node_id": int(node_id),
        "hosts": {}
    }
    write_json_file(conf_path, config)

    return {
        "status": "success",
        "hostgroupid": new_group_id
    }
