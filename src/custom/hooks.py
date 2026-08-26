"""二开 hook 的逻辑本体入口。

上游 ``orchestrator.py`` 只调用本模块的公开函数（每处一行薄 hook，带
``HORIZON-CUSTOM`` 标记）。所有二开逻辑都在 ``src/custom/`` 内，orchestrator
不感知细节。所有 hook 都对异常静默降级，绝不拖垮主流程。

配置惰性加载：首次访问时读 ``data/custom.json`` 并缓存到 orchestrator 实例的
``_custom_config`` 属性（避免侵入上游 ``__init__``）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List

import httpx

from .config import CustomConfig, load_custom_config

# 匹配 summary 里每条报道前的锚点行：<a id="item-xxx"></a>
_ANCHOR_RE = re.compile(r'<a id="([^"]+)"></a>\s*$')

if TYPE_CHECKING:  # 仅类型提示，运行时不 import，避免循环依赖
    from ..models import ContentItem
    from ..orchestrator import HorizonOrchestrator

logger = logging.getLogger(__name__)


def _get_custom_config(orchestrator: "HorizonOrchestrator") -> CustomConfig:
    """惰性加载并缓存二开配置到 orchestrator 实例。"""
    cfg = getattr(orchestrator, "_custom_config", None)
    if cfg is None:
        cfg = load_custom_config()
        orchestrator._custom_config = cfg
    return cfg


# ---------------------------------------------------------------------------
# 功能1：自定义源
# ---------------------------------------------------------------------------
def append_custom_fetch_tasks(
    orchestrator: "HorizonOrchestrator",
    tasks: list,
    client: httpx.AsyncClient,
    since: datetime,
) -> None:
    """把已启用的自定义源的抓取任务追加进 ``tasks`` 列表（原地修改）。

    复用 ``orchestrator._fetch_with_progress`` 以获得统一的进度显示与 per-source
    容错。构造期异常（配置/registry）在此吞掉并记 warning，不追加任何任务。
    """
    try:
        from .registry import build_scraper

        config = _get_custom_config(orchestrator)
        for source_cfg in config.sources:
            if not source_cfg.enabled:
                continue
            scraper = build_scraper(source_cfg, client)
            if scraper is None:
                continue
            tasks.append(
                orchestrator._fetch_with_progress(source_cfg.name, scraper, since)
            )
    except Exception as exc:  # noqa: BLE001 - 静默降级，不拖垮抓取主流程
        logger.warning("Custom sources hook failed (%s); skipped.", exc)


# ---------------------------------------------------------------------------
# 功能2：文章配图（后处理插入）
# ---------------------------------------------------------------------------
def insert_illustrations(summary_markdown: str, anchor_to_url: Dict[str, str]) -> str:
    """在 summary 字符串里按 anchor 定位，把 ``![](url)`` 插到标题行下方。

    summary 里每条报道形如::

        <a id="item-tech-news-1"></a>
        ### [标题](url) ⭐️ 8/10

    图片在**转义之后**注入（不经过上游 ``_escape_markdown``），所以 ``![](url)``
    保持为真实图片语法。url 是我们生成的可信公网地址。

    纯字符串操作，整体 try/except：任何异常都原样返回未插图 summary，
    保证 summary 永不损坏（宁可无图，不可损坏）。
    """
    if not anchor_to_url:
        return summary_markdown
    try:
        lines = summary_markdown.split("\n")
        out: List[str] = []
        i = 0
        while i < len(lines):
            out.append(lines[i])
            match = _ANCHOR_RE.match(lines[i])
            if match and match.group(1) in anchor_to_url:
                # 紧跟的下一行应是标题行（### ...）；连同它一起吐出，再插图
                if i + 1 < len(lines):
                    out.append(lines[i + 1])
                    i += 1
                out.append("")
                out.append(f"![]({anchor_to_url[match.group(1)]})")
            i += 1
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001 - 静默降级，不损坏 summary
        logger.warning("insert_illustrations failed (%s); summary left unmodified.", exc)
        return summary_markdown


async def illustrate_items(
    orchestrator: "HorizonOrchestrator",
    important_items: List["ContentItem"],
    today: str,
) -> Dict[str, str]:
    """为 top-N 精选报道生图，返回 ``{anchor_id: 公网图片URL}``（语言无关）。

    在 lang 循环前调用一次，映射被循环内所有语言的 summary 共享。
    ``today`` 由 orchestrator 统一传入（与 summary/落盘路径同一日期），避免跨午夜边界不一致。
    外层 + per-item 双层静默降级：任何失败只影响个别配图，绝不中断主流程。
    """
    result: Dict[str, str] = {}
    try:
        from . import illustrator

        cfg = _get_custom_config(orchestrator).illustrator
        if not cfg.enabled or not important_items:
            return result

        anchor_map = illustrator.compute_anchor_map(orchestrator, important_items)
        targets = illustrator.select_targets(important_items, cfg.illustrate_top_n)

        for item in targets:
            anchor = anchor_map.get(id(item))
            if not anchor:
                continue
            try:
                url = await illustrator.illustrate_one(orchestrator, cfg, item, today)
                if url:
                    result[anchor] = url
            except Exception as exc:  # noqa: BLE001 - per-item 降级
                logger.warning("Illustration failed for %s (%s); skipped.", item.id, exc)

        illustrator.cleanup_old_images(cfg, today)
    except Exception as exc:  # noqa: BLE001 - 外层降级
        logger.warning("Illustrate hook failed (%s); no images this run.", exc)
    return result


# ---------------------------------------------------------------------------
# 功能3：文章上传
# ---------------------------------------------------------------------------
async def publish_summary(
    orchestrator: "HorizonOrchestrator",
    date: str,
    lang: str,
    summary_markdown: str,
) -> None:
    """把（带图的）日报发布到自研博客。仅配置的语言（默认 zh）会真正发出。

    整体静默降级：配置未启用 / 非目标语言 / 网络失败都不影响主流程。
    """
    try:
        from . import publisher

        cfg = _get_custom_config(orchestrator).publisher
        await publisher.publish(
            cfg, date=date, lang=lang, summary_markdown=summary_markdown
        )
    except Exception as exc:  # noqa: BLE001 - 静默降级
        logger.warning("Publish hook failed (%s); skipped.", exc)
