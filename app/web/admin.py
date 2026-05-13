"""Web 管理面板"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.manager.config_manager import config_manager
from app.manager.server_manager import server_manager
from app.manager.settings_manager import settings_manager
from app.manager.stats import stats_manager
from app.models.workflow import WorkflowConfig, WorkflowInput
from app.config import settings

admin_router = APIRouter(prefix="", tags=["admin"])

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
    server_map = {s.id: s.name for s in server_manager.get_all_servers()}
    return templates.TemplateResponse(
        request, "configs.html",
        {"request": request, "configs": configs, "server_map": server_map},
    )


@admin_router.get("/configs/new", response_class=HTMLResponse)
async def new_config_page(request: Request):
    return templates.TemplateResponse(request, "config_new.html", {"request": request, "edit_mode": False})


@admin_router.get("/configs/edit/{route:path}", response_class=HTMLResponse)
async def edit_config_page(request: Request, route: str):
    cfg = config_manager.get("/" + route)
    if cfg is None:
        raise HTTPException(404, "Config not found")
    return templates.TemplateResponse(
        request, "config_new.html",
        {"request": request, "edit_mode": True, "edit_config": cfg.model_dump(mode="json")},
    )


@admin_router.get("/configs/api/{route:path}", response_class=HTMLResponse)
async def api_detail_page(request: Request, route: str):
    cfg = config_manager.get("/" + route)
    if cfg is None:
        raise HTTPException(404, "Config not found")
    host = request.headers.get("host", "localhost")
    return templates.TemplateResponse(
        request, "config_api.html",
        {
            "request": request,
            "config": cfg,
            "host": host,
            "api_url": f"http://{host}{cfg.route}",
        },
    )


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


@admin_router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    llm = settings_manager.get_llm_config()
    return templates.TemplateResponse(
        request, "settings.html",
        {"request": request, "llm": llm.to_dict()},
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
    workflow_json: str = Form(""),       # base64 编码的 workflow JSON
    timeout: int = Form(120),
    backend_servers: str = Form(""),
    output_node_id: str = Form(""),
    inputs_json: str = Form("[]"),
):
    """创建新的 workflow config"""
    import json

    # 保存 workflow JSON 文件
    if workflow_json and workflow_file:
        try:
            wf_data = json.loads(workflow_json)
            config_manager.save_workflow_json(workflow_file, wf_data)
        except Exception:
            pass

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
        inputs=[WorkflowInput(**inp) for inp in inputs_data],
    )
    config_manager.save(config)
    return {"ok": True, "route": route}


@admin_router.put("/api/configs/{route:path}")
async def update_config(
    route: str,
    name: str = Form(...),
    new_route: str = Form(...),
    description: str = Form(""),
    workflow_file: str = Form(""),
    workflow_json: str = Form(""),
    timeout: int = Form(120),
    backend_servers: str = Form(""),
    output_node_id: str = Form(""),
    inputs_json: str = Form("[]"),
):
    """更新已有 workflow config"""
    import json

    if workflow_json and workflow_file:
        try:
            wf_data = json.loads(workflow_json)
            config_manager.save_workflow_json(workflow_file, wf_data)
        except Exception:
            pass

    inputs_data = json.loads(inputs_json)
    config = WorkflowConfig(
        name=name,
        route=new_route,
        method="POST",
        description=description,
        workflow_file=workflow_file,
        timeout=timeout,
        backend_servers=[s.strip() for s in backend_servers.split(",") if s.strip()],
        output_node_id=output_node_id,
        inputs=[WorkflowInput(**inp) for inp in inputs_data],
    )
    config_manager.update(route, config)
    return {"ok": True, "route": new_route}


@admin_router.post("/api/configs/analyze")
async def analyze_workflow(workflow_file: UploadFile = File(...)):
    """上传 workflow JSON → AI 分析 → 返回推荐 config"""
    import json
    content = await workflow_file.read()
    try:
        workflow = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    suggested = await config_manager.analyze_workflow_json(workflow)
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


@admin_router.post("/api/servers")
async def add_server(
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(8188),
):
    server = server_manager.add_server(name=name, host=host, port=port)
    return {"ok": True, "server": server.model_dump()}


class BatchServerItem(BaseModel):
    host: str
    port: int = 8188
    name: str = ""


@admin_router.post("/api/servers/batch")
async def batch_add_servers(items: list[BatchServerItem]):
    existing = {(s.host, s.port) for s in server_manager.get_all_servers()}
    count = 0
    skipped = 0
    for item in items:
        if (item.host, item.port) in existing:
            skipped += 1
            continue
        name = item.name or f"ComfyUI-{item.port}"
        server_manager.add_server(name=name, host=item.host, port=item.port)
        existing.add((item.host, item.port))
        count += 1
    return {"ok": True, "count": count, "skipped": skipped}


@admin_router.delete("/api/servers/{server_id}")
async def delete_server(server_id: str):
    ok = server_manager.remove_server(server_id)
    if not ok:
        raise HTTPException(404, "Server not found")
    return {"ok": True}


@admin_router.get("/api/stats")
async def get_stats():
    return await stats_manager.get_all_stats()


@admin_router.get("/api/tasks/recent")
async def get_recent_tasks(limit: int = 50):
    return await stats_manager.get_recent_tasks(limit)


# ── 设置 API ────────────────────────────────────────

@admin_router.get("/api/settings/llm")
async def get_llm_settings():
    return settings_manager.get_llm_config().to_dict()


@admin_router.put("/api/settings/llm")
async def update_llm_settings(
    provider: str = Form("openai"),
    api_base: str = Form(""),
    api_key: str = Form(""),
    model: str = Form(""),
    temperature: float = Form(0.1),
    max_tokens: int = Form(2048),
):
    from app.manager.settings_manager import LLMConfig
    config = LLMConfig(
        provider=provider,
        api_base=api_base,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    settings_manager.update_llm_config(config)
    return {"ok": True, "config": config.to_dict()}


@admin_router.post("/api/settings/llm/test")
async def test_llm():
    result = await settings_manager.test_llm_connection()
    return result
