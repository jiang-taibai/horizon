"""文章配图（AI 文生图）。

对 digest 精选集里分数最高的前 N 条报道生成配图：
1. 复用上游文本 LLM（``create_ai_client``）为报道生成一段"绘画提示词"；
2. 调 OpenAI 兼容图像 API（``/v1/images/generations``）出图；
3. 图片落盘到 ``data/images/YYYY-MM-DD/``；
4. 返回 ``{anchor_id: 公网图片URL}`` 映射，供后处理把 ``![](url)`` 插进 summary。

**anchor_id 匹配**：图片要插到 summary 里正确的报道下，而 summary 里每条报道的
HTML 锚点由 ``DailySummarizer.build_view`` 按 profile 分组 + 组内 index 计算。
本模块复刻同一 ``build_view`` 调用，用 **对象身份 ``id(item)``** 反查每个 item 的
anchor_id（``build_view`` 不复制 item，引用一致），绕开标题/URL 被转义变换的问题。
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from .config import IllustratorConfig

if TYPE_CHECKING:
    from ..models import ContentItem
    from ..orchestrator import HorizonOrchestrator

logger = logging.getLogger(__name__)

# 让文本 LLM 产出绘画提示词的系统指令。
# 必须输出 JSON：上游 OpenAIClient 会强制 response_format=json_object，
# 且部分兼容 endpoint（如阿里云百炼）要求 prompt 中出现 "json" 字样才允许该模式。
_PROMPT_SYSTEM = (
    "You are an art director. Given a news headline and summary, write ONE concise "
    "image-generation prompt (<=60 words) for a clean, modern, editorial cover "
    "illustration with no text/letters in the image. Write the prompt in {lang}. "
    'Respond ONLY with a JSON object of the form {{"prompt": "<the prompt>"}}.'
)


def compute_anchor_map(
    orchestrator: "HorizonOrchestrator",
    items: List["ContentItem"],
) -> Dict[int, str]:
    """复刻 summarizer 的分组/anchor 计算，返回 ``{id(item): anchor_id}``。

    使用与 orchestrator 的 lang 循环内**完全相同**的参数构造 ``DailySummarizer``，
    保证算出的 anchor 与 ``generate_summary`` 渲染进 markdown 的 ``id=`` 一致。
    anchor 与语言无关（``_item_anchor`` 只吃 profile_id + 组内 index），用任一
    语言计算即可。
    """
    from ..ai.summarizer import DailySummarizer

    if not items:
        return {}

    summarizer = DailySummarizer(
        profile_names=orchestrator.profiles.names,
        profile_order=orchestrator.config.digest.profile_order,
    )
    lang0 = orchestrator.config.ai.languages[0] if orchestrator.config.ai.languages else "en"
    view = summarizer.build_view(items, lang0)

    anchor_map: Dict[int, str] = {}
    for group in view.groups:
        for view_item in group.items:
            anchor_map[id(view_item.item)] = view_item.anchor_id
    return anchor_map


def select_targets(
    items: List["ContentItem"], top_n: int
) -> List["ContentItem"]:
    """取分数最高的前 N 条。``items`` 已按 score 降序（orchestrator 保证）。"""
    if top_n <= 0:
        return []
    return list(items[:top_n])


async def generate_prompt(orchestrator: "HorizonOrchestrator", cfg: IllustratorConfig, item: "ContentItem") -> str:
    """用上游文本 LLM 为一条报道生成绘画提示词。

    上游 ``OpenAIClient`` 会强制 ``response_format=json_object``，故让模型返回
    ``{"prompt": ...}`` JSON 再解析；解析失败降级到用原始文本或标题。
    """
    from ..ai.client import create_ai_client
    from ..ai.utils import parse_json_response

    client = create_ai_client(orchestrator.config.ai)
    analysis = item.processing.analysis if item.processing else None
    summary = (analysis.summary if analysis else "") or ""
    user = f"Headline: {item.title}\nSummary: {summary}"
    system = _PROMPT_SYSTEM.format(lang=cfg.prompt_language)
    raw = await client.complete(system=system, user=user, max_tokens=300)

    parsed = parse_json_response(raw or "")
    if parsed and isinstance(parsed.get("prompt"), str) and parsed["prompt"].strip():
        return parsed["prompt"].strip()
    # 降级：解析失败时用原始文本（去掉可能的 JSON 包裹）或标题兜底
    return (raw or "").strip() or item.title


async def _call_image_api(cfg: IllustratorConfig, prompt: str) -> bytes:
    """按配置的 image_provider 生成图片二进制。

    协议差异封装在 :mod:`image_providers` 里；本函数只负责按 provider 分发，
    保持 illustrator 与具体图像服务解耦，方便以后切换模型。
    """
    from .image_providers import build_image_provider

    provider = build_image_provider(cfg)
    return await provider.generate(prompt)


def _save_image(cfg: IllustratorConfig, date: str, native_id: str, data: bytes) -> str:
    """把图片落盘到 output_dir/YYYY-MM-DD/，返回相对文件名（用于拼公网 URL）。"""
    day_dir = Path(cfg.output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{native_id}.png"
    (day_dir / fname).write_bytes(data)
    return fname


def _public_url(cfg: IllustratorConfig, date: str, fname: str) -> str:
    """拼接图片对外可访问 URL。"""
    base = cfg.public_base_url.rstrip("/")
    return f"{base}/{date}/{fname}" if base else f"{date}/{fname}"


def cleanup_old_images(cfg: IllustratorConfig, today: str) -> None:
    """删除 output_dir 下超过 image_retention_days 天的日期目录。静默降级。"""
    try:
        root = Path(cfg.output_dir)
        if not root.exists() or cfg.image_retention_days <= 0:
            return
        cutoff = time.time() - cfg.image_retention_days * 86400
        for child in root.iterdir():
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Image cleanup failed (%s); skipped.", exc)


async def illustrate_one(
    orchestrator: "HorizonOrchestrator",
    cfg: IllustratorConfig,
    item: "ContentItem",
    date: str,
) -> Optional[str]:
    """为单条报道生图并落盘，返回公网 URL。任一步异常向上抛给调用者做 per-item 降级。"""
    prompt = await generate_prompt(orchestrator, cfg, item)
    data = await _call_image_api(cfg, prompt)
    # 用 item.id 的安全形式做文件名
    native_id = item.id.replace(":", "_").replace("/", "_")
    fname = _save_image(cfg, date, native_id, data)
    return _public_url(cfg, date, fname)
