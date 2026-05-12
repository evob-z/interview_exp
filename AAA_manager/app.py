"""面试助手 Web 服务入口"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import config
from api.routes import qa, profile, sync, stats, history, followup, asr

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

# 注册路由
app.include_router(qa.router, prefix="/api/qa", tags=["问答"])
app.include_router(profile.router, prefix="/api/profile", tags=["画像"])
app.include_router(sync.router, prefix="/api/sync", tags=["同步"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(followup.router, prefix="/api/followup", tags=["追问预测"])
app.include_router(asr.router, prefix="/api/asr", tags=["语音识别"])

# 静态文件（前端）
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "static")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT)
