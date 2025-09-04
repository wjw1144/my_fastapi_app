#app/api/endpoints/hostgroups.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from pyzabbix import ZabbixAPI
from app.dependencies.zabbix import get_zapi
from app.services.hostgroup_service import create_hostgroup


router = APIRouter()

class HostGroupRequest(BaseModel):
    name: str
    id: str | None = None

@router.post("/hostgroups", status_code=status.HTTP_201_CREATED)
def create_host_group(request: HostGroupRequest, zapi: ZabbixAPI = Depends(get_zapi)):
    try:
        result = create_hostgroup(zapi, request.name, request.id)
        if result["status"] == "exists":
            # 已存在返回 200 状态
            return {
                "status": "exists",
                "message": result["message"],
                "hostgroupid": result["hostgroupid"]
            }
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
