"""自定义 scraper 基类。

自定义源不新增 ``SourceType`` 枚举成员（上游 ``ContentItem`` 是 ``extra="forbid"``
且 ``source_type`` 是固定枚举）。策略是**伪装成 ``SourceType.RSS``**，真实来源身份
放进 ``metadata``：

- ``metadata["custom_source"]`` = 源类型 key（registry 里的 type）
- ``metadata["source_name"]`` = 源显示名 —— 上游 ``_sub_source_label`` 会读它，
  使报表显示真实源名而非笼统的 "rss"。

子类只需实现 :meth:`fetch`；构造 ``ContentItem`` 时统一用 :meth:`make_item`，
以保证伪装与 metadata 约定一致。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ...models import ContentItem, ProfileRoute, SourceType
from ...scrapers.base import BaseScraper
from ..config import CustomSourceConfig


class CustomScraper(BaseScraper):
    """所有二开自定义源的基类。

    与上游 ``BaseScraper`` 兼容（同样接受 ``config`` dict 与 ``http_client``，
    实现 ``async fetch(since)``），因此能被 orchestrator 的
    ``_fetch_with_progress`` 无缝调度，白拿统一的进度与 per-source 容错。
    """

    def __init__(self, source_config: CustomSourceConfig, http_client: httpx.AsyncClient):
        super().__init__(source_config.options, http_client)
        self.source_config = source_config

    async def fetch(self, since: datetime) -> List[ContentItem]:  # pragma: no cover - abstract
        raise NotImplementedError

    def make_item(
        self,
        *,
        native_id: str,
        title: str,
        url: str,
        published_at: datetime,
        content: Optional[str] = None,
        author: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> ContentItem:
        """构造一个伪装成 RSS、带真实来源身份的 ContentItem。

        Args:
            native_id: 源内的原生条目标识（用于生成稳定 id，会被 hash）。
            title / url / published_at: 条目基本字段。
            content / author: 可选正文与作者。
            extra_metadata: 附加 metadata（会与来源身份约定字段合并）。
        """
        entry_hash = hashlib.sha256(str(native_id).encode("utf-8")).hexdigest()[:16]
        metadata: Dict[str, Any] = {
            "custom_source": self.source_config.type,
            "source_name": self.source_config.name,
            "category": self.source_config.category,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        profile: ProfileRoute = self.source_config.profile
        return ContentItem(
            id=self._generate_id("custom", self.source_config.type, entry_hash),
            source_type=SourceType.RSS,  # 伪装：走上游 RSS 下游流程
            title=title,
            url=url,
            content=content,
            author=author or self.source_config.name,
            published_at=published_at,
            profile=profile,
            metadata=metadata,
        )
