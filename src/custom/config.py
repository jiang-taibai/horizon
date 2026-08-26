"""二开配置模型与加载器。

上游 `Config` 是 ``extra="forbid"``，禁止往 ``data/config.json`` 塞自定义字段。
因此二开配置独立存放于 ``data/custom.json``，由本模块加载。

- 结构化配置：本文件的 pydantic 模型。
- 密钥类：配置里只写**环境变量名**（沿用上游 ``api_key_env`` 惯例），运行时 ``os.getenv`` 取值。
- URL 等字段也支持 ``${VAR}`` 内联展开（复用上游 ``_expand_env_vars``）。

加载失败（文件缺失 / JSON 错 / schema 校验失败）一律**降级为空配置**（全部禁用），
保证二开可插拔、坏了也不拖垮主流程。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..storage.manager import _expand_env_vars

logger = logging.getLogger(__name__)

DEFAULT_CUSTOM_CONFIG_PATH = "data/custom.json"


class CustomSourceConfig(BaseModel):
    """单个自定义源的配置。"""

    model_config = ConfigDict(extra="forbid")

    name: str  # 显示名，兼作抓取进度条名称与报表 sub-source 标签
    type: str  # registry 里注册的 scraper 工厂 key
    enabled: bool = True
    category: Optional[str] = None  # 供 balanced_digest 分组
    profile: Optional[str] = None  # 走上游 profile 分类
    options: dict = Field(default_factory=dict)  # scraper 自定义参数（feed url、分页等）


class IllustratorConfig(BaseModel):
    """文章配图（AI 文生图）配置。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    illustrate_top_n: int = 3  # 给 digest 精选集里分数最高的前 N 条配图
    # 文本 LLM 复用上游 ai provider（生成绘画提示词），无需在此单独配置。
    # 图像 provider：决定用哪种图像 API 协议。新增协议只需在 illustrator 里加实现类。
    #   - "openai"    : OpenAI 兼容 /v1/images/generations（DALL·E、多数中转站）
    #   - "dashscope" : 阿里云百炼文生图（异步提交 + 轮询，qwen-image / wan 系列）
    image_provider: str = "openai"
    image_base_url: str = ""  # 图像 API 根地址（openai: /v1 结尾；dashscope: https://dashscope.aliyuncs.com/api/v1）
    image_model: str = "dall-e-3"
    image_api_key_env: str = "HORIZON_IMAGE_API_KEY"  # 存环境变量名，非密钥本身
    image_size: str = "1024x1024"  # openai: "1024x1024"；dashscope: "1024*1024"
    prompt_language: str = "en"  # 绘画提示词语言
    output_dir: str = "data/images"  # 图片本地落盘根目录（按 YYYY-MM-DD 分子目录）
    image_retention_days: int = 30  # 本地图片保留天数，过期目录清理
    public_base_url: str = ""  # 落盘图片对外可访问 URL 的前缀，供博客端拉取转存
    timeout_sec: float = 90.0  # 单次 HTTP 超时（同步出图会阻塞到完成，留足时间）


class PublisherConfig(BaseModel):
    """文章上传（发布到自研博客）配置。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    api_url: str = ""  # 博客接收端点（Docker 内网或公网，由部署决定）
    token_env: str = "HORIZON_BLOG_TOKEN"  # 存环境变量名，非 token 本身
    languages: List[str] = Field(default_factory=lambda: ["zh"])  # 仅发布这些语言版本
    slug_prefix: str = ""  # slug = f"{slug_prefix}{date}"，用日期做幂等键
    timeout_sec: float = 30.0


class CustomConfig(BaseModel):
    """二开配置根模型（对应 data/custom.json）。"""

    model_config = ConfigDict(extra="forbid")

    sources: List[CustomSourceConfig] = Field(default_factory=list)
    illustrator: IllustratorConfig = Field(default_factory=IllustratorConfig)
    publisher: PublisherConfig = Field(default_factory=PublisherConfig)


def load_custom_config(path: str = DEFAULT_CUSTOM_CONFIG_PATH) -> CustomConfig:
    """加载二开配置。

    仿照上游 ``StorageManager.load_config``：读 JSON → ``_expand_env_vars`` 展开
    ``${VAR}`` → pydantic 校验。

    任何失败都降级为空配置（全部禁用），并记 warning。二开配置是可选的：
    文件不存在属正常情况（用户未启用二开），JSON/schema 错误也不应拖垮主流程。
    """
    config_path = Path(path)
    if not config_path.exists():
        return CustomConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = _expand_env_vars(data)
        return CustomConfig.model_validate(data)
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        logger.warning(
            "Failed to load custom config from %s (%s); "
            "custom features disabled this run.",
            config_path,
            exc,
        )
        return CustomConfig()
