"""Config 文件管理器：CRUD、热加载、YAML 解析"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings
from app.models.workflow import WorkflowConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigManager:
    """管理所有 workflow config YAML 文件"""

    def __init__(self):
        self._configs: dict[str, WorkflowConfig] = {}

    # ── 加载 ────────────────────────────────────────

    def load_all(self) -> dict[str, WorkflowConfig]:
        """扫描 workflows 目录，加载所有 YAML"""
        self._configs.clear()
        wf_dir = settings.workflows_dir_path
        if not wf_dir.exists():
            logger.warning(f"Workflows dir not found: {wf_dir}")
            return {}

        for yaml_file in sorted(wf_dir.glob("*.yaml")):
            try:
                config = self._load_one(yaml_file)
                self._configs[config.route] = config
                logger.info(f"Loaded workflow: {config.route} -> {config.name}")
            except Exception as e:
                logger.error(f"Failed to load {yaml_file}: {e}")

        logger.info(f"Loaded {len(self._configs)} workflow configs")
        return dict(self._configs)

    def _load_one(self, path: Path) -> WorkflowConfig:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return WorkflowConfig(**data)

    def reload(self):
        return self.load_all()

    # ── 查询 ────────────────────────────────────────

    def get(self, route: str) -> Optional[WorkflowConfig]:
        return self._configs.get(route)

    def list_all(self) -> list[WorkflowConfig]:
        return list(self._configs.values())

    def get_routes(self) -> list[str]:
        return list(self._configs.keys())

    # ── 工作流 JSON ─────────────────────────────────

    def get_workflow_json(self, workflow_file: str) -> dict:
        """加载 ComfyUI workflow JSON 模板"""
        json_path = settings.workflows_json_dir_path / workflow_file
        if not json_path.exists():
            raise FileNotFoundError(f"Workflow JSON not found: {json_path}")

        import json
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── CRUD ────────────────────────────────────────

    def save(self, config: WorkflowConfig):
        """保存 config 到 YAML 文件（用于管理面板）"""
        wf_dir = settings.workflows_dir_path
        wf_dir.mkdir(parents=True, exist_ok=True)

        # 用 route 去掉前导 / 作为文件名
        safe_name = config.route.lstrip("/").replace("/", "-") or "unnamed"
        file_path = wf_dir / f"{safe_name}.yaml"

        # 转为 dict 后写入
        data = config.model_dump(exclude_none=True, exclude_defaults=False)
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        self._configs[config.route] = config
        logger.info(f"Saved workflow config: {config.route}")

    def delete(self, route: str) -> bool:
        config = self._configs.pop(route, None)
        if config is None:
            return False

        safe_name = route.lstrip("/").replace("/", "-")
        file_path = settings.workflows_dir_path / f"{safe_name}.yaml"
        if file_path.exists():
            file_path.unlink()

        logger.info(f"Deleted workflow config: {route}")
        return True

    # ── AI 审核相关 ─────────────────────────────────

    def analyze_workflow_json(self, workflow: dict) -> WorkflowConfig:
        """
        分析 ComfyUI workflow JSON，自动识别可配置参数，
        生成推荐的 WorkflowConfig，供管理面板 AI 审核使用。
        """
        inputs = []
        output_node_id = ""

        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            node_inputs = node_data.get("inputs", {})

            if class_type == "CLIPTextEncode":
                text_val = node_inputs.get("text", "")
                if text_val and not text_val.startswith("{{"):
                    inputs.append({
                        "name": f"text_{node_id}",
                        "type": "string",
                        "required": False,
                        "description": f"CLIPTextEncode 节点 {node_id} 的文本输入",
                        "inject_to": {"node_id": node_id, "field": "text"},
                    })

            elif class_type == "EmptyLatentImage":
                for field in ["width", "height", "batch_size"]:
                    if field in node_inputs:
                        inputs.append({
                            "name": field if field != "batch_size" else "batch_size",
                            "type": "integer",
                            "required": False,
                            "default": node_inputs[field],
                            "description": f"EmptyLatentImage 节点 {node_id} 的 {field}",
                            "inject_to": {"node_id": node_id, "field": field},
                        })

            elif class_type == "KSampler" or class_type == "KSamplerAdvanced":
                for field in ["seed", "steps", "cfg"]:
                    if field in node_inputs:
                        val = node_inputs[field]
                        default = -1 if field == "seed" else val
                        inputs.append({
                            "name": field,
                            "type": "integer",
                            "required": False,
                            "default": default,
                            "description": f"KSampler 节点 {node_id} 的 {field}",
                            "inject_to": {"node_id": node_id, "field": field},
                        })

            elif class_type == "LoadImage":
                image_val = node_inputs.get("image", "")
                if image_val and image_val.startswith("{{"):
                    # 已经是模板占位符
                    pass

            elif class_type in ("SaveImage", "VHS_VideoCombine", "SaveImageWebsocket"):
                if not output_node_id:
                    output_node_id = node_id

        # 合并重复的 seed/steps/cfg
        seen = set()
        merged = []
        for inp in inputs:
            key = f"{inp['name']}_{inp['inject_to']['field']}"
            if key not in seen:
                seen.add(key)
                merged.append(inp)

        return WorkflowConfig(
            name="New Workflow",
            route="/new-workflow",
            method="POST",
            description="Auto-analyzed workflow",
            workflow_file="",
            timeout=120,
            backend_servers=[],
            inputs=merged,
            output_node_id=output_node_id,
        )


# 全局单例
config_manager = ConfigManager()
