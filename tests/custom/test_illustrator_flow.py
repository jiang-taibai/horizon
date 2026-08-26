"""配图端到端流程测试：生词 + 图像API + 落盘 + retention + per-item 降级。

图像 API 与文本 LLM 都被 mock，不触网。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.custom import hooks, illustrator
from src.custom.config import CustomConfig, IllustratorConfig
from src.models import (
    ClassificationResult,
    ContentAnalysis,
    ContentItem,
    ProcessingResult,
    SourceType,
)


def _make_item(idx: int, profile: str = "tech-news", score: float = 9.0) -> ContentItem:
    return ContentItem(
        id=f"rss:item-{idx}",
        source_type=SourceType.RSS,
        title=f"Item {idx}",
        url=f"https://example.com/{idx}",
        published_at=datetime(2026, 4, 25, tzinfo=timezone.utc),
        profile=profile,
        processing=ProcessingResult(
            classification=ClassificationResult(profile=profile, method="source_override"),
            analysis=ContentAnalysis(score=score, reason="r", summary=f"S{idx}", tags=["AI"]),
        ),
    )


def _orch(items, illus_cfg, languages=("en", "zh"), profile_order=("tech-news",)):
    orch = SimpleNamespace(
        profiles=SimpleNamespace(names={}),
        config=SimpleNamespace(
            digest=SimpleNamespace(profile_order=list(profile_order)),
            ai=SimpleNamespace(languages=list(languages)),
        ),
    )
    orch._custom_config = CustomConfig(illustrator=illus_cfg)
    return orch


def test_illustrate_items_happy_path(tmp_path, monkeypatch):
    items = [_make_item(1), _make_item(2), _make_item(3), _make_item(4)]
    cfg = IllustratorConfig(
        enabled=True,
        illustrate_top_n=2,
        output_dir=str(tmp_path / "images"),
        public_base_url="https://cdn.test/images",
    )
    orch = _orch(items, cfg)

    captured = {}

    async def fake_complete(**kwargs):
        # 返回 JSON（匹配上游 json_object 强制格式）
        return '{"prompt": "a clean editorial illustration"}'

    monkeypatch.setattr(
        "src.ai.client.create_ai_client",
        lambda ai_cfg: SimpleNamespace(complete=fake_complete),
    )

    async def fake_image_api(cfg_, prompt):
        captured["prompt"] = prompt
        return b"\x89PNG\r\n\x1a\nfakebytes"

    monkeypatch.setattr(illustrator, "_call_image_api", fake_image_api)

    result = asyncio.run(hooks.illustrate_items(orch, items))

    # 只给 top-2 配图
    assert len(result) == 2
    # URL 用了 public_base_url
    assert all(u.startswith("https://cdn.test/images/") for u in result.values())
    # 图片确实落盘
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = tmp_path / "images" / today
    assert day_dir.exists()
    assert len(list(day_dir.glob("*.png"))) == 2
    # JSON 里的 prompt 被正确解析并传给图像 API
    assert captured["prompt"] == "a clean editorial illustration"


def test_disabled_returns_empty(tmp_path, monkeypatch):
    items = [_make_item(1)]
    cfg = IllustratorConfig(enabled=False, output_dir=str(tmp_path / "images"))
    orch = _orch(items, cfg)
    result = asyncio.run(hooks.illustrate_items(orch, items))
    assert result == {}


def test_per_item_failure_degrades(tmp_path, monkeypatch):
    """一条生图失败不影响其它条。"""
    items = [_make_item(1), _make_item(2)]
    cfg = IllustratorConfig(
        enabled=True, illustrate_top_n=2, output_dir=str(tmp_path / "images")
    )
    orch = _orch(items, cfg)

    async def fake_complete(**kwargs):
        return "prompt"

    monkeypatch.setattr(
        "src.ai.client.create_ai_client",
        lambda ai_cfg: SimpleNamespace(complete=fake_complete),
    )

    calls = {"n": 0}

    async def flaky_image_api(cfg_, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("image api down")
        return b"okbytes"

    monkeypatch.setattr(illustrator, "_call_image_api", flaky_image_api)

    result = asyncio.run(hooks.illustrate_items(orch, items))
    # 第一条失败，第二条成功
    assert len(result) == 1


def test_cleanup_removes_old_dirs(tmp_path):
    cfg = IllustratorConfig(output_dir=str(tmp_path / "images"), image_retention_days=30)
    root = tmp_path / "images"
    old = root / "2000-01-01"
    old.mkdir(parents=True)
    (old / "x.png").write_bytes(b"x")
    recent = root / "2026-04-25"
    recent.mkdir(parents=True)
    # 把旧目录 mtime 设成很久以前
    import os

    os.utime(old, (time.time() - 100 * 86400, time.time() - 100 * 86400))

    illustrator.cleanup_old_images(cfg, "2026-04-25")

    assert not old.exists()
    assert recent.exists()
