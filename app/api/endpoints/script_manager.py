from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from enum import Enum
from app.services.script_manager_service import manage_script, send_command_to_group, check_status, ping_host_from_remote

router = APIRouter()

class ScriptAction(str, Enum):
    start = "start"
    stop = "stop"

class ScriptRequest(BaseModel):
    group_id: str
    action: ScriptAction

class CommandRequest(BaseModel):
    group_id: str
    command: str  # 例如: 'tx_gain 0 40'

class StatusRequest(BaseModel):
    group_id: str
    
class PingRequest(BaseModel):
    group_id: str
    target_ip: str  # 控制端 IP

@router.post("/ping_host")
async def ping_host(request: PingRequest):
    result, status_code = await ping_host_from_remote(request.group_id, request.target_ip)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.get("message"))
    return result
    
@router.post("/start_or_stop")
async def script_manager(request: ScriptRequest):
    result, status_code = await manage_script(request.group_id, request.action)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.get("message"))
    return result

@router.post("/send_command")
async def send_command(request: CommandRequest):
    result, status_code = await send_command_to_group(request.group_id, request.command)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.get("message"))
    return result


@router.post("/check_status")
async def check_service_status(request: StatusRequest):
    result, status_code = await check_status(request.group_id)
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=result.get("message"))
    return result
