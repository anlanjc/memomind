"""LLM 访问层：一个最小 OpenAI 兼容客户端 + 确定性 Mock。

- ``OpenAICompatibleClient``：httpx 直连 ``/chat/completions``（DashScope
  兼容模式、OpenAI、vLLM、Ollama 的 openai 兼容端点都可用）。
  环境变量：MEMOMIND_LLM_BASE_URL / MEMOMIND_LLM_API_KEY / MEMOMIND_LLM_MODEL。
  缺 API key 时抛 :class:`MissingLLMConfigError`，信息里写清怎么配。
- ``MockResponder``：chat 主循环用的确定性应答器（评测/测试/离线演示）。

项目刻意不依赖 openai SDK / langchain，只用 httpx —— 依赖面小、可 mock。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx

__all__ = [
    "MissingLLMConfigError",
    "LLMConfig",
    "OpenAICompatibleClient",
    "MockResponder",
]

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"


class MissingLLMConfigError(RuntimeError):
    """缺少 LLM 配置（通常是没设 MEMOMIND_LLM_API_KEY）。"""


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls, base_url=None, api_key=None, model=None) -> "LLMConfig":
        base_url = base_url or os.environ.get("MEMOMIND_LLM_BASE_URL", DEFAULT_BASE_URL)
        api_key = api_key or os.environ.get("MEMOMIND_LLM_API_KEY")
        model = model or os.environ.get("MEMOMIND_LLM_MODEL", DEFAULT_MODEL)
        if not api_key:
            raise MissingLLMConfigError(
                "缺少 LLM API key：请设置环境变量 MEMOMIND_LLM_API_KEY"
                "（可选 MEMOMIND_LLM_BASE_URL，默认 " + DEFAULT_BASE_URL +
                "；MEMOMIND_LLM_MODEL，默认 " + DEFAULT_MODEL + "）。"
                "离线评测请使用 RuleExtractor + MockResponder，无需任何 key。"
            )
        return cls(base_url=base_url.rstrip("/"), api_key=api_key, model=model)


class OpenAICompatibleClient:
    """最小 OpenAI 兼容 chat 客户端（httpx）。

    ``transport`` 参数用于注入 httpx.MockTransport 做离线测试。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        cfg = LLMConfig.from_env(base_url=base_url, api_key=api_key, model=model)
        self.base_url = cfg.base_url
        self.model = cfg.model
        self._headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(
            headers=self._headers, timeout=timeout, transport=transport
        )

    def chat(self, system: str, user: str, temperature: float = 0.1) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        resp = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        self._client.close()


class MockResponder:
    """确定性应答器：不联网、不随机，评测与演示的"应答"角色。

    策略：有记忆注入时，把记忆块复述进回答（体现"记住了"）；
    无记忆时礼貌说明并承诺记录。评测断言的是检索与落库结果，
    应答文本只做演示观感。
    """

    def respond(self, session_id: str, user_text: str, memory_block: str) -> str:
        if memory_block.strip():
            lines = [
                ln for ln in memory_block.strip().splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            cited = "；".join(
                ln.strip().lstrip("- ").split("  [")[0] for ln in lines[:3]
            )
            return f"（结合记忆）我记得：{cited}。关于「{user_text}」，我已结合上面的记忆为你处理。"
        return f"这是新的信息，我先记下来：「{user_text}」。"
