"""示例自定义源：抓取一个返回 JSON 列表的 HTTP 接口。

演示"目标站点没有 RSS、需要调它的 JSON API"这类场景。真实二开时可复制此文件、
改写 :meth:`fetch` 的解析逻辑即可。

配置（``data/custom.json`` 的 sources 条目）示例::

    {
      "name": "示例 JSON 源",
      "type": "example_json",
      "category": "tech",
      "profile": null,
      "options": {
        "url": "https://api.example.com/items",
        "title_field": "title",
        "url_field": "link",
        "id_field": "id",
        "time_field": "published_at"
      }
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from dateutil import parser as date_parser

from ...models import ContentItem
from .base import CustomScraper


class ExampleJSONScraper(CustomScraper):
    """从一个返回 JSON 数组的接口抓取条目。"""

    async def fetch(self, since: datetime) -> List[ContentItem]:
        opts = self.source_config.options
        url = opts.get("url")
        if not url:
            return []

        title_field = opts.get("title_field", "title")
        url_field = opts.get("url_field", "url")
        id_field = opts.get("id_field", "id")
        time_field = opts.get("time_field", "published_at")

        response = await self.client.get(url, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()

        rows = payload if isinstance(payload, list) else payload.get("items", [])
        items: List[ContentItem] = []
        for row in rows:
            published_at = self._parse_time(row.get(time_field))
            if published_at is None or published_at < since:
                continue

            link = row.get(url_field)
            if not link:
                continue

            items.append(
                self.make_item(
                    native_id=str(row.get(id_field, link)),
                    title=row.get(title_field, "Untitled"),
                    url=link,
                    published_at=published_at,
                    content=row.get("content") or row.get("summary"),
                )
            )
        return items

    @staticmethod
    def _parse_time(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = date_parser.parse(str(value))
        except (ValueError, OverflowError, TypeError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
