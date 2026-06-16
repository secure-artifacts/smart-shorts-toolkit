"""
ui/main_window.py

Smart Shorts Toolkit 主窗口。

界面布局：
    - 标题
    - 拖拽区域（支持拖入文件，自动识别类型）
    - 状态显示区域（日志/进度文本）
    - 进度条
    - 四个功能按钮：提取音频 / 智能切割(59秒) / 合并音频 / 合并视频

拖拽自动识别规则：
    - 单个视频文件 -> 提取音频
    - 单个音频文件 -> 智能切割
    - 多个音频文件 -> 合并音频
    - 多个视频文件 -> 合并视频
    - 混合类型 / 数量不符 -> 提示错误

所有耗时操作（FFmpeg 调用）均在 QThread 工作线程中执行，避免阻塞 UI。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modules.extract_audio import batch_extract_audio, is_supported_video as is_video_for_extract
from modules.merge_audio import is_supported_audio as is_audio_for_merge, merge_audio_files
from modules.merge_video import is_supported_video as is_video_for_merge, merge_video_files
from modules.split_audio import batch_split_audio, is_supported_audio as is_audio_for_split
from utils.ffmpeg_utils import FFmpegExecutionError, FFmpegNotFoundError

logger = logging.getLogger("SmartShortsToolkit.main_window")


# ---------------------------------------------------------------------------
# 工作线程：在后台执行 FFmpeg 相关任务，避免阻塞主界面
# ---------------------------------------------------------------------------

class WorkerThread(QThread):
    """
    通用后台工作线程。

    Signals:
        progress_signal: (current, total, message) 进度更新
        finished_signal: (success, summary_message) 任务完成
        log_signal: (message) 日志输出
    """

    progress_signal = Signal(int, int, str)
    finished_signal = Signal(bool, str)
    log_signal = Signal(str)

    def __init__(self, task_type: str, files: List[Path]):
        """
        Args:
            task_type: 任务类型，取值之一：
                "extract_audio" / "split_audio" / "merge_audio" / "merge_video"
            files: 输入文件路径列表
        """
        super().__init__()
        self.task_type = task_type
        self.files = files

    def run(self) -> None:  # noqa: C901 - 任务分发逻辑相对集中，保持单方法便于阅读
        try:
            if self.task_type == "extract_audio":
                self._run_extract_audio()
            elif self.task_type == "split_audio":
                self._run_split_audio()
            elif self.task_type == "merge_audio":
                self._run_merge_audio()
            elif self.task_type == "merge_video":
                self._run_merge_video()
            else:
                self.finished_signal.emit(False, f"未知任务类型: {self.task_type}")
        except (FFmpegNotFoundError, FFmpegExecutionError) as exc:
            logger.exception("任务执行失败")
            self.finished_signal.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - 兜底捕获，避免线程崩溃无提示
            logger.exception("任务执行出现未预期异常")
            self.finished_signal.emit(False, f"发生未预期错误: {exc}")

    # -- 提取音频 ------------------------------------------------------

    def _run_extract_audio(self) -> None:
        def progress_cb(current: int, total: int, name: str) -> None:
            self.progress_signal.emit(current, total, f"正在提取音频: {name} ({current}/{total})")
            self.log_signal.emit(f"[提取音频] 开始处理: {name}")

        results = batch_extract_audio(self.files, progress_callback=progress_cb)

        success_count = 0
        error_lines: List[str] = []
        for input_path, output_path, error in results:
            if output_path is not None:
                success_count += 1
                self.log_signal.emit(f"  ✅ {input_path.name} -> {output_path.name}")
            else:
                error_lines.append(f"  ❌ {input_path.name}: {error}")
                self.log_signal.emit(f"  ❌ {input_path.name}: {error}")

        total = len(results)
        if success_count == total:
            self.finished_signal.emit(
                True, f"提取音频完成：成功 {success_count}/{total} 个文件。"
            )
        else:
            summary = (
                f"提取音频完成：成功 {success_count}/{total}，"
                f"失败 {total - success_count} 个。\n" + "\n".join(error_lines)
            )
            self.finished_signal.emit(success_count > 0, summary)

    # -- 智能切割 ------------------------------------------------------

    def _run_split_audio(self) -> None:
        def progress_cb(current: int, total: int, name: str) -> None:
            self.progress_signal.emit(current, total, f"正在切割: {name} ({current}/{total})")
            self.log_signal.emit(f"[智能切割] 开始处理: {name}")

        results = batch_split_audio(self.files, progress_callback=progress_cb)

        success_count = 0
        error_lines: List[str] = []
        total_segments = 0
        for input_path, output_paths, error in results:
            if output_paths is not None:
                success_count += 1
                total_segments += len(output_paths)
                self.log_signal.emit(
                    f"  ✅ {input_path.name} -> 生成 {len(output_paths)} 个片段，"
                    f"输出目录: {output_paths[0].parent}"
                )
                for op in output_paths:
                    self.log_signal.emit(f"      - {op.name}")
            else:
                error_lines.append(f"  ❌ {input_path.name}: {error}")
                self.log_signal.emit(f"  ❌ {input_path.name}: {error}")

        total = len(results)
        if success_count == total:
            self.finished_signal.emit(
                True,
                f"智能切割完成：成功 {success_count}/{total} 个文件，"
                f"共生成 {total_segments} 个片段。",
            )
        else:
            summary = (
                f"智能切割完成：成功 {success_count}/{total}，"
                f"失败 {total - success_count} 个。\n" + "\n".join(error_lines)
            )
            self.finished_signal.emit(success_count > 0, summary)

    # -- 合并音频 ------------------------------------------------------

    def _run_merge_audio(self) -> None:
        self.progress_signal.emit(0, 1, f"正在合并 {len(self.files)} 个音频文件...")
        self.log_signal.emit(f"[合并音频] 开始合并 {len(self.files)} 个文件")
        for f in self.files:
            self.log_signal.emit(f"  - {f.name}")

        output_path = merge_audio_files(self.files)

        self.progress_signal.emit(1, 1, "合并完成")
        self.log_signal.emit(f"  ✅ 合并成功 -> {output_path}")
        self.finished_signal.emit(True, f"合并音频完成，输出文件: {output_path}")

    # -- 合并视频 ------------------------------------------------------

    def _run_merge_video(self) -> None:
        self.progress_signal.emit(0, 1, f"正在合并 {len(self.files)} 个视频文件...")
        self.log_signal.emit(f"[合并视频] 开始合并 {len(self.files)} 个文件")
        for f in self.files:
            self.log_signal.emit(f"  - {f.name}")

        output_path = merge_video_files(self.files)

        self.progress_signal.emit(1, 1, "合并完成")
        self.log_signal.emit(f"  ✅ 合并成功 -> {output_path}")
        self.finished_signal.emit(True, f"合并视频完成，输出文件: {output_path}")


# ---------------------------------------------------------------------------
# 拖拽区域控件
# ---------------------------------------------------------------------------

class DropArea(QFrame):
    """
    支持拖拽文件的区域控件。

    Signals:
        files_dropped: List[Path] - 用户拖入的文件路径列表
    """

    files_dropped = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("DropArea")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel("📂")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_font = QFont()
        icon_font.setPointSize(36)
        self.icon_label.setFont(icon_font)

        self.text_label = QLabel("将视频或音频文件拖拽到此处")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.sub_label = QLabel(
            "单个视频 → 提取音频   |   单个音频 → 智能切割\n"
            "多个音频 → 合并音频   |   多个视频 → 合并视频"
        )
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setObjectName("SubLabel")

        layout.addWidget(self.icon_label)
        layout.addWidget(self.text_label)
        layout.addWidget(self.sub_label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("DropAreaActive")
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001
        self.setObjectName("DropArea")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setObjectName("DropArea")
        self.style().unpolish(self)
        self.style().polish(self)

        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Smart Shorts Toolkit 主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Shorts Toolkit")
        self.resize(720, 600)
        self.setMinimumSize(640, 520)

        self._current_files: List[Path] = []
        self._worker: Optional[WorkerThread] = None

        self._build_ui()
        self._apply_styles()

    # -- UI 构建 --------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 标题
        title_label = QLabel("Smart Shorts Toolkit")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        subtitle_label = QLabel("YouTube Shorts 音视频处理工具")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setObjectName("SubtitleLabel")
        main_layout.addWidget(subtitle_label)

        # 拖拽区域
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self._on_files_dropped)
        main_layout.addWidget(self.drop_area)

        # 当前选中文件提示
        self.selected_files_label = QLabel("未选择文件")
        self.selected_files_label.setObjectName("SelectedFilesLabel")
        self.selected_files_label.setWordWrap(True)
        main_layout.addWidget(self.selected_files_label)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.btn_extract = QPushButton("提取音频")
        self.btn_split = QPushButton("智能切割（59秒）")
        self.btn_merge_audio = QPushButton("合并音频")
        self.btn_merge_video = QPushButton("合并视频")

        for btn in (self.btn_extract, self.btn_split, self.btn_merge_audio, self.btn_merge_video):
            btn.setMinimumHeight(40)
            button_layout.addWidget(btn)

        self.btn_extract.clicked.connect(self._on_extract_audio_clicked)
        self.btn_split.clicked.connect(self._on_split_audio_clicked)
        self.btn_merge_audio.clicked.connect(self._on_merge_audio_clicked)
        self.btn_merge_video.clicked.connect(self._on_merge_video_clicked)

        main_layout.addLayout(button_layout)

        # 手动选择文件按钮
        self.btn_choose_files = QPushButton("或点击此处选择文件...")
        self.btn_choose_files.clicked.connect(self._on_choose_files_clicked)
        main_layout.addWidget(self.btn_choose_files)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        main_layout.addWidget(self.progress_bar)

        # 状态显示区域（日志）
        status_label = QLabel("状态信息")
        status_label.setObjectName("StatusTitleLabel")
        main_layout.addWidget(status_label)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setObjectName("StatusText")
        main_layout.addWidget(self.status_text, stretch=1)

        self._log("欢迎使用 Smart Shorts Toolkit！请拖入文件或点击按钮选择文件。")

    def _apply_styles(self) -> None:
        """应用自定义样式，兼容浅色/深色模式。"""
        self.setStyleSheet(
            """
            QLabel#SubtitleLabel {
                color: palette(mid);
                font-size: 12px;
            }
            QLabel#SubLabel {
                color: palette(mid);
                font-size: 11px;
            }
            QLabel#SelectedFilesLabel {
                color: palette(text);
                font-size: 12px;
                padding: 4px;
            }
            QLabel#StatusTitleLabel {
                font-weight: bold;
            }
            QFrame#DropArea {
                border: 2px dashed palette(mid);
                border-radius: 10px;
                background-color: palette(base);
            }
            QFrame#DropAreaActive {
                border: 2px dashed palette(highlight);
                border-radius: 10px;
                background-color: palette(alternate-base);
            }
            QTextEdit#StatusText {
                font-family: -apple-system, Menlo, monospace;
                font-size: 12px;
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            QPushButton {
                padding: 8px 12px;
                border-radius: 6px;
                font-weight: 500;
            }
            """
        )

    # -- 日志与状态 -------------------------------------------------------

    def _log(self, message: str) -> None:
        """向状态区域追加一条日志信息，并写入应用日志。"""
        self.status_text.append(message)
        logger.info(message)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for btn in (
            self.btn_extract,
            self.btn_split,
            self.btn_merge_audio,
            self.btn_merge_video,
            self.btn_choose_files,
        ):
            btn.setEnabled(enabled)

    # -- 文件选择 ---------------------------------------------------------

    def _on_files_dropped(self, paths: List[Path]) -> None:
        """处理拖拽文件，自动识别类型并执行对应操作。"""
        self._current_files = paths
        self._update_selected_files_label()

        video_exts_extract = {".mp4", ".mov", ".mkv"}
        video_exts_merge = {".mp4", ".mov"}
        audio_exts_split = {".mp3", ".m4a", ".wav", ".aac", ".flac"}
        audio_exts_merge = {".mp3", ".m4a", ".wav"}

        is_all_video = all(p.suffix.lower() in video_exts_extract for p in paths)
        is_all_audio = all(p.suffix.lower() in audio_exts_split for p in paths)

        if len(paths) == 1:
            single = paths[0]
            if single.suffix.lower() in video_exts_extract:
                self._log(f"检测到单个视频文件: {single.name} -> 自动执行【提取音频】")
                self._start_task("extract_audio", [single])
                return
            if single.suffix.lower() in audio_exts_split:
                self._log(f"检测到单个音频文件: {single.name} -> 自动执行【智能切割】")
                self._start_task("split_audio", [single])
                return
            self._show_error(f"不支持的文件格式: {single.suffix}")
            return

        # 多文件
        if is_all_audio and all(p.suffix.lower() in audio_exts_merge for p in paths):
            self._log(f"检测到 {len(paths)} 个音频文件 -> 自动执行【合并音频】")
            self._start_task("merge_audio", paths)
            return

        if is_all_video and all(p.suffix.lower() in video_exts_merge for p in paths):
            self._log(f"检测到 {len(paths)} 个视频文件 -> 自动执行【合并视频】")
            self._start_task("merge_video", paths)
            return

        self._show_error(
            "无法识别拖入的文件组合。\n"
            "请确保：\n"
            "  - 单个视频文件 (mp4/mov/mkv) -> 提取音频\n"
            "  - 单个音频文件 (mp3/m4a/wav/aac/flac) -> 智能切割\n"
            "  - 多个音频文件 (mp3/m4a/wav) -> 合并音频\n"
            "  - 多个视频文件 (mp4/mov) -> 合并视频"
        )

    def _update_selected_files_label(self) -> None:
        if not self._current_files:
            self.selected_files_label.setText("未选择文件")
            return
        names = "\n".join(f"  • {p.name}" for p in self._current_files)
        self.selected_files_label.setText(f"已选择 {len(self._current_files)} 个文件:\n{names}")

    def _on_choose_files_clicked(self) -> None:
        """打开文件选择对话框。"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择视频或音频文件",
            "",
            "媒体文件 (*.mp4 *.mov *.mkv *.mp3 *.m4a *.wav *.aac *.flac);;所有文件 (*)",
        )
        if files:
            paths = [Path(f) for f in files]
            self._current_files = paths
            self._update_selected_files_label()
            self._log(f"已选择 {len(paths)} 个文件，请点击对应功能按钮处理。")

    # -- 按钮点击事件 -------------------------------------------------------

    def _on_extract_audio_clicked(self) -> None:
        files = self._filter_files(is_video_for_extract, "支持的视频文件 (mp4/mov/mkv)")
        if not files:
            return
        self._start_task("extract_audio", files)

    def _on_split_audio_clicked(self) -> None:
        files = self._filter_files(is_audio_for_split, "支持的音频文件 (mp3/m4a/wav/aac/flac)")
        if not files:
            return
        self._start_task("split_audio", files)

    def _on_merge_audio_clicked(self) -> None:
        files = self._filter_files(is_audio_for_merge, "支持的音频文件 (mp3/m4a/wav)")
        if not files:
            return
        if len(files) < 2:
            self._show_error("合并音频至少需要选择 2 个文件。")
            return
        self._start_task("merge_audio", files)

    def _on_merge_video_clicked(self) -> None:
        files = self._filter_files(is_video_for_merge, "支持的视频文件 (mp4/mov)")
        if not files:
            return
        if len(files) < 2:
            self._show_error("合并视频至少需要选择 2 个文件。")
            return
        self._start_task("merge_video", files)

    def _filter_files(self, predicate, type_desc: str) -> Optional[List[Path]]:
        """根据当前选中的文件，按谓词过滤；若没有文件则提示用户先选择。"""
        if not self._current_files:
            self._show_error(f"请先拖入或选择文件（{type_desc}）。")
            return None

        valid = [p for p in self._current_files if predicate(p)]
        if not valid:
            self._show_error(f"当前选中的文件中没有{type_desc}。")
            return None

        invalid_count = len(self._current_files) - len(valid)
        if invalid_count > 0:
            self._log(f"提示：已忽略 {invalid_count} 个不符合格式的文件。")

        return valid

    # -- 任务调度 ---------------------------------------------------------

    def _start_task(self, task_type: str, files: List[Path]) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._show_error("当前有任务正在执行，请稍候再操作。")
            return

        self._set_buttons_enabled(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)

        task_names = {
            "extract_audio": "提取音频",
            "split_audio": "智能切割",
            "merge_audio": "合并音频",
            "merge_video": "合并视频",
        }
        self._log(f"--- 开始任务: {task_names.get(task_type, task_type)} ---")

        self._worker = WorkerThread(task_type, files)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.log_signal.connect(self._log)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, message: str) -> None:
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        self.statusBar().showMessage(message) if self.statusBar() else None

    def _on_finished(self, success: bool, message: str) -> None:
        self._set_buttons_enabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1 if success else 0)

        self._log(f"--- 任务结束 ---\n{message}\n")

        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "处理失败", message)

        self._worker = None

    # -- 错误提示 ---------------------------------------------------------

    def _show_error(self, message: str) -> None:
        self._log(f"⚠️ {message}")
        QMessageBox.warning(self, "提示", message)
