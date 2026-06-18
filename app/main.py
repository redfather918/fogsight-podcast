"""
FastAPI 应用入口
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router
from app.models.job import init_db
from app.utils.logger import logger
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    await init_db()
    logger.info("数据库初始化完成")
    yield
    logger.info("应用关闭")


app = FastAPI(
    title="Fogsight Podcast — PDF to Video",
    version="1.0.0",
    lifespan=lifespan,
)

# 注册 API 路由
app.include_router(router, prefix="/api")

# 静态文件
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
