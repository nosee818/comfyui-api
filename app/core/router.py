"""动态路由注册引擎

启动时扫描 configs/workflows/*.yaml，为每个 workflow 自动注册 FastAPI 路由。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.gateway import gateway
from app.manager.config_manager import config_manager
from app.models.workflow import InputType, WorkflowConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 动态路由的 router，挂载到 / 下
dynamic_router = APIRouter()


def register_all_workflows(router: APIRouter | None = None):
    """扫描所有 workflow config 并注册路由 + OpenAPI 文档。

    每个 config 创建一个 endpoint:
      POST /{route}  →  接收 multipart/form-data  →  返回 TaskResponse
    """
    if router is None:
        router = dynamic_router

    configs = config_manager.list_all()
    registered = 0

    for config in configs:
        route_path = config.route
        if not route_path.startswith("/"):
            route_path = f"/{route_path}"

        # 为每个 route 创建一个闭包捕获 config
        def make_endpoint(cfg: WorkflowConfig):
            async def endpoint(request: Request):
                form = await request.form()
                form_params: dict[str, Any] = {}
                uploaded_files: list[Any] = []

                for key, value in form.items():
                    if hasattr(value, 'filename'):
                        uploaded_files.append(value)
                    else:
                        form_params[key] = value

                # 类型转换
                for inp in cfg.inputs:
                    if inp.name in form_params:
                        if inp.type == InputType.INTEGER:
                            form_params[inp.name] = int(form_params[inp.name])
                        elif inp.type == InputType.FLOAT:
                            form_params[inp.name] = float(form_params[inp.name])
                        elif inp.type == InputType.BOOLEAN:
                            v = str(form_params[inp.name]).lower()
                            form_params[inp.name] = v in ("true", "1", "yes")

                try:
                    result = await gateway.execute(
                        cfg.route, form_params, uploaded_files
                    )
                    return JSONResponse(
                        content=result.model_dump(mode="json"),
                        status_code=200,
                    )
                except ValueError as e:
                    return JSONResponse(
                        content={"error": str(e)}, status_code=400
                    )
                except RuntimeError as e:
                    return JSONResponse(
                        content={"error": str(e)}, status_code=503
                    )

            # 动态设置函数的元信息
            endpoint.__name__ = f"workflow_{cfg.route.lstrip('/').replace('/', '_')}"
            return endpoint

        # 注册路由
        router.add_api_route(
            path=route_path,
            endpoint=make_endpoint(config),
            methods=[config.method],
            summary=config.name,
            description=_build_openapi_desc(config),
            tags=["workflows"],
        )
        registered += 1

    # 注入 OpenAPI 参数文档
    _patch_openapi_params(router)

    logger.info(f"Registered {registered} workflow routes")
    return registered


def _build_openapi_desc(cfg: WorkflowConfig) -> str:
    """为 workflow 构建 OpenAPI 描述，包含参数表"""
    if not cfg.inputs:
        return cfg.description or ""

    lines = [cfg.description or "", "", "**参数:**", ""]
    for inp in cfg.inputs:
        req = "必填" if inp.required else "可选"
        default = f", 默认: {inp.default}" if inp.default is not None and inp.default != '' else ""
        img_note = f" (上传文件)" if inp.type == InputType.IMAGE_SEQUENCE else ""
        lines.append(f"- **{inp.name}** ({inp.type.value}, {req}{default}){img_note}: {inp.description}")
    lines.append("")
    lines.append("Content-Type: multipart/form-data")
    return "\n".join(lines)


def _patch_openapi_params(router: APIRouter):
    """为动态注册的 workflow 路由注入 OpenAPI requestBody schema"""
    for route in router.routes:
        cfg = config_manager.get(route.path)
        if not cfg or not cfg.inputs:
            continue

        if not hasattr(route, 'body_field') or route.body_field is None:
            continue

        # 构建 form-data schema
        properties = {}
        required = []
        for inp in cfg.inputs:
            schema_type = "string"
            if inp.type == InputType.INTEGER:
                schema_type = "integer"
            elif inp.type == InputType.FLOAT:
                schema_type = "number"
            elif inp.type == InputType.BOOLEAN:
                schema_type = "boolean"
            elif inp.type == InputType.IMAGE_SEQUENCE:
                schema_type = "string"
                properties[inp.name] = {
                    "type": schema_type,
                    "format": "binary",
                    "description": f"{inp.description} (文件上传)",
                }
                if inp.required:
                    required.append(inp.name)
                continue

            props = {
                "type": schema_type,
                "description": inp.description,
            }
            if inp.default is not None and inp.default != '':
                props["default"] = inp.default
            properties[inp.name] = props
            if inp.required:
                required.append(inp.name)

        # 注入到 OpenAPI schema
        try:
            schema = route.body_field.type_.schema()
            if hasattr(schema, 'get'):
                media_type = schema.get("content", {}).get("multipart/form-data", {})
                media_type["schema"] = {
                    "type": "object",
                    "properties": properties,
                    "required": required if required else None,
                }
        except Exception:
            pass
