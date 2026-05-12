"""统计模块：调用次数、成功率、耗时 — 基于 SQLite"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from app.config import settings
from app.models.task import TaskStatsResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    workflow_route TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    backend_server TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_stats_route ON task_stats(workflow_route);
CREATE INDEX IF NOT EXISTS idx_stats_created ON task_stats(created_at);
CREATE INDEX IF NOT EXISTS idx_stats_task_id ON task_stats(task_id);
"""


class StatsManager:
    def __init__(self):
        self._db: Optional[aiosqlite.Connection] = None

    async def _get_db(self) -> aiosqlite.Connection:
        if self._db is None:
            db_path = settings.db_full_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(str(db_path))
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(DB_SCHEMA)
            await self._db.commit()
        return self._db

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    # ── 记录 ────────────────────────────────────────

    async def log_start(
        self, task_id: str, route: str, backend: str
    ):
        db = await self._get_db()
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO task_stats (task_id, workflow_route, status, backend_server, created_at) "
            "VALUES (?, ?, 'running', ?, ?)",
            (task_id, route, backend, now),
        )
        await db.commit()

    async def log_complete(
        self, task_id: str, success: bool, error: str = ""
    ):
        db = await self._get_db()
        now = datetime.now(timezone.utc).isoformat()

        row = await db.execute(
            "SELECT created_at FROM task_stats WHERE task_id = ?",
            (task_id,),
        )
        result = await row.fetchone()
        if not result:
            return

        created = datetime.fromisoformat(result["created_at"])
        duration_ms = int(
            (datetime.now(timezone.utc) - created).total_seconds() * 1000
        )

        status = "completed" if success else "failed"
        await db.execute(
            "UPDATE task_stats SET status = ?, completed_at = ?, duration_ms = ?, error = ? "
            "WHERE task_id = ?",
            (status, now, duration_ms, error, task_id),
        )
        await db.commit()

    # ── 查询统计 ────────────────────────────────────

    async def get_route_stats(self, route: str) -> TaskStatsResponse:
        db = await self._get_db()

        row = await db.execute(
            "SELECT "
            "  COUNT(*) as total, "
            "  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success, "
            "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as fail, "
            "  AVG(CASE WHEN status IN ('completed','failed') THEN duration_ms ELSE NULL END) as avg_dur, "
            "  MAX(created_at) as last "
            "FROM task_stats WHERE workflow_route = ?",
            (route,),
        )
        r = await row.fetchone()
        if r is None:
            return TaskStatsResponse(workflow_route=route)

        last_called = (
            datetime.fromisoformat(r["last"]) if r["last"] else None
        )
        return TaskStatsResponse(
            workflow_route=route,
            total_calls=r["total"] or 0,
            success_count=r["success"] or 0,
            fail_count=r["fail"] or 0,
            avg_duration_ms=round(r["avg_dur"] or 0, 1),
            last_called=last_called,
        )

    async def get_all_stats(self) -> list[TaskStatsResponse]:
        db = await self._get_db()
        rows = await db.execute(
            "SELECT workflow_route FROM task_stats GROUP BY workflow_route"
        )
        routes = [r["workflow_route"] async for r in rows]
        results = []
        for route in routes:
            results.append(await self.get_route_stats(route))
        return results

    async def get_recent_tasks(self, limit: int = 50) -> list[dict]:
        db = await self._get_db()
        rows = await db.execute(
            "SELECT * FROM task_stats ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) async for r in rows]

    async def cleanup_old(self, retention_seconds: int = 3600):
        """清理过期记录"""
        db = await self._get_db()
        cutoff = int(datetime.now(timezone.utc).timestamp()) - retention_seconds
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        await db.execute(
            "DELETE FROM task_stats WHERE created_at < ? AND status IN ('completed', 'failed')",
            (cutoff_iso,),
        )
        await db.commit()


# 全局单例
stats_manager = StatsManager()
