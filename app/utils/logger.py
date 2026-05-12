"""日志配置"""

import logging
import sys
from pathlib import Path

from app.config import settings


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging():
    """初始化全局日志配置"""
    log_dir = Path(settings.base_dir) / settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)

    # 文件
    file_handler = logging.FileHandler(
        log_dir / "gateway.log", encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # 降低第三方库日志级别
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
