"""参数注入器：将用户输入写入 workflow JSON 模板"""

from __future__ import annotations

import copy
import random
from typing import Any

from app.models.workflow import InputType, WorkflowConfig, WorkflowInput


class Injector:
    """将用户参数注入到 ComfyUI workflow JSON 中"""

    def inject(
        self,
        workflow: dict[str, Any],
        config: WorkflowConfig,
        params: dict[str, Any],
        uploaded_images: dict[str, list[str]],
    ) -> dict[str, Any]:
        """
        Args:
            workflow: 原始 workflow JSON（深拷贝后修改）
            config: 对应的 WorkflowConfig
            params: 用户请求中的参数 {name: value}
            uploaded_images: 已上传到 ComfyUI 的图片映射 {input_name: [filename1, ...]}

        Returns:
            注入参数后的 workflow JSON
        """
        workflow = copy.deepcopy(workflow)

        for inp in config.inputs:
            value = params.get(inp.name)

            # 如果用户没传，用默认值
            if value is None:
                if inp.default is not None:
                    value = inp.default
                elif inp.required:
                    raise ValueError(f"缺少必填参数: {inp.name}")
                else:
                    continue

            if inp.type == InputType.STRING:
                self._inject_string(workflow, inp, str(value))

            elif inp.type == InputType.INTEGER:
                self._inject_integer(workflow, inp, value)

            elif inp.type == InputType.FLOAT:
                self._inject_float(workflow, inp, value)

            elif inp.type == InputType.BOOLEAN:
                self._inject_bool(workflow, inp, value)

            elif inp.type == InputType.IMAGE_SEQUENCE:
                image_names = uploaded_images.get(inp.name, [])
                self._inject_image_sequence(workflow, inp, image_names)

        # 额外处理 seed = -1 → 随机
        self._resolve_random_seeds(workflow, config)

        return workflow

    def _resolve_random_seeds(
        self, workflow: dict[str, Any], config: WorkflowConfig
    ):
        """将 seed=-1 替换为随机数"""
        seed_inputs = [i for i in config.inputs if i.name == "seed"]
        if not seed_inputs:
            return

        for seed_inp in seed_inputs:
            node_id = seed_inp.inject_to.node_id
            if node_id and node_id in workflow:
                node = workflow[node_id]
                current_seed = node.get("inputs", {}).get(seed_inp.inject_to.field)
                if current_seed == -1 or current_seed == "-1":
                    node["inputs"][seed_inp.inject_to.field] = random.randint(
                        0, 2**32 - 1
                    )

    # ── 各类型注入 ──────────────────────────────────

    def _inject_string(
        self, workflow: dict, inp: WorkflowInput, value: str
    ):
        workflow[inp.inject_to.node_id]["inputs"][
            inp.inject_to.field
        ] = value

    def _inject_integer(
        self, workflow: dict, inp: WorkflowInput, value: Any
    ):
        workflow[inp.inject_to.node_id]["inputs"][
            inp.inject_to.field
        ] = int(value)

    def _inject_float(
        self, workflow: dict, inp: WorkflowInput, value: Any
    ):
        workflow[inp.inject_to.node_id]["inputs"][
            inp.inject_to.field
        ] = float(value)

    def _inject_bool(
        self, workflow: dict, inp: WorkflowInput, value: Any
    ):
        if isinstance(value, str):
            value = value.lower() in ("true", "1", "yes")
        workflow[inp.inject_to.node_id]["inputs"][
            inp.inject_to.field
        ] = bool(value)

    def _inject_image_sequence(
        self, workflow: dict, inp: WorkflowInput, image_names: list[str]
    ):
        """将 1-N 张图片名注入到 workflow 的 LoadImage 节点序列"""
        nodes = inp.inject_to.nodes or []
        for i, node_id in enumerate(nodes):
            if i < len(image_names):
                workflow[node_id]["inputs"][
                    inp.inject_to.field
                ] = image_names[i]
            # 超出实际图片数量的节点不修改，保持原样
