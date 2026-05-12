"""Web 管理面板"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.manager.config_manager import config_manager
from app.manager.server_manager import server_manager
from app.manager.stats import stats_manager
from app.models.workflow import WorkflowConfig, WorkflowInput
from app.config import settings

admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Jinja2 模板路径
from fastapi.templating import Jinja2Templates
from pathlib import Path

_tpl_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_tpl_dir))


# ── 页面路由 ────────────────────────────────────────

@admin_router.get("/", response_class=HTMLResponse)
async def admin_index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"request": request})


@admin_router.get("/configs", response_class=HTMLResponse)
async def configs_page(request: Request):
    configs = config_manager.list_all()
    return templates.TemplateResponse(
        request, "configs.html",
        {"request": request, "configs": configs},
    )


@admin_router.get("/configs/new", response_class=HTMLResponse)
async def new_config_page(request: Request):
    return templates.TemplateResponse(request, "config_new.html", {"request": request})


@admin_router.get("/servers", response_class=HTMLResponse)
async def servers_page(request: Request):
    servers = server_manager.get_all_servers()
    status_list = server_manager.get_all_status()
    return templates.TemplateResponse(
        request, "servers.html",
        {"request": request, "servers": servers, "status_list": status_list},
    )


@admin_router.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    all_stats = await stats_manager.get_all_stats()
    recent = await stats_manager.get_recent_tasks(100)
    return templates.TemplateResponse(
        request, "stats.html",
        {"request": request, "stats": all_stats, "recent": recent},
    )


# ── API 路由 ────────────────────────────────────────

@admin_router.get("/api/configs")
async def list_configs():
    return config_manager.list_all()


@admin_router.post("/api/configs")
async def create_config(
    name: str = Form(...),
    route: str = Form(...),
    description: str = Form(""),
    workflow_file: str = Form(""),
    timeout: int = Form(120),
    backend_servers: str = Form(""),
    output_node_id: str = Form(""),
    inputs_json: str = Form("[]"),
):
    """创建新的 workflow config"""
    import json
    inputs_data = json.loads(inputs_json)

    config = WorkflowConfig(
        name=name,
        route=route,
        method="POST",
        description=description,
        workflow_file=workflow_file,
        timeout=timeout,
        backend_servers=[s.strip() for s in backend_servers.split(",") if s.strip()],
        output_node_id=output_node_id,
        inputs=[
            WorkflowInput(**inp) for inp in inputs_data
        ],
    )
    config_manager.save(config)
    return {"ok": True, "route": route}


@admin_router.post("/api/configs/analyze")
async def analyze_workflow(workflow_file: UploadFile = File(...)):
    """上传 workflow JSON → AI 分析 → 返回推荐 config"""
    import json
    content = await workflow_file.read()
    try:
        workflow = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    suggested = config_manager.analyze_workflow_json(workflow)
    return suggested.model_dump()


@admin_router.delete("/api/configs/{route:path}")
async def delete_config(route: str):
    ok = config_manager.delete(route)
    if not ok:
        raise HTTPException(404, "Config not found")
    return {"ok": True}


@admin_router.post("/api/reload")
async def reload_configs():
    """热重载所有 config"""
    config_manager.reload()
    return {"ok": True, "count": len(config_manager.list_all())}


@admin_router.get("/api/servers")
async def list_servers():
    return server_manager.get_all_status()


@admin_router.post("/api/servers/check")
async def check_servers():
    await server_manager.check_all()
    return server_manager.get_all_status()


@admin_router.get("/api/stats")
async def get_stats():
    return await stats_manager.get_all_stats()


@admin_router.get("/api/tasks/recent")
async def get_recent_tasks(limit: int = 50):
    return await stats_manager.get_recent_tasks(limit)
