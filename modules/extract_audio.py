"""
modules/extract_audio.py

功能1：视频提取音频

支持格式：mp4 / mov / mkv
将视频中的音轨提取为同名 .m4a 文件，输出到原视频所在目录。
优先使用无损提取（copy 编码，不重新编码音频流）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional

from utils.ffmpeg_utils import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_media_info,
    run_command,
)

logger = logging.getLogger("SmartShortsToolkit.extract_audio")

# 支持的视频格式后缀
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


class ExtractAudioError(Exception):
    """音频提取过程中发生的业务异常。"""


def is_supported_video(file_path: Path) -> bool:
    """判断文件是否为支持的视频格式。"""
    return file_path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def extract_audio_from_video(video_path: Path, output_dir: Optional[Path] = None) -> Path:
    """
    从单个视频文件中提取音频，输出为同名 .m4a 文件。

    提取策略：
        1. 优先尝试 `-c:a copy`（无损直接拷贝音轨，速度快、不损失质量）
        2. 如果源音轨编码不适合直接封装为 m4a（copy 失败），
           回退为 AAC 256k 高质量重新编码

    Args:
        video_path: 输入视频文件路径
        output_dir: 输出目录，默认为视频所在目录（与需求一致）

    Raises:
        ExtractAudioError: 文件不存在、格式不支持或没有音轨
        FFmpegNotFoundError: 未找到 ffmpeg
        FFmpegExecutionError: ffmpeg 执行失败（copy 与重新编码均失败）

    Returns:
        生成的 .m4a 文件路径
    """
    if not video_path.exists():
        raise ExtractAudioError(f"文件不存在: {video_path}")

    if not is_supported_video(video_path):
        raise ExtractAudioError(
            f"不支持的视频格式: {video_path.suffix}，仅支持 mp4 / mov / mkv"
        )

    # 检查是否存在音频流
    info = get_media_info(video_path)
    if not info.has_audio:
        raise ExtractAudioError(f"视频文件不包含音频轨道: {video_path.name}")

    target_dir = output_dir if output_dir is not None else video_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{video_path.stem}.m4a"

    ffmpeg = get_ffmpeg_path()

    # 第一步：尝试无损拷贝音轨
    copy_cmd = [
        ffmpeg,
        "-y",
        "-i", str(video_path),
        "-vn",                 # 忽略视频流
        "-c:a", "copy",        # 音频流原始拷贝（无损）
        str(output_path),
    ]

    try:
        run_command(copy_cmd, description=f"无损提取音频: {video_path.name}")
        logger.info("无损提取音频成功: %s -> %s", video_path.name, output_path.name)
        return output_path
    except FFmpegExecutionError as exc:
        logger.warning(
            "无损提取失败，尝试重新编码为 AAC: %s\n原因: %s", video_path.name, exc
        )

    # 第二步：回退为重新编码 AAC（高质量 256kbps）
    reencode_cmd = [
        ffmpeg,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-c:a", "aac",
        "-b:a", "256k",
        str(output_path),
    ]

    try:
        run_command(reencode_cmd, description=f"重新编码提取音频: {video_path.name}")
        logger.info("重新编码提取音频成功: %s -> %s", video_path.name, output_path.name)
        return output_path
    except FFmpegExecutionError as exc:
        raise ExtractAudioError(
            f"提取音频失败（无损与重新编码均失败）: {video_path.name}\n{exc}"
        ) from exc


def batch_extract_audio(
    video_paths: List[Path],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[tuple[Path, Optional[Path], Optional[str]]]:
    """
    批量提取多个视频文件的音频。

    Args:
        video_paths: 视频文件路径列表
        progress_callback: 进度回调函数 (current_index, total, current_filename)

    Returns:
        结果列表，每项为 (输入路径, 输出路径或None, 错误信息或None)
    """
    results: List[tuple[Path, Optional[Path], Optional[str]]] = []
    total = len(video_paths)

    for idx, video_path in enumerate(video_paths, start=1):
        if progress_callback:
            progress_callback(idx, total, video_path.name)

        try:
            output_path = extract_audio_from_video(video_path)
            results.append((video_path, output_path, None))
        except (ExtractAudioError, FFmpegNotFoundError, FFmpegExecutionError) as exc:
            logger.error("提取音频失败: %s -> %s", video_path.name, exc)
            results.append((video_path, None, str(exc)))

    return results
