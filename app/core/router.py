"""动态路由注册引擎

启动时扫描 configs/workflows/*.yaml，为每个 workflow 自动注册 FastAPI 路由。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.gateway import gateway
from app.manager.config_manager import config_manager
from app.models.workflow import InputType, WorkflowConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 动态路由的 router，挂载到 / 下
dynamic_router = APIRouter()


def register_all_workflows(router: APIRouter | None = None):
    """扫描所有 workflow config 并注册路由。

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
            async def endpoint(
                request: Request,
                # 动态参数：从 config.inputs 读取
            ):
                # 解析 multipart/form-data
                form = await request.form()
                form_params: dict[str, Any] = {}
                uploaded_files: list[UploadFile] = []

                for key, value in form.items():
                    if isinstance(value, UploadFile):
                        uploaded_files.append(value)
                    else:
                        form_params[key] = value

                # 类型转换：integer/float 从字符串转
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

            # 动态设置函数的元信息，用于 OpenAPI docs
            endpoint.__name__ = f"workflow_{cfg.route.lstrip('/').replace('/', '_')}"

            return endpoint

        # 注册路由
        router.add_api_route(
            path=route_path,
            endpoint=make_endpoint(config),
            methods=[config.method],
            summary=config.name,
            description=config.description,
            tags=["workflows"],
        )
        registered += 1

    logger.info(f"Registered {registered} workflow routes")
    return registered
