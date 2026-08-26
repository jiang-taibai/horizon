"""4 个 hook 在 orchestrator 上下文的集成/降级测试。

重点验证：二开未配置（custom.json 缺失）时，所有 hook 都安全降级，
不抛异常、不改变主流程数据。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.custom import hooks
from src.custom.config import CustomConfig


def _orch_without_custom_config():
    """一个没有 _custom_config 属性的 orchestrator 替身。"""
    return SimpleNamespace(
        config=SimpleNamespace(
            digest=SimpleNamespace(profile_order=[]),
            ai=SimpleNamespace(languages=["zh"]),
        ),
        profiles=SimpleNamespace(names={}),
    )


def test_lazy_config_load_and_cache(monkeypatch):
    calls = {"n": 0}

    def fake_load(path="data/custom.json"):
        calls["n"] += 1
        return CustomConfig()

    monkeypatch.setattr(hooks, "load_custom_config", fake_load)
    orch = _orch_without_custom_config()

    cfg1 = hooks._get_custom_config(orch)
    cfg2 = hooks._get_custom_config(orch)
    assert cfg1 is cfg2  # 缓存到实例
    assert calls["n"] == 1  # 只加载一次


def test_append_fetch_tasks_no_config_is_noop(monkeypatch):
    monkeypatch.setattr(hooks, "load_custom_config", lambda path="data/custom.json": CustomConfig())
    orch = _orch_without_custom_config()
    tasks = []
    # 不应抛，也不应改动 tasks
    hooks.append_custom_fetch_tasks(orch, tasks, client=None, since=datetime.now(timezone.utc))
    assert tasks == []


def test_illustrate_items_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(hooks, "load_custom_config", lambda path="data/custom.json": CustomConfig())
    orch = _orch_without_custom_config()
    result = asyncio.run(hooks.illustrate_items(orch, []))
    assert result == {}


def test_publish_summary_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(hooks, "load_custom_config", lambda path="data/custom.json": CustomConfig())
    orch = _orch_without_custom_config()
    # 不应抛
    asyncio.run(hooks.publish_summary(orch, "2026-04-25", "zh", "# 日报"))


def test_insert_illustrations_empty_is_identity():
    md = "# Horizon\n\ncontent"
    assert hooks.insert_illustrations(md, {}) == md
