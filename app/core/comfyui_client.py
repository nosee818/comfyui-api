"""ComfyUI HTTP/WS 客户端封装"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

import httpx
import websockets
from websockets.asyncio.client import ClientConnection as WSConnection

from app.utils.logger import get_logger

logger = get_logger(__name__)


class ComfyUIClient:
    """封装对单个 ComfyUI 后端服务器的所有操作"""

    def __init__(self, base_url: str, ws_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = timeout
        self._client_id = str(uuid.uuid4())
        self._http: Optional[httpx.AsyncClient] = None
        self._ws: Optional[WSConnection] = None

    @property
    def client_id(self) -> str:
        return self._client_id

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,           # 连接超时 10 秒，快速判定不可达
                    read=self.timeout,      # 读取超时跟随 config（生图可能很久）
                    write=30.0,
                    pool=10.0,
                ),
                limits=httpx.Limits(max_keepalive_connections=5),
            )
        return self._http

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    # ── 服务器状态 ──────────────────────────────────

    async def check_health(self) -> dict[str, Any]:
        """检查服务器是否在线 + 队列状态"""
        http = await self._get_http()
        try:
            resp = await http.get(f"{self.base_url}/system_stats", timeout=5.0)
            resp.raise_for_status()
            return {"online": True, "data": resp.json()}
        except Exception as e:
            logger.warning(f"Health check failed for {self.base_url}: {e}")
            return {"online": False, "error": str(e)}

    async def get_queue(self) -> dict[str, Any]:
        http = await self._get_http()
        resp = await http.get(f"{self.base_url}/queue")
        resp.raise_for_status()
        return resp.json()

    # ── 图片上传 ────────────────────────────────────

    async def upload_image(
        self, file_content: bytes, filename: str, overwrite: bool = True
    ) -> str:
        """上传图片到 ComfyUI，返回服务端文件名"""
        http = await self._get_http()
        files = {"image": (filename, file_content, "image/png")}
        data = {"overwrite": str(overwrite).lower()}
        resp = await http.post(
            f"{self.base_url}/upload/image", files=files, data=data
        )
        resp.raise_for_status()
        result = resp.json()
        # ComfyUI 返回 {"name": "filename.png", "subfolder": "", "type": "input"}
        return result.get("name", filename)

    # ── Prompt 提交 ─────────────────────────────────

    async def submit_prompt(
        self, workflow: dict[str, Any]
    ) -> dict[str, Any]:
        """提交 workflow，返回 {prompt_id, node_errors}"""
        http = await self._get_http()
        payload = {
            "prompt": workflow,
            "client_id": self._client_id,
        }
        resp = await http.post(
            f"{self.base_url}/prompt",
            json=payload,
            timeout=httpx.Timeout(connect=10.0, read=30.0),
        )
        resp.raise_for_status()
        result = resp.json()
        if "node_errors" in result and result["node_errors"]:
            error_details = json.dumps(result["node_errors"])
            logger.error(f"Node errors in prompt: {error_details}")
            raise ValueError(f"Workflow node errors: {error_details}")
        return result

    # ── WebSocket 进度监听 ──────────────────────────

    async def connect_ws(self) -> WSConnection:
        url = f"{self.ws_url}?clientId={self._client_id}"
        self._ws = await websockets.connect(url, max_size=2**26)
        return self._ws

    async def listen_for_result(
        self, prompt_id: str, ws: WSConnection
    ) -> dict[str, Any]:
        """
        监听 WebSocket 直到获取执行结果。
        返回 {"success": bool, "outputs": {...}, "error": str|None}
        """
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "execution_error":
                    data = msg.get("data", {})
                    return {
                        "success": False,
                        "outputs": {},
                        "error": data.get("exception_message", "Unknown error"),
                        "traceback": data.get("traceback", ""),
                    }

                if msg_type == "executed":
                    data = msg.get("data", {})
                    if data.get("prompt_id") == prompt_id:
                        return {
                            "success": True,
                            "outputs": data.get("output", {}),
                            "error": None,
                        }

                if msg_type == "executing":
                    data = msg.get("data", {})
                    if data.get("prompt_id") == prompt_id and data.get("node") is None:
                        # 执行完成但可能没有 executed 消息（老版本）
                        # 稍等再收一条
                        continue

        except asyncio.TimeoutError:
            return {
                "success": False,
                "outputs": {},
                "error": f"Execution timeout after {self.timeout}s",
            }

    # ── 获取历史输出 ────────────────────────────────

    async def get_history(self, prompt_id: str) -> dict[str, Any]:
        """通过 HTTP 获取执行历史和输出文件列表"""
        http = await self._get_http()
        resp = await http.get(f"{self.base_url}/history/{prompt_id}")
        resp.raise_for_status()
        return resp.json()

    # ── 中断执行 ────────────────────────────────────

    async def interrupt(self):
        http = await self._get_http()
        payload = {"client_id": self._client_id}
        await http.post(f"{self.base_url}/interrupt", json=payload)

    async def cancel_prompt(self, prompt_id: str):
        http = await self._get_http()
        await http.post(f"{self.base_url}/queue", json={"delete": [prompt_id]})
