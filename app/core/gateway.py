"""API 网关核心：接收请求 → 加载 config → 注入参数 → 转发 → 返回结果"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import UploadFile

from app.core.comfyui_client import ComfyUIClient
from app.core.injector import Injector
from app.manager.config_manager import config_manager
from app.manager.server_manager import server_manager
from app.manager.stats import stats_manager
from app.models.task import TaskResponse, TaskStatus, TaskStatusResponse
from app.models.workflow import InputType, WorkflowConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Gateway:
    """API 网关：处理所有 workflow 执行请求"""

    def __init__(self):
        self._injector = Injector()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        route: str,
        form_params: dict[str, Any],
        uploaded_files: list[UploadFile],
    ) -> TaskResponse:
        """
        执行一个 workflow。

        Args:
            route: API 路由 (如 /z-image)
            form_params: 表单参数 {text: "...", width: "1080", ...}
            uploaded_files: multipart 上传的文件列表

        Returns:
            TaskResponse with task_id
        """
        # 1. 加载 config
        config = config_manager.get(route)
        if config is None:
            raise ValueError(f"Unknown workflow route: {route}")

        # 2. 选择后端服务器
        server = server_manager.get_available(config.backend_servers)
        if server is None:
            raise RuntimeError(
                f"No available backend server for route: {route}"
            )

        # 3. 上传图片到 ComfyUI
        uploaded_images: dict[str, list[str]] = {}
        image_fields = [
            inp for inp in config.inputs if inp.type == InputType.IMAGE_SEQUENCE
        ]
        if image_fields and uploaded_files:
            client = ComfyUIClient(server.base_url, server.ws_url)
            try:
                for img_inp in image_fields:
                    max_items = img_inp.max_items or 3
                    # 从 uploaded_files 中匹配：假设前端用 input_name + "_0", "_1", "_2" 做 field name
                    # 或者直接按顺序分配
                    image_names = []
                    for i, uf in enumerate(uploaded_files[:max_items]):
                        content = await uf.read()
                        filename = uf.filename or f"input_{uuid.uuid4().hex[:8]}.png"
                        name = await client.upload_image(content, filename)
                        image_names.append(name)
                        await uf.seek(0)  # 重置以便后续可能使用
                    uploaded_images[img_inp.name] = image_names
            finally:
                await client.close()

        # 4. 加载 workflow JSON
        workflow_json = config_manager.get_workflow_json(config.workflow_file)

        # 5. 注入参数
        workflow = self._injector.inject(
            workflow_json, config, form_params, uploaded_images
        )

        # 6. 提交 prompt
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        self._tasks[task_id] = {
            "task_id": task_id,
            "workflow_route": route,
            "status": TaskStatus.PENDING,
            "progress": 0,
            "progress_max": 0,
            "message": "Queued",
            "created_at": now,
            "completed_at": None,
            "error": None,
            "outputs": [],
            "backend_server": f"{server.host}:{server.port}",
        }

        # 记录统计
        await stats_manager.log_start(
            task_id, route, f"{server.host}:{server.port}"
        )

        # 7. 后台执行
        asyncio.create_task(
            self._execute_background(task_id, config, server, workflow)
        )

        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            backend_server=f"{server.host}:{server.port}",
        )

    async def _execute_background(
        self,
        task_id: str,
        config: WorkflowConfig,
        server: Any,  # BackendServer
        workflow: dict[str, Any],
    ):
        """后台执行：提交 prompt → WebSocket 监听 → 收集结果"""
        client = ComfyUIClient(server.base_url, server.ws_url, config.timeout)
        try:
            # 更新状态为 running
            self._tasks[task_id]["status"] = TaskStatus.RUNNING
            self._tasks[task_id]["message"] = "Submitting to ComfyUI..."

            # 提交 prompt
            result = await client.submit_prompt(workflow)
            prompt_id = result["prompt_id"]
            self._tasks[task_id]["message"] = f"Running (prompt_id: {prompt_id})"

            # WebSocket 监听
            ws = await client.connect_ws()
            try:
                ws_result = await client.listen_for_result(prompt_id, ws)
            finally:
                await ws.close()

            if ws_result["success"]:
                # 获取输出文件
                outputs = ws_result.get("outputs", {})
                image_outputs = self._extract_image_outputs(
                    outputs, config.output_node_id, server
                )
                self._tasks[task_id].update({
                    "status": TaskStatus.COMPLETED,
                    "progress": 100,
                    "progress_max": 100,
                    "message": "Completed",
                    "completed_at": datetime.now(timezone.utc),
                    "outputs": image_outputs,
                })
                await stats_manager.log_complete(task_id, success=True)

            else:
                error_msg = ws_result.get("error", "Unknown error")
                self._tasks[task_id].update({
                    "status": TaskStatus.FAILED,
                    "message": "Failed",
                    "completed_at": datetime.now(timezone.utc),
                    "error": error_msg,
                })
                await stats_manager.log_complete(
                    task_id, success=False, error=error_msg
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Task {task_id} failed: {error_msg}")
            self._tasks[task_id].update({
                "status": TaskStatus.FAILED,
                "message": "Failed",
                "completed_at": datetime.now(timezone.utc),
                "error": error_msg,
            })
            await stats_manager.log_complete(
                task_id, success=False, error=error_msg
            )
        finally:
            await client.close()

    def _extract_image_outputs(
        self, outputs: dict, target_node_id: str, server: Any
    ) -> list[dict]:
        """从 ComfyUI 输出中提取图片信息"""
        result = []
        node_output = outputs.get(target_node_id, {})
        images = node_output.get("images", [])
        for img in images:
            result.append({
                "filename": img.get("filename", ""),
                "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output"),
                "url": (
                    f"{server.base_url}/view?"
                    f"filename={img.get('filename', '')}&"
                    f"subfolder={img.get('subfolder', '')}&"
                    f"type={img.get('type', 'output')}"
                ),
            })
        return result

    # ── 任务查询 ────────────────────────────────────

    def get_task(self, task_id: str) -> TaskStatusResponse | None:
        data = self._tasks.get(task_id)
        if data is None:
            return None
        return TaskStatusResponse(**data)

    def cancel_task(self, task_id: str) -> bool:
        """取消任务（尽力而为）"""
        task = self._tasks.get(task_id)
        if task and task["status"] in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task["status"] = TaskStatus.CANCELLED
            task["message"] = "Cancelled"
            task["completed_at"] = datetime.now(timezone.utc)
            return True
        return False

    async def cleanup_old_tasks(self):
        """定期清理内存中的旧任务"""
        from app.config import settings

        while True:
            await asyncio.sleep(settings.task_cleanup_interval)
            cutoff = datetime.now(timezone.utc).timestamp() - settings.task_retention_seconds
            to_remove = []
            for tid, task in self._tasks.items():
                if task["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    created = task.get("created_at")
                    if created and created.timestamp() < cutoff:
                        to_remove.append(tid)
            for tid in to_remove:
                del self._tasks[tid]
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} old tasks")


# 全局单例
gateway = Gateway()
