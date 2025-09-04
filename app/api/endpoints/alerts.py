# app/api/endpoints/alerts.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List, Dict, Any
from app.services.alert_service import process_alerts

router = APIRouter()

class AlertRequest(BaseModel):
    groupid: str

class AlertDetail(BaseModel):
    host: str
    description: str
    severity: str
    timestamp: str

class HostInfo(BaseModel):
    hostid: str
    host: str
    monitoring_option: str

class AlertResponse(BaseModel):
    groupid: str
    hosts: List[HostInfo]
    hasAlert: bool
    alerts: List[AlertDetail]

@router.post("/alerts", response_model=AlertResponse)
async def get_alerts(request: AlertRequest):
    try:
        return await process_alerts(request.groupid)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
