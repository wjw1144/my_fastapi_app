#app/api/endpoints/update_file.py
from fastapi import APIRouter, HTTPException
from app.services.update_file_service import update_files, update_files_full
from app.schemas.update_file import UpdateFileRequest, UpdateFileFullRequest

router = APIRouter()

@router.post("/update_file")
async def update_file(request: UpdateFileRequest):
    result, status = await update_files(request.mcc, request.mnc, request.file_paths)
    if status != 200:
        raise HTTPException(status_code=status, detail=result.get("message"))
    return result

@router.post("/update_file_full")
async def update_file_full(request: UpdateFileFullRequest):
    result, status = await update_files_full(request.files)
    if status != 200:
        raise HTTPException(status_code=status, detail=result.get("message"))
    return result

