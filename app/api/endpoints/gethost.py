# app/api/endpoints/gethost.py
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.dependencies.zabbix import get_zapi
from app.services.host_service import fetch_hosts_by_groupid

router = APIRouter()

class GetHostRequest(BaseModel):
    groupid: str

@router.post("/gethost")
async def get_hosts(request: GetHostRequest, zapi=Depends(get_zapi)):
    try:
        hosts = await asyncio.to_thread(fetch_hosts_by_groupid, zapi, request.groupid)
        return {"hosts": hosts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
