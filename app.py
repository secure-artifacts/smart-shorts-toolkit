"""
app.py

Smart Shorts Toolkit 应用入口。

启动流程：
    1. 初始化日志系统
    2. 检查 FFmpeg / FFprobe 是否可用（缺失时提示安装方式但不阻止启动界面）
    3. 创建并显示主窗口
    4. 进入 Qt 事件循环
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from ui.main_window import MainWindow
from utils.ffmpeg_utils import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path
from utils.logger import setup_logger

logger = setup_logger()


def check_ffmpeg_available() -> str | None:
    """
    检查 ffmpeg 与 ffprobe 是否可用。

    Returns:
        如果缺失，返回提示信息字符串；否则返回 None。
    """
    try:
        ffmpeg_path = get_ffmpeg_path()
        ffprobe_path = get_ffprobe_path()
        logger.info("FFmpeg 路径: %s", ffmpeg_path)
        logger.info("FFprobe 路径: %s", ffprobe_path)
        return None
    except FFmpegNotFoundError as exc:
        logger.error("FFmpeg/FFprobe 检测失败: %s", exc)
        return str(exc)


def main() -> int:
    """应用主入口函数，返回进程退出码。"""
    logger.info("Smart Shorts Toolkit 启动")

    app = QApplication(sys.argv)
    app.setApplicationName("Smart Shorts Toolkit")
    app.setOrganizationName("SmartShortsToolkit")

    # 检查 FFmpeg 可用性，缺失时给出友好提示（不阻止界面打开）
    ffmpeg_error = check_ffmpeg_available()
    if ffmpeg_error:
        QMessageBox.warning(
            None,
            "未检测到 FFmpeg",
            "未在系统中检测到 FFmpeg / FFprobe，相关功能将无法使用。\n\n"
            "请通过 Homebrew 安装：\n"
            "    brew install ffmpeg\n\n"
            f"详细信息：\n{ffmpeg_error}",
        )

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
