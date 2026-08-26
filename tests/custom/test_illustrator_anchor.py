"""★ 契约测试：illustrator 复刻的 anchor_id 必须与 summarizer 实际渲染的
``<a id="...">`` 完全一致。

这是配图定位的地基。若上游改了 anchor 生成规则（``_item_anchor`` / ``build_view``），
本测试会失败，提醒二开侧同步修正，避免图片静默插错位置。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from types import SimpleNamespace

from src.ai.summarizer import DailySummarizer
from src.custom.illustrator import compute_anchor_map, select_targets
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentArtifact,
    ContentBlock,
    ContentItem,
    ProcessingResult,
    SourceType,
)


def _make_item(idx: int, profile: str, score: float) -> ContentItem:
    return ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="content",
        author="tester",
        published_at=datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc),
        profile=profile,
        processing=ProcessingResult(
            classification=ClassificationResult(profile=profile, method="source_override"),
            analysis=ContentAnalysis(
                score=score, reason="r", summary=f"Summary {idx}.", tags=["AI"]
            ),
            artifacts={
                lang: ContentArtifact(
                    language=lang,
                    title=f"Item {idx}",
                    blocks=[
                        ContentBlock(id="summary", title="S", content=f"Summary {idx}.", primary=True)
                    ],
                )
                for lang in ("en", "zh")
            },
        ),
    )


def _fake_orchestrator(items, profile_order=None, languages=("en", "zh")):
    """构造一个足够 compute_anchor_map 使用的最小 orchestrator 替身。"""
    return SimpleNamespace(
        profiles=SimpleNamespace(names={}),
        config=SimpleNamespace(
            digest=SimpleNamespace(profile_order=list(profile_order or [])),
            ai=SimpleNamespace(languages=list(languages)),
        ),
    )


def _rendered_anchors(summary_markdown: str) -> list[str]:
    return re.findall(r'<a id="([^"]+)"></a>', summary_markdown)


def test_computed_anchor_matches_rendered_id():
    """核心契约：compute_anchor_map 的值 == generate_summary 渲染出的 id。"""
    items = [
        _make_item(1, "tech-news", 9.0),
        _make_item(2, "tech-news", 8.0),
        _make_item(3, "research", 7.0),
    ]
    orch = _fake_orchestrator(items, profile_order=["tech-news", "research"])

    anchor_map = compute_anchor_map(orch, items)

    # 用相同参数真实渲染一版 summary，抓出其中的 id
    summarizer = DailySummarizer(profile_names={}, profile_order=["tech-news", "research"])
    summary = asyncio.run(
        summarizer.generate_summary(items, date="2026-04-25", total_fetched=10, language="en")
    )
    rendered = set(_rendered_anchors(summary))

    # 每个 item 计算出的 anchor 都真实出现在 summary 里
    for item in items:
        assert anchor_map[id(item)] in rendered


def test_anchor_language_independent():
    """anchor 与语言无关：en / zh 渲染出的 id 集合一致。"""
    items = [_make_item(1, "tech-news", 9.0), _make_item(2, "research", 8.0)]
    summarizer = DailySummarizer(profile_names={}, profile_order=["tech-news", "research"])
    en = set(
        _rendered_anchors(
            asyncio.run(summarizer.generate_summary(items, "2026-04-25", 5, language="en"))
        )
    )
    zh = set(
        _rendered_anchors(
            asyncio.run(summarizer.generate_summary(items, "2026-04-25", 5, language="zh"))
        )
    )
    assert en == zh


def test_select_targets_top_n():
    items = [_make_item(i, "tech-news", 10.0 - i) for i in range(5)]
    assert select_targets(items, 3) == items[:3]
    assert select_targets(items, 0) == []
    assert select_targets(items, 99) == items
