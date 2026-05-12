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
        data = config.model_dump(mode="json", exclude_none=True)
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

    async def analyze_workflow_json(self, workflow: dict) -> WorkflowConfig:
        """
        使用 LLM 分析 ComfyUI workflow JSON，自动识别可配置参数。
        如果 LLM 未配置或失败，回退到规则匹配。
        """
        from app.manager.settings_manager import settings_manager
        llm = settings_manager.get_llm_config()

        # 尝试 LLM 分析
        try:
            result = await self._analyze_with_llm(workflow, llm)
            if result is not None:
                return result
        except Exception as e:
            logger.warning(f"LLM analysis failed, fallback to rule-based: {e}")

        # 回退到规则匹配
        return self._analyze_rule_based(workflow)

    async def _analyze_with_llm(self, workflow: dict, llm) -> WorkflowConfig | None:
        """使用 LLM 分析 workflow JSON"""
        import json
        import httpx
        import os

        api_key = llm.get_api_key()
        if llm.provider in ("openai", "custom") and not api_key:
            logger.info("LLM not configured, skipping")
            return None

        system_prompt = (
            "你是一个 ComfyUI workflow 分析助手。"
            "分析给定的 workflow JSON，识别所有可以暴露给 API 用户的参数。"
            "对于每个参数，判断其名称(name)、类型(type: string/integer/float/boolean)、"
            "是否必填(required)、默认值(default)、描述(description)、"
            "以及注入目标(inject_to: node_id 和 field)。"
            "参数类型规则："
            "- CLIPTextEncode 节点的 text 字段 → type: string"
            "- EmptyLatentImage 节点的 width/height → type: integer"
            "- KSampler 节点的 seed/steps/cfg → type: integer"
            "- LoadImage 节点的 image 字段 → type: image_sequence (如果需要多图)"
            "- CheckpointLoaderSimple 节点的 ckpt_name → type: string"
            "找到 output_node_id：通常是 SaveImage、VHS_VideoCombine 等节点的 ID。"
            "请只返回 JSON，格式如下："
            '{"inputs": [...], "output_node_id": "9"}'
        )

        workflow_str = json.dumps(workflow, indent=2, ensure_ascii=False)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = {
            "model": llm.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"分析以下 ComfyUI workflow JSON：\n```json\n{workflow_str}\n```"},
            ],
            "temperature": llm.temperature,
            "max_tokens": llm.max_tokens,
            "response_format": {"type": "json_object"},
        }

        base_url = llm.get_base_url()
        url = f"{base_url}/chat/completions"
        if not url.startswith("http"):
            url = f"https://{url}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

        # 解析 LLM 响应
        parsed = json.loads(content)
        llm_inputs = parsed.get("inputs", [])
        llm_output = parsed.get("output_node_id", "")

        # 将 LLM 返回转为 WorkflowInput
        from app.models.workflow import WorkflowInput, InputType, InjectTo
        inputs = []
        for inp in llm_inputs:
            try:
                itype = InputType(inp.get("type", "string"))
            except ValueError:
                itype = InputType.STRING

            inject_data = inp.get("inject_to", {})
            inputs.append(WorkflowInput(
                name=inp.get("name", ""),
                type=itype,
                required=inp.get("required", True),
                default=inp.get("default"),
                description=inp.get("description", ""),
                inject_to=InjectTo(
                    node_id=str(inject_data.get("node_id", "")),
                    field=str(inject_data.get("field", "")),
                    nodes=inject_data.get("nodes"),
                    type=inject_data.get("type"),
                ),
            ))

        return WorkflowConfig(
            name="New Workflow",
            route="/new-workflow",
            description="LLM auto-analyzed workflow",
            workflow_file="",
            timeout=120,
            backend_servers=[],
            inputs=inputs,
            output_node_id=str(llm_output),
        )

    def _analyze_rule_based(self, workflow: dict) -> WorkflowConfig:
        """规则匹配分析：回退方案"""
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

            elif class_type in ("KSampler", "KSamplerAdvanced"):
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
                pass  # 由 LLM 处理更合适

            elif class_type in ("SaveImage", "VHS_VideoCombine", "SaveImageWebsocket"):
                if not output_node_id:
                    output_node_id = node_id

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
            description="Rule-based analyzed workflow",
            workflow_file="",
            timeout=120,
            backend_servers=[],
            inputs=merged,
            output_node_id=output_node_id,
        )


# 全局单例
config_manager = ConfigManager()
