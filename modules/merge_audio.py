"""
modules/merge_audio.py

功能3：合并音频

支持格式：mp3 / m4a / wav
将多个音频文件按顺序合并为一个文件 merged.mp3，
输出到第一个文件所在目录。

实现方式：
    - 优先使用 FFmpeg concat demuxer（无损拼接，要求相同编码参数）
    - 如果 concat demuxer 失败（编码参数不一致），
      回退为 filter_complex concat（重新编码）
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

from utils.ffmpeg_utils import (
    FFmpegExecutionError,
    get_ffmpeg_path,
    run_command,
)

logger = logging.getLogger("SmartShortsToolkit.merge_audio")

# 支持的音频格式后缀
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav"}


class MergeAudioError(Exception):
    """音频合并过程中发生的业务异常。"""


def is_supported_audio(file_path: Path) -> bool:
    """判断文件是否为支持合并的音频格式。"""
    return file_path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def _escape_concat_path(path: Path) -> str:
    """
    为 FFmpeg concat demuxer 列表文件转义路径中的单引号。

    concat 文件格式示例：
        file '/path/to/a.mp3'
        file '/path/to/b.mp3'
    """
    # ffmpeg concat 列表中，单引号需要替换为 '\''
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'"


def merge_audio_files(audio_paths: List[Path], output_dir: Optional[Path] = None) -> Path:
    """
    合并多个音频文件为一个 merged.mp3 文件。

    Args:
        audio_paths: 待合并的音频文件路径列表（按合并顺序排列）
        output_dir: 输出目录，默认为第一个文件所在目录

    Raises:
        MergeAudioError: 文件数量不足、文件不存在、格式不支持
        FFmpegExecutionError: ffmpeg 执行失败（concat 与重新编码均失败）

    Returns:
        合并后生成的文件路径 (merged.mp3)
    """
    if len(audio_paths) < 2:
        raise MergeAudioError("合并音频至少需要 2 个文件")

    for p in audio_paths:
        if not p.exists():
            raise MergeAudioError(f"文件不存在: {p}")
        if not is_supported_audio(p):
            raise MergeAudioError(
                f"不支持的音频格式: {p.suffix}，仅支持 mp3/m4a/wav"
            )

    target_dir = output_dir if output_dir is not None else audio_paths[0].parent
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / "merged.mp3"

    # 如果输出文件已存在，避免覆盖造成混淆，自动追加序号
    counter = 1
    while output_path.exists():
        output_path = target_dir / f"merged_{counter}.mp3"
        counter += 1

    ffmpeg = get_ffmpeg_path()

    # 第一步：尝试使用 concat demuxer 无损拼接
    # 创建临时 concat 列表文件
    list_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            for p in audio_paths:
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
            run_command(concat_cmd, description="无损拼接音频（concat demuxer）")
            logger.info("无损合并音频成功 -> %s", output_path.name)
            return output_path
        except FFmpegExecutionError as exc:
            logger.warning(
                "concat demuxer 拼接失败，可能编码参数不一致，回退为重新编码: %s", exc
            )
    finally:
        if list_file and list_file.exists():
            list_file.unlink(missing_ok=True)

    # 第二步：回退方案 - 使用 filter_complex concat 重新编码为 MP3
    input_args: List[str] = []
    for p in audio_paths:
        input_args += ["-i", str(p)]

    # 构造 filter_complex concat 表达式
    # 例如: [0:a][1:a][2:a]concat=n=3:v=0:a=1[outa]
    n = len(audio_paths)
    stream_refs = "".join(f"[{i}:a]" for i in range(n))
    filter_complex = f"{stream_refs}concat=n={n}:v=0:a=1[outa]"

    reencode_cmd = (
        [ffmpeg, "-y"]
        + input_args
        + [
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-c:a", "libmp3lame",
            "-q:a", "2",  # 高质量 VBR
            str(output_path),
        ]
    )

    try:
        run_command(reencode_cmd, description="重新编码合并音频（filter_complex concat）")
        logger.info("重新编码合并音频成功 -> %s", output_path.name)
        return output_path
    except FFmpegExecutionError as exc:
        raise MergeAudioError(f"合并音频失败（concat 与重新编码均失败）:\n{exc}") from exc
