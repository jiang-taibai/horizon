"""后处理插图测试（纯字符串）。"""

from __future__ import annotations

from src.custom.hooks import insert_illustrations

SUMMARY = """# Horizon - 2026-04-25

<a id="item-tech-news-1"></a>
### [标题一](https://x.test/1) ⭐️ 9/10

正文一

<a id="item-tech-news-2"></a>
### [标题二](https://x.test/2) ⭐️ 8/10

正文二
"""


def test_inserts_image_after_title_line():
    out = insert_illustrations(SUMMARY, {"item-tech-news-1": "https://img/1.png"})
    lines = out.split("\n")
    # 找到标题一那行，其后应出现图片
    idx = next(i for i, l in enumerate(lines) if "标题一" in l)
    assert "![](https://img/1.png)" in lines[idx + 1 : idx + 3]
    # 标题二没配图，不应出现图片
    assert "![](https://img/1.png)" not in "\n".join(
        lines[next(i for i, l in enumerate(lines) if "标题二" in l):]
    )


def test_multiple_anchors():
    out = insert_illustrations(
        SUMMARY,
        {"item-tech-news-1": "https://img/1.png", "item-tech-news-2": "https://img/2.png"},
    )
    assert "![](https://img/1.png)" in out
    assert "![](https://img/2.png)" in out


def test_empty_map_returns_unchanged():
    assert insert_illustrations(SUMMARY, {}) == SUMMARY


def test_unknown_anchor_ignored():
    out = insert_illustrations(SUMMARY, {"item-does-not-exist": "https://img/x.png"})
    assert "![]" not in out
    assert out == SUMMARY


def test_image_not_escaped():
    """插入的图片是真 markdown（不带反斜杠转义）。"""
    out = insert_illustrations(SUMMARY, {"item-tech-news-1": "https://img/1.png"})
    assert "\\!\\[" not in out
    assert "![](https://img/1.png)" in out
