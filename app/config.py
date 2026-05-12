"""全局配置模块"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(f"CGW_{key}", default)


@dataclass
class Settings:
    # 项目根目录
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    # 网关服务
    gateway_host: str = field(default_factory=lambda: _env("GATEWAY_HOST", "0.0.0.0"))
    gateway_port: int = field(default_factory=lambda: int(_env("GATEWAY_PORT", "8288")))

    # 配置文件路径（相对于 base_dir）
    servers_config: str = field(default_factory=lambda: _env("SERVERS_CONFIG", "configs/servers.yaml"))
    workflows_dir: str = field(default_factory=lambda: _env("WORKFLOWS_DIR", "configs/workflows"))
    workflows_json_dir: str = field(default_factory=lambda: _env("WORKFLOWS_JSON_DIR", "configs/workflows_json"))

    # 数据库
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "data/gateway.db"))

    # 日志
    log_dir: str = field(default_factory=lambda: _env("LOG_DIR", "logs"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # 健康检查间隔（秒）
    health_check_interval: int = field(default_factory=lambda: int(_env("HEALTH_CHECK_INTERVAL", "30")))

    # 清理已完成任务的间隔（秒）
    task_cleanup_interval: int = field(default_factory=lambda: int(_env("TASK_CLEANUP_INTERVAL", "300")))
    task_retention_seconds: int = field(default_factory=lambda: int(_env("TASK_RETENTION_SECONDS", "3600")))

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


settings = Settings()
