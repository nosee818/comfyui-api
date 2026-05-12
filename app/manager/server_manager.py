"""后端服务器管理器：健康检查、选择、状态追踪"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import yaml

from app.config import settings
from app.models.workflow import BackendServer, ServersConfig
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ServerManager:
    """管理所有 ComfyUI 后端服务器"""

    def __init__(self):
        self._servers: dict[str, BackendServer] = {}
        self._status: dict[str, dict] = {}  # server_id → {online, queue_remaining, last_checked}
        self._load_index: dict[str, int] = {}  # round-robin 计数器
        self._lock = asyncio.Lock()

    # ── 加载配置 ────────────────────────────────────

    def load_servers(self) -> list[BackendServer]:
        """从 YAML 加载服务器列表"""
        path = settings.servers_config_path
        if not path.exists():
            logger.warning(f"Servers config not found: {path}")
            return []

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        config = ServersConfig(**data)

        self._servers = {s.id: s for s in config.servers if s.enabled}
        for sid in self._servers:
            self._status.setdefault(sid, {"online": False, "queue_remaining": 0, "last_checked": None})
            self._load_index.setdefault(sid, 0)

        logger.info(f"Loaded {len(self._servers)} backend servers")
        return list(self._servers.values())

    def reload(self):
        return self.load_servers()

    # ── 查询 ────────────────────────────────────────

    def get_server(self, server_id: str) -> BackendServer | None:
        return self._servers.get(server_id)

    def get_all_servers(self) -> list[BackendServer]:
        return list(self._servers.values())

    def get_online_servers(self) -> list[BackendServer]:
        return [s for s in self._servers.values() if self._status.get(s.id, {}).get("online")]

    def get_available(self, server_ids: list[str]) -> BackendServer | None:
        """从指定 ID 列表中选择一个可用的服务器（round-robin）"""
        candidates = [
            s for sid in server_ids
            if (s := self._servers.get(sid)) and self._status.get(sid, {}).get("online")
        ]
        if not candidates:
            return None

        # round-robin
        idx = self._load_index.get(server_ids[0], 0)
        chosen = candidates[idx % len(candidates)]
        self._load_index[chosen.id] = (self._load_index.get(chosen.id, 0) + 1) % 10000
        return chosen

    def get_server_status(self, server_id: str) -> dict:
        return self._status.get(server_id, {})

    def get_all_status(self) -> list[dict]:
        return [
            {
                "server_id": s.id,
                "name": s.name,
                "host": s.host,
                "port": s.port,
                **self._status.get(s.id, {"online": False, "queue_remaining": 0, "last_checked": None}),
            }
            for s in self._servers.values()
        ]

    # ── 健康检查 ────────────────────────────────────

    async def check_all(self) -> dict[str, dict]:
        """对所有后端服务器执行健康检查"""
        from app.core.comfyui_client import ComfyUIClient

        async def check_one(server: BackendServer):
            client = ComfyUIClient(server.base_url, server.ws_url)
            try:
                result = await client.check_health()
                online = result.get("online", False)
                queue_remaining = 0
                if online and "data" in result:
                    queue_remaining = len(result["data"].get("queue_remaining", 0)
                                          if isinstance(result["data"].get("queue_remaining"), list)
                                          else [])
                self._status[server.id] = {
                    "online": online,
                    "queue_remaining": queue_remaining,
                    "last_checked": datetime.now(timezone.utc),
                }
            except Exception as e:
                logger.error(f"Health check error for {server.id}: {e}")
                self._status[server.id] = {
                    "online": False,
                    "queue_remaining": 0,
                    "last_checked": datetime.now(timezone.utc),
                }
            finally:
                await client.close()

        tasks = [check_one(s) for s in self._servers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        return dict(self._status)

    async def health_check_loop(self):
        """后台循环：定时健康检查"""
        while True:
            await asyncio.sleep(settings.health_check_interval)
            try:
                await self.check_all()
            except Exception as e:
                logger.error(f"Health check loop error: {e}")


# 全局单例
server_manager = ServerManager()
