#app/api/endpoints/log_manager.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any,Optional
from pydantic import BaseModel

from app.services.log_manager_service import LogManagerService

router = APIRouter()

class GroupRequest(BaseModel):
    group_id: str
    fetch_prev_page: Optional[int] = 0

class FullGroupLogsRequest(BaseModel):
    group_id: str
    offsets: Optional[Dict[str, int]] = None

class LoadOlderLogsRequest(BaseModel):
    group_id: str
    filename: str
    host_ip: str
    log_dir: str
    offset: int

class SingleLogRequest(BaseModel):
    group_id: str
    host_ip: str
    log_dir: str
    log_file: str


@router.post("/log_manager")
async def get_logs(request: GroupRequest):
    try:
        result = await LogManagerService.fetch_logs(
            group_id=request.group_id,
            fetch_prev_page=request.fetch_prev_page 
        )
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/full_group_logs")
async def full_group_logs(request: FullGroupLogsRequest):
    try:
        logs = await LogManagerService.read_full_group_logs(request.group_id)
        return JSONResponse(content=logs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/load_older_logs")
async def load_older_logs(request: LoadOlderLogsRequest):
    try:
        logs = await LogManagerService.load_older_logs(
            request.group_id, request.filename, request.host_ip,request.log_dir,request.offset
        )
        return JSONResponse(content=logs)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/single_log")
async def read_single_log(request: SingleLogRequest):
    try:
        result = await LogManagerService.read_single_log(
            request.group_id,
            request.host_ip,
            request.log_dir,
            request.log_file
        )
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
