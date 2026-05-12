"""FastAPI 主入口"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.gateway import gateway
from app.core.router import dynamic_router, register_all_workflows
from app.manager.config_manager import config_manager
from app.manager.server_manager import server_manager
from app.manager.stats import stats_manager
from app.utils.logger import setup_logging, get_logger
from app.web.admin import admin_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时加载配置，关闭时清理资源"""
    setup_logging()
    logger.info("=" * 50)
    logger.info(f"ComfyUI API Gateway starting on {settings.gateway_host}:{settings.gateway_port}")

    # 加载服务器配置
    server_manager.load_servers()

    # 加载 workflow 配置
    config_manager.load_all()

    # 注册动态路由
    register_all_workflows(dynamic_router)

    # 后台任务
    health_task = asyncio.create_task(server_manager.health_check_loop())
    cleanup_task = asyncio.create_task(gateway.cleanup_old_tasks())

    logger.info("Gateway ready. Workflow routes registered.")

    yield

    # 关闭
    logger.info("Shutting down...")
    health_task.cancel()
    cleanup_task.cancel()
    await stats_manager.close()
    logger.info("Gateway stopped.")


app = FastAPI(
    title="ComfyUI API Gateway",
    description="统一 API 网关，管理多个 ComfyUI 后端服务器的 workflow 执行",
    version="0.1.0",
    lifespan=lifespan,
)

# 静态文件
static_dir = Path(__file__).resolve().parent / "web" / "static"
app.mount("/admin/static", StaticFiles(directory=str(static_dir)), name="admin_static")

# 注册路由
app.include_router(dynamic_router)
app.include_router(admin_router)


# ── 任务查询 API ────────────────────────────────────

@app.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态和结果"""
    task = gateway.get_task(task_id)
    if task is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return task


@app.post("/task/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    ok = gateway.cancel_task(task_id)
    return {"ok": ok}


# ── 健康检查 ────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "comfyui-api-gateway",
        "version": "0.1.0",
    }
