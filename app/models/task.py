"""Pydantic 模型：Task 任务状态"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCreateRequest(BaseModel):
    """由 gateway 内部使用，非对外 API"""
    workflow_route: str
    params: dict[str, Any]


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    message: str = "Task submitted"
    created_at: datetime = Field(default_factory=datetime.now)


class TaskStatusResponse(BaseModel):
    task_id: str
    workflow_route: str
    status: TaskStatus
    progress: int = 0
    progress_max: int = 0
    message: str = ""
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    backend_server: str = ""


class TaskStatsResponse(BaseModel):
    workflow_route: str
    total_calls: int = 0
    success_count: int = 0
    fail_count: int = 0
    avg_duration_ms: float = 0.0
    last_called: Optional[datetime] = None


class ServerStatusResponse(BaseModel):
    server_id: str
    name: str
    host: str
    port: int
    online: bool
    queue_remaining: int = 0
    last_checked: Optional[datetime] = None
