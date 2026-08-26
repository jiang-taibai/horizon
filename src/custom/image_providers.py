"""图像生成 provider 抽象层。

不同图像服务的协议差异很大（OpenAI 的 ``/v1/images/generations`` vs 阿里云百炼的
异步任务 + 轮询）。本模块把"给 prompt、拿图片二进制"抽象成统一接口 :class:`ImageProvider`，
``IllustratorConfig.image_provider`` 字段决定用哪个实现。

新增一个图像服务，只需：
1. 写一个继承 ``ImageProvider`` 的类，实现 ``async generate(prompt) -> bytes``；
2. 在 :data:`PROVIDER_REGISTRY` 里登记它的 provider key。
"""

from __future__ import annotations

import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, Type

import httpx

from .config import IllustratorConfig

logger = logging.getLogger(__name__)


class ImageProvider(ABC):
    """图像生成 provider 抽象基类。"""

    def __init__(self, cfg: IllustratorConfig):
        self.cfg = cfg

    def _api_key(self) -> str:
        return os.getenv(self.cfg.image_api_key_env, "")

    @abstractmethod
    async def generate(self, prompt: str) -> bytes:
        """根据 prompt 生成一张图，返回图片二进制。失败抛异常（由上层做 per-item 降级）。"""
        raise NotImplementedError

    @staticmethod
    async def _download(url: str, timeout: float) -> bytes:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.content


class OpenAIImageProvider(ImageProvider):
    """OpenAI 兼容图像 API（``/v1/images/generations``）。

    兼容返回 ``b64_json``（直接解码）或 ``url``（再下载）。
    """

    async def generate(self, prompt: str) -> bytes:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            base_url=self.cfg.image_base_url or None,
            api_key=self._api_key() or "no_key",
        )
        resp = await client.images.generate(
            model=self.cfg.image_model,
            prompt=prompt,
            size=self.cfg.image_size,
            n=1,
        )
        datum = resp.data[0]
        b64 = getattr(datum, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        url = getattr(datum, "url", None)
        if url:
            return await self._download(url, self.cfg.timeout_sec)
        raise ValueError("OpenAI image API returned neither b64_json nor url")


class DashScopeImageProvider(ImageProvider):
    """阿里云百炼 qwen-image-3.0 系列文生图（同步调用）。

    ``qwen-image-3.0`` / ``qwen-image-3.0-pro`` 支持 HTTP 同步调用：
    1. POST ``{root}/services/aigc/multimodal-generation/generation``
       （**不带** ``X-DashScope-Async`` 头 = 同步），body 用
       ``input.messages[].content[].text``；请求会阻塞到出图完成。
    2. 从响应 ``output.choices[].message.content[].image`` 取图片 URL
       （OSS 地址，24h 过期），立即下载返回二进制。

    ``image_base_url`` 应配 ``https://dashscope.aliyuncs.com/api/v1``；
    ``image_size`` 用 ``宽*高`` 格式（如 ``1024*1024``）。
    """

    _GEN_PATH = "/services/aigc/multimodal-generation/generation"

    def _root(self) -> str:
        return (self.cfg.image_base_url or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _normalize_size(size: str) -> str:
        """DashScope 用 ``宽*高`` 格式；兼容 OpenAI 风格的 ``1024x1024`` 写法。"""
        return size.replace("x", "*").replace("X", "*")

    async def generate(self, prompt: str) -> bytes:
        body = {
            "model": self.cfg.image_model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]}
                ]
            },
            "parameters": {
                "size": self._normalize_size(self.cfg.image_size),
                "n": 1,
                "watermark": False,
            },
        }
        async with httpx.AsyncClient(timeout=self.cfg.timeout_sec) as http:
            resp = await http.post(
                f"{self._root()}{self._GEN_PATH}",
                json=body,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                # 带上响应体，便于定位（阿里云会在 body 里给出具体错误原因）
                raise ValueError(
                    f"DashScope image API {resp.status_code}: {resp.text[:500]}"
                )
            output = resp.json().get("output") or {}
            image_url = self._extract_url(output)
            return await self._download(image_url, self.cfg.timeout_sec)

    @staticmethod
    def _extract_url(output: dict) -> str:
        # qwen-image-3.0 同步返回：output.choices[].message.content[].image
        choices = output.get("choices")
        if choices:
            for content in choices[0].get("message", {}).get("content", []):
                if content.get("image"):
                    return content["image"]
        # 兼容 results 结构（部分模型）
        results = output.get("results")
        if results and results[0].get("url"):
            return results[0]["url"]
        raise ValueError(f"DashScope returned no image url in output: {output}")


PROVIDER_REGISTRY: Dict[str, Type[ImageProvider]] = {
    "openai": OpenAIImageProvider,
    "dashscope": DashScopeImageProvider,
}


def build_image_provider(cfg: IllustratorConfig) -> ImageProvider:
    """按 cfg.image_provider 构造 provider 实例。未知 provider 抛错。"""
    provider_cls = PROVIDER_REGISTRY.get(cfg.image_provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown image_provider '{cfg.image_provider}'. "
            f"Available: {sorted(PROVIDER_REGISTRY)}"
        )
    return provider_cls(cfg)
