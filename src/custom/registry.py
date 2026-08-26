"""自定义 scraper 注册表。

把 ``CustomSourceConfig.type`` 映射到具体的 scraper 类。新增自定义源时：
1. 在 ``scrapers/`` 下写一个继承 ``CustomScraper`` 的类；
2. 在 :data:`SCRAPER_REGISTRY` 里登记它的 ``type`` key。

orchestrator 侧完全不需要改动——装配由 ``hooks.append_custom_fetch_tasks`` 驱动。
"""

from __future__ import annotations

import logging
from typing import Dict, Type

import httpx

from .config import CustomSourceConfig
from .scrapers.base import CustomScraper
from .scrapers.example_source import ExampleJSONScraper

logger = logging.getLogger(__name__)

# type key -> scraper 类
SCRAPER_REGISTRY: Dict[str, Type[CustomScraper]] = {
    "example_json": ExampleJSONScraper,
}


def build_scraper(
    source_config: CustomSourceConfig, http_client: httpx.AsyncClient
) -> CustomScraper | None:
    """按 config.type 构造 scraper 实例。

    未知 type 记 warning 并返回 ``None``（跳过该源，不影响其它源）。
    """
    scraper_cls = SCRAPER_REGISTRY.get(source_config.type)
    if scraper_cls is None:
        logger.warning(
            "Unknown custom source type '%s' (source '%s'); skipping.",
            source_config.type,
            source_config.name,
        )
        return None
    return scraper_cls(source_config, http_client)
