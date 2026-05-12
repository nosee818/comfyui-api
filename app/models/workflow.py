"""Pydantic 模型：Workflow Config"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class InputType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    IMAGE_SEQUENCE = "image_sequence"


class InjectTo(BaseModel):
    node_id: str = ""
    field: str = ""
    type: Optional[str] = None
    nodes: Optional[list[str]] = None


class WorkflowInput(BaseModel):
    name: str
    type: InputType
    required: bool = True
    default: Any = None
    description: str = ""
    min_items: Optional[int] = None
    max_items: Optional[int] = None
    inject_to: InjectTo = Field(default_factory=InjectTo)


class WorkflowConfig(BaseModel):
    name: str
    route: str
    method: str = "POST"
    description: str = ""
    workflow_file: str
    timeout: int = 120
    backend_servers: list[str] = Field(default_factory=list)
    inputs: list[WorkflowInput] = Field(default_factory=list)
    output_node_id: str = ""


class BackendServer(BaseModel):
    id: str
    name: str
    host: str
    port: int = 8188
    enabled: bool = True

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"


class ServersConfig(BaseModel):
    servers: list[BackendServer] = Field(default_factory=list)
