"""二开配置加载器测试。"""

from __future__ import annotations

import json

import pytest

from src.custom.config import (
    CustomConfig,
    IllustratorConfig,
    PublisherConfig,
    load_custom_config,
)


def _write(tmp_path, data: dict):
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_missing_file_returns_empty_config(tmp_path):
    """文件不存在 → 返回空配置（全部禁用），不报错。"""
    cfg = load_custom_config(str(tmp_path / "nope.json"))
    assert isinstance(cfg, CustomConfig)
    assert cfg.sources == []
    assert cfg.illustrator.enabled is False
    assert cfg.publisher.enabled is False


def test_defaults():
    """默认值符合方案约定。"""
    assert IllustratorConfig().illustrate_top_n == 3
    assert IllustratorConfig().image_retention_days == 30
    assert PublisherConfig().languages == ["zh"]


def test_load_valid_config(tmp_path):
    path = _write(
        tmp_path,
        {
            "sources": [
                {"name": "我的源", "type": "example", "options": {"url": "https://x.test/feed"}}
            ],
            "illustrator": {"enabled": True, "illustrate_top_n": 5},
            "publisher": {"enabled": True, "api_url": "http://blog:8080/api"},
        },
    )
    cfg = load_custom_config(path)
    assert len(cfg.sources) == 1
    assert cfg.sources[0].name == "我的源"
    assert cfg.sources[0].enabled is True  # 默认
    assert cfg.illustrator.illustrate_top_n == 5
    assert cfg.publisher.api_url == "http://blog:8080/api"


def test_env_var_expansion(tmp_path, monkeypatch):
    """${VAR} 在字符串值里被展开。"""
    monkeypatch.setenv("MY_BLOG_URL", "https://blog.example.com/ingest")
    path = _write(
        tmp_path,
        {"publisher": {"enabled": True, "api_url": "${MY_BLOG_URL}"}},
    )
    cfg = load_custom_config(path)
    assert cfg.publisher.api_url == "https://blog.example.com/ingest"


def test_invalid_json_degrades_to_empty(tmp_path):
    """JSON 语法错 → 降级空配置 + warning，不抛。"""
    path = tmp_path / "custom.json"
    path.write_text("{ not valid json", encoding="utf-8")
    cfg = load_custom_config(str(path))
    assert cfg.sources == []
    assert cfg.illustrator.enabled is False


def test_schema_error_degrades_to_empty(tmp_path):
    """schema 校验失败（缺 name/type 等）→ 降级空配置，不抛。"""
    path = _write(tmp_path, {"sources": [{"type": "example"}]})  # 缺 name
    cfg = load_custom_config(path)
    assert cfg.sources == []


def test_extra_field_forbidden(tmp_path):
    """未知字段 → 校验失败 → 降级空配置（extra=forbid 生效）。"""
    path = _write(tmp_path, {"illustrator": {"enabled": True, "bogus": 1}})
    cfg = load_custom_config(path)
    # 校验失败降级，enabled 回到默认 False
    assert cfg.illustrator.enabled is False
