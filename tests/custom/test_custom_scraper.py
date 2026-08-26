"""自定义源 scraper / registry / fetch hook 测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.custom.config import CustomSourceConfig
from src.custom.registry import build_scraper
from src.custom.scrapers.base import CustomScraper
from src.custom.scrapers.example_source import ExampleJSONScraper
from src.models import SourceType


def _client_returning(payload):
    """构造一个 httpx.AsyncClient，其 GET 返回固定 JSON payload。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def _fetch(payload, cfg, since):
    """在单个 event loop 内建 client 并抓取（MockTransport 需与 client 同 loop）。"""

    async def _run():
        async with _client_returning(payload) as client:
            scraper = ExampleJSONScraper(cfg, client)
            return await scraper.fetch(since)

    return asyncio.run(_run())


def test_example_scraper_disguises_as_rss_with_identity():
    now = datetime.now(timezone.utc)
    payload = [
        {
            "id": "a1",
            "title": "热点新闻",
            "link": "https://x.test/a1",
            "published_at": now.isoformat(),
            "summary": "正文",
        }
    ]
    cfg = CustomSourceConfig(
        name="我的自定义源",
        type="example_json",
        category="tech",
        options={"url": "https://api.test/items", "url_field": "link"},
    )
    items = _fetch(payload, cfg, now - timedelta(hours=1))

    assert len(items) == 1
    item = items[0]
    # 伪装成 RSS
    assert item.source_type == SourceType.RSS
    # 真实来源身份放 metadata
    assert item.metadata["custom_source"] == "example_json"
    assert item.metadata["source_name"] == "我的自定义源"
    assert item.metadata["category"] == "tech"
    assert item.title == "热点新闻"
    assert str(item.url) == "https://x.test/a1"


def test_example_scraper_filters_by_since():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=5)).isoformat()
    payload = [
        {"id": "old", "title": "旧", "link": "https://x.test/old", "published_at": old},
        {"id": "new", "title": "新", "link": "https://x.test/new", "published_at": now.isoformat()},
    ]
    cfg = CustomSourceConfig(
        name="s",
        type="example_json",
        options={"url": "https://api.test/items", "url_field": "link"},
    )
    items = _fetch(payload, cfg, now - timedelta(hours=1))

    assert [i.title for i in items] == ["新"]


def test_missing_url_returns_empty():
    cfg = CustomSourceConfig(name="s", type="example_json", options={})
    items = _fetch([], cfg, datetime.now(timezone.utc))
    assert items == []


def test_registry_known_type():
    cfg = CustomSourceConfig(name="s", type="example_json", options={})
    scraper = build_scraper(cfg, http_client=None)  # 构造不触网
    assert isinstance(scraper, ExampleJSONScraper)
    assert isinstance(scraper, CustomScraper)


def test_registry_unknown_type_returns_none():
    cfg = CustomSourceConfig(name="s", type="does_not_exist", options={})
    assert build_scraper(cfg, http_client=None) is None
