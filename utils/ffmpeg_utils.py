"""
utils/ffmpeg_utils.py

通用 FFmpeg / FFprobe 调用工具模块。
所有模块（提取音频、智能切割、合并音频、合并视频）均依赖此模块。

设计目标：
- 统一管理 ffmpeg / ffprobe 路径查找逻辑（兼容 Apple Silicon Homebrew 路径）
- 提供统一的子进程调用、日志记录、异常处理
- 提供静音检测、媒体信息查询等通用功能
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("SmartShortsToolkit.ffmpeg_utils")


class FFmpegNotFoundError(Exception):
    """当系统中找不到 ffmpeg 或 ffprobe 可执行文件时抛出。"""


class FFmpegExecutionError(Exception):
    """当 ffmpeg / ffprobe 子进程执行失败时抛出。"""


# 常见的 Apple Silicon / Intel Homebrew 安装路径，作为 PATH 查找的补充
_COMMON_BIN_DIRS = [
    "/opt/homebrew/bin",   # Apple Silicon Homebrew 默认路径
    "/usr/local/bin",      # Intel Homebrew 默认路径
    "/usr/bin",
]


def _find_binary(name: str) -> Optional[str]:
    """
    查找指定可执行文件（ffmpeg / ffprobe）的完整路径。

    查找顺序：
    1. 系统 PATH（shutil.which）
    2. 常见 Homebrew 安装目录

    Args:
        name: 可执行文件名，如 "ffmpeg" 或 "ffprobe"

    Returns:
        找到的完整路径，未找到则返回 None
    """
    # 优先使用系统 PATH
    found = shutil.which(name)
    if found:
        return found

    # 回退到常见安装目录
    for d in _COMMON_BIN_DIRS:
        candidate = Path(d) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return None


def get_ffmpeg_path() -> str:
    """
    获取 ffmpeg 可执行文件路径。

    Raises:
        FFmpegNotFoundError: 未找到 ffmpeg

    Returns:
        ffmpeg 可执行文件的完整路径
    """
    path = _find_binary("ffmpeg")
    if path is None:
        raise FFmpegNotFoundError(
            "未找到 ffmpeg。请先安装：\n"
            "  brew install ffmpeg\n"
            "并确保已在 PATH 中或位于 /opt/homebrew/bin。"
        )
    return path


def get_ffprobe_path() -> str:
    """
    获取 ffprobe 可执行文件路径。

    Raises:
        FFmpegNotFoundError: 未找到 ffprobe

    Returns:
        ffprobe 可执行文件的完整路径
    """
    path = _find_binary("ffprobe")
    if path is None:
        raise FFmpegNotFoundError(
            "未找到 ffprobe。请先安装：\n"
            "  brew install ffmpeg\n"
            "并确保已在 PATH 中或位于 /opt/homebrew/bin。"
        )
    return path


def run_command(cmd: List[str], description: str = "") -> subprocess.CompletedProcess:
    """
    执行子进程命令，统一日志与异常处理。

    Args:
        cmd: 命令参数列表
        description: 用于日志记录的命令描述

    Raises:
        FFmpegExecutionError: 命令执行返回非 0 状态码

    Returns:
        subprocess.CompletedProcess 对象
    """
    logger.info("执行命令 [%s]: %s", description or "FFmpeg/FFprobe", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise FFmpegExecutionError(f"命令未找到: {cmd[0]}") from exc
    except Exception as exc:  # noqa: BLE001
        raise FFmpegExecutionError(f"命令执行异常: {exc}") from exc

    if result.returncode != 0:
        logger.error(
            "命令执行失败 (returncode=%s)\nSTDOUT:\n%s\nSTDERR:\n%s",
            result.returncode,
            result.stdout,
            result.stderr,
        )
        raise FFmpegExecutionError(
            f"{description or '命令'} 执行失败 (returncode={result.returncode}):\n"
            f"{result.stderr.strip()[-2000:]}"
        )

    return result


@dataclass
class MediaInfo:
    """媒体文件基本信息。"""

    duration: float          # 时长（秒）
    has_video: bool          # 是否包含视频流
    has_audio: bool          # 是否包含音频流
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[str] = None
    sample_rate: Optional[str] = None
    channels: Optional[int] = None


def get_media_info(file_path: Path) -> MediaInfo:
    """
    使用 ffprobe 获取媒体文件信息（时长、编码、分辨率等）。

    Args:
        file_path: 媒体文件路径

    Raises:
        FFmpegExecutionError: ffprobe 执行失败
        FFmpegNotFoundError: 未找到 ffprobe

    Returns:
        MediaInfo 数据对象
    """
    ffprobe = get_ffprobe_path()

    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-show_streams",
        "-of", "json",
        str(file_path),
    ]
    result = run_command(cmd, description=f"获取媒体信息: {file_path.name}")

    import json

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegExecutionError(f"解析 ffprobe 输出失败: {exc}") from exc

    duration = 0.0
    fmt = data.get("format", {})
    if "duration" in fmt:
        try:
            duration = float(fmt["duration"])
        except (TypeError, ValueError):
            duration = 0.0

    has_video = False
    has_audio = False
    video_codec = None
    audio_codec = None
    width = None
    height = None
    fps = None
    sample_rate = None
    channels = None

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            has_video = True
            video_codec = stream.get("codec_name")
            width = stream.get("width")
            height = stream.get("height")
            fps = stream.get("r_frame_rate")
            # 视频流的 duration 有时比 format.duration 更准确
            if duration == 0.0 and "duration" in stream:
                try:
                    duration = float(stream["duration"])
                except (TypeError, ValueError):
                    pass
        elif codec_type == "audio":
            has_audio = True
            audio_codec = stream.get("codec_name")
            sample_rate = stream.get("sample_rate")
            channels = stream.get("channels")
            if duration == 0.0 and "duration" in stream:
                try:
                    duration = float(stream["duration"])
                except (TypeError, ValueError):
                    pass

    return MediaInfo(
        duration=duration,
        has_video=has_video,
        has_audio=has_audio,
        video_codec=video_codec,
        audio_codec=audio_codec,
        width=width,
        height=height,
        fps=fps,
        sample_rate=sample_rate,
        channels=channels,
    )


@dataclass
class SilencePeriod:
    """静音区间。"""

    start: float
    end: float

    @property
    def midpoint(self) -> float:
        """静音区间中点，作为切割点更安全（避免切到音头/音尾）。"""
        return (self.start + self.end) / 2.0


def detect_silences(
    file_path: Path,
    noise_db: float = -30.0,
    min_silence_duration: float = 0.3,
) -> List[SilencePeriod]:
    """
    使用 FFmpeg 的 silencedetect 滤镜检测音频中的静音区间。

    Args:
        file_path: 音频文件路径
        noise_db: 静音判定阈值（单位 dB，默认 -30dB）
        min_silence_duration: 最小静音持续时间（秒），默认 0.3 秒

    Raises:
        FFmpegExecutionError: ffmpeg 执行失败
        FFmpegNotFoundError: 未找到 ffmpeg

    Returns:
        SilencePeriod 列表，按时间顺序排列
    """
    ffmpeg = get_ffmpeg_path()

    cmd = [
        ffmpeg,
        "-i", str(file_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_duration}",
        "-f", "null",
        "-",
    ]

    logger.info("检测静音区间: %s", file_path.name)
    # silencedetect 的结果输出在 stderr 中，不能用 run_command 的非 0 校验
    # （此命令本身 returncode 通常为 0，但保险起见手动调用）
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise FFmpegExecutionError(f"命令未找到: {cmd[0]}") from exc
    except Exception as exc:  # noqa: BLE001
        raise FFmpegExecutionError(f"静音检测异常: {exc}") from exc

    stderr_text = result.stderr or ""

    # 解析形如:
    # [silencedetect @ 0x...] silence_start: 12.345
    # [silencedetect @ 0x...] silence_end: 14.567 | silence_duration: 2.222
    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", stderr_text)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", stderr_text)]

    periods: List[SilencePeriod] = []
    for i in range(min(len(starts), len(ends))):
        periods.append(SilencePeriod(start=starts[i], end=ends[i]))

    logger.info("共检测到 %d 个静音区间", len(periods))
    return periods


def ensure_output_dir(path: Path) -> None:
    """确保目录存在，不存在则创建。"""
    path.mkdir(parents=True, exist_ok=True)
