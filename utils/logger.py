"""
utils/logger.py

统一日志配置模块。
日志同时输出到控制台和用户目录下的日志文件，便于打包为 .app 后排查问题。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(name: str = "SmartShortsToolkit") -> logging.Logger:
    """
    初始化并返回应用全局 Logger。

    日志文件位置：
        ~/Library/Logs/SmartShortsToolkit/app.log

    Args:
        name: logger 名称

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # 避免重复添加 handler（多次调用）
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    try:
        log_dir = Path.home() / "Library" / "Logs" / "SmartShortsToolkit"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:  # noqa: BLE001
        # 日志文件创建失败不应阻止程序运行
        logger.warning("无法创建日志文件: %s", exc)

    return logger
