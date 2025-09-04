from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.logger import logger
from app.core.limiter import limiter
from app.api.endpoints import gethost, hostgroups, hosts, alerts, files, update_file, script_manager, log_manager, users
from app.dependencies import zabbix
import os
from fastapi.staticfiles import StaticFiles


app = FastAPI()

# ✅ 添加 CORS 中间件，支持前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议指定域名，例如 ["https://your-frontend.com"]
    allow_credentials=True,
    allow_methods=["*"],  # 允许包括 OPTIONS 在内的所有方法
    allow_headers=["*"],  # 允许所有请求头
)

# 限速相关
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"message": "Too many requests"})

@app.get("/")
async def root():
    logger.info("Root path accessed.")
    return {"message": "Welcome to FastAPI App"}

@app.on_event("startup")
async def startup_event():
    await zabbix.init_zapi_client()

@app.on_event("shutdown")
async def shutdown_event():
    # 清理任务（如关闭连接池等）可写在这里
    pass

# 设置文件保存目录
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
FILES_DIR = os.path.join(BASE_DIR, 'files')
os.makedirs(FILES_DIR, exist_ok=True)

# 挂载 /files 路径，用于访问复制后的文件
app.mount("/files", StaticFiles(directory=FILES_DIR), name="files") 
# ✅ 注册 API 路由
app.include_router(gethost.router, prefix="/api")
app.include_router(hostgroups.router, prefix="/api")
app.include_router(hosts.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(update_file.router, prefix="/api")
app.include_router(script_manager.router, prefix="/api")
app.include_router(log_manager.router, prefix="/api")
app.include_router(users.router, prefix="/api")
