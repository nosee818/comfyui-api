"""全局设置管理器：LLM 配置"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import httpx
import yaml

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

SETTINGS_FILE = "configs/settings.yaml"


@dataclass
class LLMConfig:
    provider: str = "openai"     # openai | ollama | custom
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_tokens: int = 2048

    def get_api_key(self) -> str:
        return self.api_key or os.environ.get("OPENAI_API_KEY", "")

    def get_base_url(self) -> str:
        """确保 api_base 以 /v1 结尾（OpenAI 兼容格式）"""
        url = self.api_base.rstrip("/")
        if self.provider == "ollama" and not url.endswith("/v1"):
            # Ollama 原生端口 11434，需要 /v1 前缀
            return url
        return url

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "api_base": self.api_base,
            "api_key": self.api_key,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LLMConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SettingsManager:
    def __init__(self):
        self._llm_config: LLMConfig = LLMConfig()

    @property
    def file_path(self):
        return settings.base_dir / SETTINGS_FILE

    def load(self) -> LLMConfig:
        path = self.file_path
        if not path.exists():
            self._llm_config = LLMConfig()
            self.save()
            return self._llm_config

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        llm_data = data.get("llm", {})
        self._llm_config = LLMConfig.from_dict(llm_data)
        logger.info(f"Loaded LLM config: provider={self._llm_config.provider}, model={self._llm_config.model}")
        return self._llm_config

    def save(self):
        path = self.file_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump({"llm": self._llm_config.to_dict()}, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def get_llm_config(self) -> LLMConfig:
        return self._llm_config

    def update_llm_config(self, config: LLMConfig):
        self._llm_config = config
        self.save()
        logger.info(f"Updated LLM config: provider={config.provider}, model={config.model}")

    async def test_llm_connection(self) -> dict:
        """测试 LLM 连接，返回 {ok, message}"""
        llm = self._llm_config
        api_key = llm.get_api_key()

        if llm.provider == "openai" and not api_key:
            return {"ok": False, "message": "API Key 未配置"}

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = {
            "model": llm.model,
            "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 10,
            "temperature": 0,
        }

        url = f"{llm.get_base_url()}/chat/completions"
        if not url.startswith("http"):
            url = f"https://{url}" if llm.provider != "ollama" else f"http://{url}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return {"ok": True, "message": f"连接成功，模型响应：{content}"}
                else:
                    return {"ok": False, "message": f"API 返回 {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}


# 全局单例
settings_manager = SettingsManager()
