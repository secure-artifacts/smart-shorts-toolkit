"""
modules/merge_video.py

功能4：合并视频

支持格式：mp4 / mov
将多个视频文件按顺序合并为一个 merged.mp4 文件，
输出到第一个文件所在目录。

实现策略：
    1. 检查所有输入视频的关键参数（编码格式、分辨率、帧率、采样率等）是否一致
    2. 若一致 -> 使用 concat demuxer 进行无损拼接（-c copy）
    3. 若不一致 -> 使用 filter_complex concat 重新编码
       （统一编码为 H.264 + AAC，分辨率以第一个视频为基准）
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

from utils.ffmpeg_utils import (
    FFmpegExecutionError,
    MediaInfo,
    get_ffmpeg_path,
    get_media_info,
    run_command,
)

logger = logging.getLogger("SmartShortsToolkit.merge_video")

# 支持的视频格式后缀
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov"}


class MergeVideoError(Exception):
    """视频合并过程中发生的业务异常。"""


def is_supported_video(file_path: Path) -> bool:
    """判断文件是否为支持合并的视频格式。"""
    return file_path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def _escape_concat_path(path: Path) -> str:
    """为 FFmpeg concat demuxer 列表文件转义路径中的单引号。"""
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'"


def _params_consistent(infos: List[MediaInfo]) -> bool:
    """
    判断多个视频的关键参数是否一致，决定是否可以使用无损 concat。

    比较项：视频编码格式、音频编码格式、分辨率、帧率、采样率
    """
    if not infos:
        return False

    first = infos[0]
    for info in infos[1:]:
        if info.video_codec != first.video_codec:
            return False
        if info.audio_codec != first.audio_codec:
            return False
        if info.width != first.width or info.height != first.height:
            return False
        if info.fps != first.fps:
            return False
        if info.sample_rate != first.sample_rate:
            return False
    return True


def merge_video_files(video_paths: List[Path], output_dir: Optional[Path] = None) -> Path:
    """
    合并多个视频文件为一个 merged.mp4 文件。

    Args:
        video_paths: 待合并的视频文件路径列表（按合并顺序排列）
        output_dir: 输出目录，默认为第一个文件所在目录

    Raises:
        MergeVideoError: 文件数量不足、文件不存在、格式不支持
        FFmpegExecutionError: ffmpeg 执行失败

    Returns:
        合并后生成的文件路径 (merged.mp4)
    """
    if len(video_paths) < 2:
        raise MergeVideoError("合并视频至少需要 2 个文件")

    for p in video_paths:
        if not p.exists():
            raise MergeVideoError(f"文件不存在: {p}")
        if not is_supported_video(p):
            raise MergeVideoError(
                f"不支持的视频格式: {p.suffix}，仅支持 mp4/mov"
            )

    target_dir = output_dir if output_dir is not None else video_paths[0].parent
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / "merged.mp4"

    # 避免覆盖已存在的输出文件
    counter = 1
    while output_path.exists():
        output_path = target_dir / f"merged_{counter}.mp4"
        counter += 1

    ffmpeg = get_ffmpeg_path()

    # 获取所有视频的媒体信息，用于判断是否参数一致
    infos: List[MediaInfo] = []
    for p in video_paths:
        try:
            infos.append(get_media_info(p))
        except FFmpegExecutionError as exc:
            raise MergeVideoError(f"无法读取视频信息: {p.name}\n{exc}") from exc

    use_lossless = _params_consistent(infos)

    if use_lossless:
        logger.info("检测到所有视频参数一致，使用无损 concat 拼接")
        list_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                for p in video_paths:
                    f.write(_escape_concat_path(p) + "\n")
                list_file = Path(f.name)

            concat_cmd = [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(output_path),
            ]

            try:
                run_command(concat_cmd, description="无损拼接视频（concat demuxer）")
                logger.info("无损合并视频成功 -> %s", output_path.name)
                return output_path
            except FFmpegExecutionError as exc:
                logger.warning(
                    "无损 concat 拼接失败，回退为重新编码: %s", exc
                )
        finally:
            if list_file and list_file.exists():
                list_file.unlink(missing_ok=True)

    # 参数不一致或无损拼接失败 -> 重新编码（filter_complex concat）
    logger.info("视频参数不一致或无损拼接失败，使用重新编码方式合并")

    # 以第一个视频的分辨率作为标准输出分辨率
    target_width = infos[0].width or 1080
    target_height = infos[0].height or 1920

    input_args: List[str] = []
    for p in video_paths:
        input_args += ["-i", str(p)]

    # 为每个输入流构建 scale + setsar 滤镜，统一分辨率，避免拼接报错
    filter_parts: List[str] = []
    concat_refs = ""
    n = len(video_paths)
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={target_width}:{target_height}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1[v{i}]"
        )
        concat_refs += f"[v{i}][{i}:a]"

    filter_parts.append(f"{concat_refs}concat=n={n}:v=1:a=1[outv][outa]")
    filter_complex = ";".join(filter_parts)

    reencode_cmd = (
        [ffmpeg, "-y"]
        + input_args
        + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "256k",
            str(output_path),
        ]
    )

    try:
        run_command(reencode_cmd, description="重新编码合并视频（filter_complex concat）")
        logger.info("重新编码合并视频成功 -> %s", output_path.name)
        return output_path
    except FFmpegExecutionError as exc:
        raise MergeVideoError(f"合并视频失败（无损与重新编码均失败）:\n{exc}") from exc
