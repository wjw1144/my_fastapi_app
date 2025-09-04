from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from app.services.user_service import UserService
import traceback

router = APIRouter()

class UserBase(BaseModel):
    imsi: str
    msisdn: str
    msc_number: Optional[str] = "unnamed-MSC"

class UserCreate(UserBase):
    group_id: str

class UserUpdate(BaseModel):
    group_id: str
    msisdn: str
    msc_number: Optional[str] = None

class UserBatchAddReq(BaseModel):
    group_id: str
    users: List[UserBase]

class DeleteUserReq(BaseModel):
    group_id: str

@router.get("/users")
async def get_users(group_id: str = Query(...)):
    print(f"[DEBUG] GET /users called with group_id={group_id}")
    try:
        users = UserService.get_users(group_id)
        print(f"[DEBUG] GET /users success, user count: {len(users)}")
        return {"status": "success", "users": users}
    except Exception as e:
        print(f"[ERROR] GET /users failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users", status_code=201)
async def add_user(user: UserCreate):
    print(f"[DEBUG] POST /users called with user={user}")
    try:
        host_ip, db_path_remote = UserService.add_user(user.group_id, user.imsi, user.msisdn, user.msc_number)
        print(f"[DEBUG] User added. Syncing DB to remote: {host_ip}, {db_path_remote}")
        await UserService.sync_db_file_to_remote(host_ip, db_path_remote)
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] POST /users failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/users/{imsi}")
async def update_user(imsi: str, user: UserUpdate):
    print(f"[DEBUG] PUT /users/{imsi} called with user={user}")
    try:
        host_ip, db_path_remote = UserService.update_user(user.group_id, imsi, user.msisdn, user.msc_number)
        print(f"[DEBUG] User updated. Syncing DB to remote: {host_ip}, {db_path_remote}")
        await UserService.sync_db_file_to_remote(host_ip, db_path_remote)
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] PUT /users/{imsi} failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/users/{imsi}")
async def delete_user(imsi: str, body: DeleteUserReq):
    print(f"[DEBUG] DELETE /users/{imsi} called with group_id={body.group_id}")
    try:
        host_ip, db_path_remote = UserService.delete_user(body.group_id, imsi)
        print(f"[DEBUG] User deleted. Syncing DB to remote: {host_ip}, {db_path_remote}")
        await UserService.sync_db_file_to_remote(host_ip, db_path_remote)
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] DELETE /users/{imsi} failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/users/batch", status_code=201)
async def batch_add_users(batch: UserBatchAddReq):
    print(f"[DEBUG] POST /users/batch called with {len(batch.users)} users")
    try:
        host_ip, db_path_remote = UserService.batch_add_users(batch.group_id, [user.dict() for user in batch.users])
        print(f"[DEBUG] Users batch added. Syncing DB to remote: {host_ip}, {db_path_remote}")
        await UserService.sync_db_file_to_remote(host_ip, db_path_remote)
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] POST /users/batch failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
