from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from typing import List, Optional
from pydantic import BaseModel, Field
from app.services.ssh_service import verify_ssh_connection
import os
import json
import logging
import asyncio
from app.services import host_service
from app.dependencies.zabbix import get_zapi

logger = logging.getLogger(__name__)
router = APIRouter()

NET_CONF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'net-conf')
os.makedirs(NET_CONF_DIR, exist_ok=True)

class Interface(BaseModel):
    type: Optional[int]
    main: Optional[int]
    useip: Optional[int]
    ip: str
    dns: Optional[str]
    port: Optional[str]

class HostPayload(BaseModel):
    host: str
    groups: List[int]
    interfaces: List[Interface]
    inventory: dict
    templates: Optional[List[int]] = Field(default_factory=list)
    ssh_user: str
    ssh_password: str

class UpdateHostPayload(BaseModel):
    host: Optional[str]
    groups: Optional[List[int]]
    interfaces: Optional[List[Interface]]
    monitoring: Optional[int]
    templates: Optional[List[int]]

class DeleteHostsPayload(BaseModel):
    hostids: List[int]

@router.get("/hosts")
async def get_hosts():
    zapi = get_zapi()
    try:
        hosts = await asyncio.to_thread(zapi.host.get, output="extend")
        return hosts
    except Exception as e:
        logger.error(f"Failed to get hosts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/hosts", status_code=status.HTTP_201_CREATED)
async def create_host(payload: HostPayload):
    try:
        new_host_id, ssh_host_ip = await host_service.create_host(payload.dict())
    except Exception as e:
        logger.error(f"Create host error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    groups = payload.groups
    host_name = payload.host
    try:
        for gid in groups:
            updated = False
            for fname in os.listdir(NET_CONF_DIR):
                fpath = os.path.join(NET_CONF_DIR, fname)
                with open(fpath, 'r+', encoding='utf-8') as cfgf:
                    cfg = json.load(cfgf)
                    if str(cfg.get('group_id')) == str(gid):
                        hosts = cfg.setdefault('hosts', {})
                        hosts[ssh_host_ip] = {
                            'host_name': host_name,
                            'host_id': str(new_host_id),
                            "conf_dir": "",
                            "log_dir": [],
                            "db_path": "",  # 可选：占位，供你后续填写
                            "start_script_path": "",
                            "stop_script_path": "",
                            "conf_paths": [],
                            "log_paths": [],
                            "roles": []
                        }
                        cfgf.seek(0)
                        json.dump(cfg, cfgf, indent=2)
                        cfgf.truncate()
                        updated = True
            if not updated:
                logger.warning(f"No matching config file found for group {gid}")
    except Exception as e:
        logger.error(f"Error updating config files: {e}")

    return JSONResponse({
        'status': 'success',
        'hostid': new_host_id,
        'ssh_verified': True
    })

@router.put("/hosts/{hostid}")
async def update_host(hostid: str, payload: UpdateHostPayload):
    update_data = {'hostid': hostid}
    if payload.host:
        update_data['host'] = payload.host
    if payload.groups:
        update_data['groups'] = [{"groupid": str(gid)} for gid in payload.groups]
    if payload.interfaces:
        update_data['interfaces'] = [i.dict() for i in payload.interfaces]
    if payload.monitoring is not None:
        update_data['inventory'] = {"type": str(payload.monitoring)}
    if payload.templates:
        update_data['templates'] = [{"templateid": str(tid)} for tid in payload.templates]

    try:
        await host_service.update_host(hostid, update_data)
    except Exception as e:
        logger.error(f"Update host error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return {'status': 'success', 'message': 'Host updated successfully.'}

@router.delete("/hosts")
async def delete_hosts(payload: DeleteHostsPayload):
    str_hostids = [str(h) for h in payload.hostids]
    try:
        response = await host_service.delete_hosts(str_hostids)
    except Exception as e:
        logger.error(f"Delete hosts error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "success",
        "message": "Hosts deleted successfully.",
        "response": response
    }