"""图像 provider 抽象层测试（OpenAI 兼容 + DashScope 异步轮询）。"""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from src.custom.config import IllustratorConfig
from src.custom.image_providers import (
    DashScopeImageProvider,
    OpenAIImageProvider,
    build_image_provider,
)

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_client(monkeypatch, transport):
    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_build_provider_by_key():
    assert isinstance(
        build_image_provider(IllustratorConfig(image_provider="openai")), OpenAIImageProvider
    )
    assert isinstance(
        build_image_provider(IllustratorConfig(image_provider="dashscope")), DashScopeImageProvider
    )


def test_build_provider_unknown_raises():
    with pytest.raises(ValueError):
        build_image_provider(IllustratorConfig(image_provider="nope"))


def test_dashscope_sync_generate_download(monkeypatch):
    """DashScope 同步：POST multimodal-generation → 拿图片 URL → 下载二进制。"""
    img_bytes = b"\x89PNG\r\nDASHSCOPE"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and "multimodal-generation/generation" in url:
            # 同步：不应带 async 头
            assert "x-dashscope-async" not in {k.lower() for k in request.headers}
            assert request.headers.get("authorization") == "Bearer sk-test"
            body = request.read().decode()
            assert "一只在草地上奔跑的柯基" in body
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {"message": {"content": [{"image": "https://oss.test/img.png"}]}}
                        ]
                    }
                },
            )
        if request.method == "GET" and "oss.test/img.png" in url:
            return httpx.Response(200, content=img_bytes)
        return httpx.Response(404)

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setenv("HORIZON_IMAGE_API_KEY", "sk-test")

    cfg = IllustratorConfig(
        image_provider="dashscope",
        image_base_url="https://dashscope.aliyuncs.com/api/v1",
        image_model="qwen-image-3.0-pro",
        image_size="1024*1024",
    )
    provider = DashScopeImageProvider(cfg)
    data = asyncio.run(provider.generate("一只在草地上奔跑的柯基"))
    assert data == img_bytes


def test_dashscope_extracts_message_content_url():
    """从 choices[].message.content[].image 结构取 URL。"""
    output = {"choices": [{"message": {"content": [{"image": "https://oss.test/x.png"}]}}]}
    assert DashScopeImageProvider._extract_url(output) == "https://oss.test/x.png"


def test_dashscope_400_includes_response_body(monkeypatch):
    """400 报错要带上响应体，便于定位真正原因。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "InvalidParameter", "message": "bad size"})

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    cfg = IllustratorConfig(image_provider="dashscope")
    provider = DashScopeImageProvider(cfg)
    with pytest.raises(ValueError, match="bad size"):
        asyncio.run(provider.generate("x"))


def test_openai_provider_b64(monkeypatch):
    """OpenAI provider：返回 b64_json 时直接解码。"""
    raw = b"openai-image-bytes"
    b64 = base64.b64encode(raw).decode()

    class FakeImages:
        async def generate(self, **kwargs):
            from types import SimpleNamespace

            return SimpleNamespace(data=[SimpleNamespace(b64_json=b64, url=None)])

    class FakeClient:
        def __init__(self, **kwargs):
            self.images = FakeImages()

    monkeypatch.setattr("openai.AsyncOpenAI", FakeClient)
    cfg = IllustratorConfig(image_provider="openai", image_model="dall-e-3")
    provider = OpenAIImageProvider(cfg)
    data = asyncio.run(provider.generate("a cat"))
    assert data == raw
