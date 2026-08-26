"""文章上传（发布到自研博客）。

把日报 Markdown POST 到自研博客 API。默认仅发布 zh 版（一天一篇），请求带
``slug``（用日期）做幂等键，同日重复运行覆盖而非新建。

图片在 Markdown 里是完整公网 URL，博客端负责拉取转存图床 + 生命周期管理，
本项目不碰图床。

网络形态（Docker 内网 / 公网 URL）由 ``PublisherConfig.api_url`` 决定，代码不写死。
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from .config import PublisherConfig

logger = logging.getLogger(__name__)


async def publish(
    cfg: PublisherConfig,
    *,
    date: str,
    lang: str,
    summary_markdown: str,
) -> bool:
    """发布一版日报。返回是否实际发出。

    仅当 ``enabled``、``api_url`` 非空、且 ``lang`` 在 ``cfg.languages`` 内才发。
    失败（网络/超时/非 2xx）静默降级：记 warning 返回 False，绝不抛。
    """
    if not cfg.enabled or not cfg.api_url:
        return False
    if lang not in cfg.languages:
        return False

    slug = f"{cfg.slug_prefix}{date}"
    payload = {
        "slug": slug,
        "date": date,
        "lang": lang,
        "content": summary_markdown,
    }
    headers = {}
    token = os.getenv(cfg.token_env, "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_sec) as client:
            resp = await client.post(cfg.api_url, json=payload, headers=headers)
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - 静默降级，不影响主流程
        logger.warning("Publish to blog failed (%s); skipped.", exc)
        return False
