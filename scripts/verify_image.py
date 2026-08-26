#!/usr/bin/env python
"""独立验证：用真实 API key 调一次图像服务，确认能真的生成图片。

用途：在把配图接进日报前，先单独把"图像 API 能出图"这件事验证通过，
避免每次都要跑完整个 horizon 才发现图像配置有问题。

用法：
    uv run python scripts/verify_image.py
    uv run python scripts/verify_image.py "自定义绘画提示词"

它会：
1. 加载 .env（取 API key）与 data/custom.json 的 illustrator 配置；
2. 按 image_provider 调一次真实图像 API；
3. 成功则把图片存到 data/images/_verify/ 并打印路径；
4. 失败则打印完整错误（含 API 返回的响应体）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 允许直接 `python scripts/verify_image.py` 运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from src.custom.config import load_custom_config  # noqa: E402
from src.custom.image_providers import build_image_provider  # noqa: E402


async def main() -> int:
    load_dotenv()

    cfg = load_custom_config().illustrator
    prompt = sys.argv[1] if len(sys.argv) > 1 else (
        "一张简洁现代的科技新闻封面插画，蓝色调，扁平风格，画面中没有任何文字"
    )

    print("=== 图像服务验证 ===")
    print(f"provider   : {cfg.image_provider}")
    print(f"base_url   : {cfg.image_base_url}")
    print(f"model      : {cfg.image_model}")
    print(f"size       : {cfg.image_size}")
    print(f"api_key_env: {cfg.image_api_key_env}")
    import os

    key = os.getenv(cfg.image_api_key_env, "")
    print(f"api_key    : {'已设置 (' + key[:6] + '...)' if key else '❌ 未设置！请检查 .env'}")
    print(f"prompt     : {prompt}")
    print("-" * 40)

    if not key:
        print(f"❌ 环境变量 {cfg.image_api_key_env} 未设置。请在 .env 里填好再试。")
        return 1

    try:
        provider = build_image_provider(cfg)
        print("正在请求图像 API（同步出图可能需要 10~40 秒）...")
        data = await provider.generate(prompt)
    except Exception as exc:
        print(f"❌ 生成失败：{type(exc).__name__}: {exc}")
        return 1

    out_dir = Path(cfg.output_dir) / "_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verify.png"
    out_path.write_bytes(data)
    print(f"✅ 成功！图片已保存：{out_path}（{len(data)} 字节）")
    print("   打开这个文件确认是正常图片，即说明图像服务配置正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
