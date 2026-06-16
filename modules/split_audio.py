"""
modules/split_audio.py

功能2：智能音频切割（核心功能）

支持格式：mp3 / m4a / wav / aac / flac

目标：
    将长音频自动切割为多个适合 YouTube Shorts 使用的片段。

切割规则：
    - 目标长度: 58 秒
    - 最大长度: 59 秒
    - 最短长度: 45 秒（最后一段允许例外，见下方说明）

切割逻辑（针对每一段，从当前游标位置 cursor 开始）：
    1. 在 [cursor+45, cursor+59] 范围内查找静音区间
    2. 如果找到多个静音区间，选择其中点最接近 cursor+58 的那个，
       作为本段的切割点
    3. 如果没有找到任何静音区间，则在 cursor+59 处强制切割
    4. 重复，直到剩余音频时长 <= 59 秒，将其作为最后一段输出

边界处理：
    - 若剩余音频本身 < 45 秒（整段音频小于45秒，或最后剩余片段),
      仍作为最后一段单独输出（不强行合并，避免产生空文件或异常）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from utils.ffmpeg_utils import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    SilencePeriod,
    detect_silences,
    get_ffmpeg_path,
    get_media_info,
    run_command,
)

logger = logging.getLogger("SmartShortsToolkit.split_audio")

# 支持的音频格式后缀
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac"}

# 切割时长参数（秒）
TARGET_LENGTH = 58.0
MAX_LENGTH = 59.0
MIN_LENGTH = 45.0

# 静音检测参数
SILENCE_NOISE_DB = -30.0
SILENCE_MIN_DURATION = 0.3


class SplitAudioError(Exception):
    """音频切割过程中发生的业务异常。"""


@dataclass
class SplitSegment:
    """切割片段信息。"""

    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def is_supported_audio(file_path: Path) -> bool:
    """判断文件是否为支持的音频格式。"""
    return file_path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _select_cut_point(
    cursor: float,
    total_duration: float,
    silences: List[SilencePeriod],
) -> float:
    """
    为当前片段选择最佳切割点。

    Args:
        cursor: 当前片段起始时间（秒）
        total_duration: 整个音频总时长（秒）
        silences: 整个音频的静音区间列表

    Returns:
        切割点时间（绝对时间，秒）
    """
    window_min = cursor + MIN_LENGTH
    window_max = cursor + MAX_LENGTH
    target = cursor + TARGET_LENGTH

    # 收窄搜索窗口，不超过音频总长
    window_max = min(window_max, total_duration)
    window_min = min(window_min, total_duration)

    candidates: List[float] = []
    for sp in silences:
        midpoint = sp.midpoint
        # 静音区间的中点落在 [window_min, window_max] 范围内才视为候选
        if window_min <= midpoint <= window_max:
            candidates.append(midpoint)

    if candidates:
        # 选择最接近目标长度(58秒)的静音中点
        best = min(candidates, key=lambda t: abs(t - target))
        logger.debug(
            "cursor=%.2f -> 选择静音切割点 %.2f (目标 %.2f)", cursor, best, target
        )
        return best

    # 未找到合适的静音点，强制在 59 秒处切割（不超过总时长）
    forced = min(cursor + MAX_LENGTH, total_duration)
    logger.debug("cursor=%.2f -> 未找到静音点，强制切割于 %.2f", cursor, forced)
    return forced


def plan_segments(total_duration: float, silences: List[SilencePeriod]) -> List[SplitSegment]:
    """
    根据总时长与静音区间列表，规划所有切割片段。

    Args:
        total_duration: 音频总时长（秒）
        silences: 静音区间列表

    Returns:
        SplitSegment 列表
    """
    segments: List[SplitSegment] = []
    cursor = 0.0
    index = 1

    if total_duration <= 0:
        return segments

    # 如果整段音频本身已经 <= 最大长度，直接整段输出
    if total_duration <= MAX_LENGTH:
        segments.append(SplitSegment(index=index, start=0.0, end=total_duration))
        return segments

    while True:
        remaining = total_duration - cursor

        # 剩余时长已经在允许范围内（<= 59秒），作为最后一段直接输出
        if remaining <= MAX_LENGTH:
            segments.append(SplitSegment(index=index, start=cursor, end=total_duration))
            break

        cut_point = _select_cut_point(cursor, total_duration, silences)

        # 安全保护：避免切割点未前进导致死循环
        if cut_point <= cursor + 0.01:
            cut_point = min(cursor + MAX_LENGTH, total_duration)

        segments.append(SplitSegment(index=index, start=cursor, end=cut_point))

        cursor = cut_point
        index += 1

        # 防御性退出：如果游标已到达或超过总时长
        if cursor >= total_duration - 0.01:
            break

    return segments


def split_audio_file(
    audio_path: Path,
    output_dir: Optional[Path] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Path]:
    """
    对单个音频文件执行智能切割。

    Args:
        audio_path: 输入音频文件路径
        output_dir: 输出目录，默认为
            "<原目录>/<原文件名(不含扩展名)>_shorts/"
        progress_callback: 进度回调 (current_segment_index, total_segments)

    Raises:
        SplitAudioError: 文件不存在、格式不支持、无法获取时长等业务错误
        FFmpegNotFoundError: 未找到 ffmpeg/ffprobe
        FFmpegExecutionError: ffmpeg 执行失败

    Returns:
        生成的音频片段文件路径列表（按顺序）
    """
    if not audio_path.exists():
        raise SplitAudioError(f"文件不存在: {audio_path}")

    if not is_supported_audio(audio_path):
        raise SplitAudioError(
            f"不支持的音频格式: {audio_path.suffix}，仅支持 mp3/m4a/wav/aac/flac"
        )

    info = get_media_info(audio_path)
    total_duration = info.duration
    if total_duration <= 0:
        raise SplitAudioError(f"无法获取音频时长或时长为0: {audio_path.name}")

    logger.info("音频 %s 总时长: %.2f 秒", audio_path.name, total_duration)

    # 检测静音区间（基于整个文件一次性检测，效率更高）
    try:
        silences = detect_silences(
            audio_path,
            noise_db=SILENCE_NOISE_DB,
            min_silence_duration=SILENCE_MIN_DURATION,
        )
    except (FFmpegExecutionError, FFmpegNotFoundError) as exc:
        logger.warning("静音检测失败，将全部使用强制切割: %s", exc)
        silences = []

    segments = plan_segments(total_duration, silences)
    if not segments:
        raise SplitAudioError(f"未能规划出任何切割片段: {audio_path.name}")

    logger.info("规划出 %d 个片段", len(segments))
    for seg in segments:
        logger.info(
            "  片段%d: %.2f -> %.2f (时长 %.2f 秒)",
            seg.index, seg.start, seg.end, seg.duration,
        )

    # 准备输出目录
    target_dir = (
        output_dir
        if output_dir is not None
        else audio_path.parent / f"{audio_path.stem}_shorts"
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_path()
    ext = audio_path.suffix.lower()
    output_paths: List[Path] = []
    total = len(segments)

    for seg in segments:
        output_name = f"{audio_path.stem}_part{seg.index:02d}{ext}"
        output_path = target_dir / output_name

        cmd = [
            ffmpeg,
            "-y",
            "-i", str(audio_path),
            "-ss", f"{seg.start:.3f}",
            "-to", f"{seg.end:.3f}",
        ]

        # 优先无损切割（copy），适用于大多数容器/编码组合
        copy_cmd = cmd + ["-c", "copy", str(output_path)]

        try:
            run_command(copy_cmd, description=f"切割片段{seg.index}（无损）")
        except FFmpegExecutionError as exc:
            logger.warning(
                "片段%d 无损切割失败，回退为重新编码: %s", seg.index, exc
            )
            # 回退方案：重新编码，针对不同格式选择合适的编码器
            reencode_cmd = list(cmd)
            if ext in (".mp3",):
                reencode_cmd += ["-c:a", "libmp3lame", "-q:a", "0"]
            elif ext in (".m4a", ".aac"):
                reencode_cmd += ["-c:a", "aac", "-b:a", "256k"]
            elif ext in (".flac",):
                reencode_cmd += ["-c:a", "flac"]
            else:  # wav 及其他
                reencode_cmd += ["-c:a", "pcm_s16le"]
            reencode_cmd.append(str(output_path))

            run_command(reencode_cmd, description=f"切割片段{seg.index}（重新编码）")

        output_paths.append(output_path)

        if progress_callback:
            progress_callback(seg.index, total)

    logger.info("切割完成，共生成 %d 个文件，输出目录: %s", len(output_paths), target_dir)
    return output_paths


def batch_split_audio(
    audio_paths: List[Path],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[tuple[Path, Optional[List[Path]], Optional[str]]]:
    """
    批量对多个音频文件执行智能切割。

    Args:
        audio_paths: 音频文件路径列表
        progress_callback: 进度回调 (current_file_index, total_files, current_filename)

    Returns:
        结果列表，每项为 (输入路径, 输出文件列表或None, 错误信息或None)
    """
    results: List[tuple[Path, Optional[List[Path]], Optional[str]]] = []
    total = len(audio_paths)

    for idx, audio_path in enumerate(audio_paths, start=1):
        if progress_callback:
            progress_callback(idx, total, audio_path.name)

        try:
            outputs = split_audio_file(audio_path)
            results.append((audio_path, outputs, None))
        except (SplitAudioError, FFmpegNotFoundError, FFmpegExecutionError) as exc:
            logger.error("切割失败: %s -> %s", audio_path.name, exc)
            results.append((audio_path, None, str(exc)))

    return results
