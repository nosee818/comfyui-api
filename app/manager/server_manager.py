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
        self._global_rr: int = 0              # 全局轮询计数器
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
        """从指定 ID 列表中选择一个可用的服务器（全局 round-robin）"""
        candidates = [
            s for sid in server_ids
            if (s := self._servers.get(sid)) and self._status.get(sid, {}).get("online")
        ]
        if not candidates:
            return None

        # 全局轮询：所有 API 共享一个计数器，确保负载均匀分布
        idx = self._global_rr % len(candidates)
        self._global_rr = (self._global_rr + 1) % 100000
        chosen = candidates[idx]
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

    # ── CRUD ────────────────────────────────────────

    def add_server(self, name: str, host: str, port: int) -> BackendServer:
        """添加后端服务器，自动生成 ID"""
        import uuid
        sid = f"server-{uuid.uuid4().hex[:6]}"
        server = BackendServer(id=sid, name=name, host=host, port=port, enabled=True)
        self._servers[sid] = server
        self._status[sid] = {"online": False, "queue_remaining": 0, "last_checked": None}
        self._load_index[sid] = 0
        self._save_to_yaml()
        logger.info(f"Added server: {name} ({host}:{port})")
        return server

    def remove_server(self, sid: str) -> bool:
        server = self._servers.pop(sid, None)
        if server is None:
            return False
        self._status.pop(sid, None)
        self._load_index.pop(sid, None)
        self._save_to_yaml()
        logger.info(f"Removed server: {server.name}")
        return True

    def _save_to_yaml(self):
        """保存服务器列表到 YAML"""
        path = settings.servers_config_path
        data = {
            "servers": [
                {"id": s.id, "name": s.name, "host": s.host, "port": s.port, "enabled": s.enabled}
                for s in self._servers.values()
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

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
