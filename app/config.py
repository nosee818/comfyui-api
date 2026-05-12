"""全局配置模块"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 项目根目录
    base_dir: Path = Path(__file__).resolve().parent.parent

    # 网关服务
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8188

    # 配置文件路径（相对于 base_dir）
    servers_config: str = "configs/servers.yaml"
    workflows_dir: str = "configs/workflows"
    workflows_json_dir: str = "configs/workflows_json"

    # 数据库
    db_path: str = "data/gateway.db"

    # 日志
    log_dir: str = "logs"
    log_level: str = "INFO"

    # 健康检查间隔（秒）
    health_check_interval: int = 30

    # 清理已完成任务的间隔（秒）
    task_cleanup_interval: int = 300
    task_retention_seconds: int = 3600

    @property
    def servers_config_path(self) -> Path:
        return self.base_dir / self.servers_config

    @property
    def workflows_dir_path(self) -> Path:
        return self.base_dir / self.workflows_dir

    @property
    def workflows_json_dir_path(self) -> Path:
        return self.base_dir / self.workflows_json_dir

    @property
    def db_full_path(self) -> Path:
        return self.base_dir / self.db_path

    class Config:
        env_prefix = "CGW_"


settings = Settings()
