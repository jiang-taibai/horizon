"""文章上传测试（mock 博客 API）。"""

from __future__ import annotations

import asyncio

import httpx

from src.custom import publisher
from src.custom.config import PublisherConfig

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _run(coro):
    return asyncio.run(coro)


def _patch_client(monkeypatch, transport):
    """用固定 transport 替换 publisher 内新建的 AsyncClient（保留原始类避免递归）。"""

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _capture_transport(record):
    def handler(request: httpx.Request) -> httpx.Response:
        record["url"] = str(request.url)
        record["headers"] = dict(request.headers)
        import json

        record["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler)


def test_publishes_zh_with_slug(monkeypatch):
    record = {}
    _patch_client(monkeypatch, _capture_transport(record))
    monkeypatch.setenv("HORIZON_BLOG_TOKEN", "secret-token")
    cfg = PublisherConfig(enabled=True, api_url="http://blog.test/ingest", slug_prefix="daily-")

    sent = _run(publisher.publish(cfg, date="2026-04-25", lang="zh", summary_markdown="# 日报"))

    assert sent is True
    assert record["body"]["slug"] == "daily-2026-04-25"  # 日期做幂等键
    assert record["body"]["lang"] == "zh"
    assert record["body"]["content"] == "# 日报"
    assert record["headers"]["authorization"] == "Bearer secret-token"


def test_skips_non_target_language(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: (_ for _ in ()).throw(AssertionError("should not POST")),
    )
    cfg = PublisherConfig(enabled=True, api_url="http://blog.test/ingest")  # languages=["zh"]
    sent = _run(publisher.publish(cfg, date="2026-04-25", lang="en", summary_markdown="x"))
    assert sent is False


def test_disabled_does_not_publish():
    cfg = PublisherConfig(enabled=False, api_url="http://blog.test/ingest")
    sent = _run(publisher.publish(cfg, date="2026-04-25", lang="zh", summary_markdown="x"))
    assert sent is False


def test_no_api_url_does_not_publish():
    cfg = PublisherConfig(enabled=True, api_url="")
    sent = _run(publisher.publish(cfg, date="2026-04-25", lang="zh", summary_markdown="x"))
    assert sent is False


def test_non_2xx_degrades_silently(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    cfg = PublisherConfig(enabled=True, api_url="http://blog.test/ingest")
    sent = _run(publisher.publish(cfg, date="2026-04-25", lang="zh", summary_markdown="x"))
    assert sent is False  # 不抛，静默降级
