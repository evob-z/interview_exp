"""面试助手 Web 服务入口"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes import qa, profile, sync, stats, history, followup, asr, prepare
from logger import get_logger

api_logger = get_logger("api")

app = FastAPI(
    title="面试助手",
    description="个人面试复盘与快速问答系统",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    # 仅记录 API 调用，跳过静态文件
    if request.url.path.startswith("/api/"):
        api_logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.2f}s)")
    return response


# 注册路由
app.include_router(qa.router, prefix="/api/qa", tags=["问答"])
app.include_router(profile.router, prefix="/api/profile", tags=["画像"])
app.include_router(sync.router, prefix="/api/sync", tags=["同步"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(followup.router, prefix="/api/followup", tags=["追问预测"])
app.include_router(asr.router, prefix="/api/asr", tags=["语音识别"])
app.include_router(prepare.router, prefix="/api/prepare", tags=["岗位预测"])

# 静态文件（前端）
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "static")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT)
