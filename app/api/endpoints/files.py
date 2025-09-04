#app/api/endpoints/files.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.file_service import copy_files_by_group_id

router = APIRouter()

class FileCopyRequest(BaseModel):
    group_id: str

@router.post("/files")
async def copy_files(request: FileCopyRequest):
    result, status = await copy_files_by_group_id(request.group_id)
    if status != 200:
        raise HTTPException(status_code=status, detail=result["message"])
    return result
