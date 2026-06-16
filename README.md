# Smart Shorts Toolkit (Mac版)

YouTube Shorts 创作者音视频处理工具，基于 Python 3.12 + PySide6 + FFmpeg 开发，
支持 Apple Silicon (M1/M2/M3/M4)，兼容 macOS Sonoma / Sequoia。

## 功能概览

| 功能 | 说明 |
| --- | --- |
| 提取音频 | 从 mp4/mov/mkv 视频中提取音轨，生成同名 `.m4a` 文件，优先无损 |
| 智能切割（59秒） | 将长音频按 58 秒目标长度、45~59 秒范围智能寻找静音点切割，适配 Shorts |
| 合并音频 | 将多个 mp3/m4a/wav 文件合并为 `merged.mp3` |
| 合并视频 | 将多个 mp4/mov 文件合并为 `merged.mp4`，参数一致时无损拼接，否则自动重新编码 |

## 项目结构

```
SmartShortsToolkit/
├── app.py                  # 应用入口
├── requirements.txt        # Python 依赖
├── build.sh                 # macOS 打包脚本
├── SmartShortsToolkit.spec  # PyInstaller 配置
├── modules/
│   ├── extract_audio.py     # 功能1：提取音频
│   ├── split_audio.py       # 功能2：智能音频切割
│   ├── merge_audio.py        # 功能3：合并音频
│   └── merge_video.py        # 功能4：合并视频
├── utils/
│   ├── ffmpeg_utils.py       # FFmpeg/FFprobe 调用与静音检测
│   └── logger.py             # 日志配置
├── ui/
│   └── main_window.py        # 主窗口与拖拽逻辑
└── assets/                    # 图标等资源文件
```

## 环境准备

### 1. 安装 Python 3.12+

推荐使用 Homebrew：

```bash
brew install python@3.12
```

### 2. 安装 FFmpeg

```bash
brew install ffmpeg
```

安装后确认：

```bash
ffmpeg -version
ffprobe -version
```

Apple Silicon 默认安装路径为 `/opt/homebrew/bin`，程序会自动查找该路径。

### 3. 安装 Python 依赖

```bash
cd SmartShortsToolkit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行（开发模式）

```bash
source .venv/bin/activate
python app.py
```

## 使用说明

### 拖拽自动识别

将文件拖入主窗口的拖拽区域，程序会根据文件类型和数量自动判断要执行的操作：

- **单个视频文件**（mp4/mov/mkv） → 自动执行【提取音频】
- **单个音频文件**（mp3/m4a/wav/aac/flac） → 自动执行【智能切割】
- **多个音频文件**（mp3/m4a/wav） → 自动执行【合并音频】
- **多个视频文件**（mp4/mov） → 自动执行【合并视频】

### 手动选择文件

点击"或点击此处选择文件..."按钮，通过系统文件选择对话框选择文件，
然后点击对应功能按钮（提取音频 / 智能切割 / 合并音频 / 合并视频）。

### 智能切割规则说明

- 目标长度：58 秒
- 最大长度：59 秒（硬限制，永不超过）
- 最短长度：45 秒
- 切割逻辑：在 [当前位置+45秒, 当前位置+59秒] 范围内查找静音区间，
  选择中点最接近"当前位置+58秒"的静音点作为切割点；
  若该范围内没有检测到静音，则在 59 秒处强制切割。
- 输出位置：`<原文件目录>/<原文件名>_shorts/`，文件名格式为
  `<原文件名>_part01.<ext>`、`<原文件名>_part02.<ext>` ...

### 输出位置说明

- 提取音频：输出到原视频所在目录，与原文件同名（`.m4a`）
- 智能切割：输出到 `<原目录>/<原文件名>_shorts/` 子目录
- 合并音频：输出到第一个文件所在目录，命名为 `merged.mp3`
  （如已存在则自动命名为 `merged_1.mp3` 等）
- 合并视频：输出到第一个文件所在目录，命名为 `merged.mp4`
  （如已存在则自动命名为 `merged_1.mp4` 等）

## 日志

应用运行日志保存在：

```
~/Library/Logs/SmartShortsToolkit/app.log
```

如遇问题可查看该文件辅助排查。

## 打包为 .app

详见下方"打包步骤"章节，或直接运行：

```bash
chmod +x build.sh
./build.sh
```

打包完成后，应用位于：

```
dist/Smart Shorts Toolkit.app
```

可直接双击运行，或拖拽到 `/Applications` 目录安装。

## 打包步骤详解

1. **确保依赖已安装**

   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **运行打包脚本**

   ```bash
   ./build.sh
   ```

   脚本会自动：
   - 创建/激活虚拟环境
   - 安装依赖
   - 检查 FFmpeg
   - 清理旧的 `build/` 和 `dist/` 目录
   - 调用 `pyinstaller SmartShortsToolkit.spec` 生成 `.app`

3. **手动打包（可选）**

   如果不使用 `build.sh`，也可以手动执行：

   ```bash
   pyinstaller SmartShortsToolkit.spec --noconfirm
   ```

4. **首次运行提示"无法打开，因为来自身份不明的开发者"**

   这是 macOS Gatekeeper 的安全限制。可通过以下方式之一解决：

   - 在 Finder 中右键点击 `Smart Shorts Toolkit.app` → 选择"打开" → 在弹出的提示中再次确认"打开"
   - 或在终端执行（仅本机临时移除限制）：

     ```bash
     xattr -cr "dist/Smart Shorts Toolkit.app"
     ```

5. **关于 FFmpeg 依赖**

   打包后的 `.app` 不包含 FFmpeg 二进制文件，运行时会在以下路径中查找：

   - 系统 `PATH`
   - `/opt/homebrew/bin`（Apple Silicon Homebrew）
   - `/usr/local/bin`（Intel Homebrew）
   - `/usr/bin`

   因此目标机器上必须安装 FFmpeg：

   ```bash
   brew install ffmpeg
   ```

## 常见问题

**Q: 提示"未检测到 FFmpeg"**

A: 请确认已通过 `brew install ffmpeg` 安装，并且 `ffmpeg`、`ffprobe`
   位于 `/opt/homebrew/bin`（Apple Silicon）或 `/usr/local/bin`（Intel）。

**Q: 智能切割后片段数量与预期不符**

A: 切割逻辑依赖 `silencedetect` 静音检测，若音频整体噪音较大、
   没有明显静音段，程序会在 59 秒处强制切割，这是预期行为，
   保证每段时长不超过 59 秒。

**Q: 合并视频后画面/声音不同步或报错**

A: 当多个视频的编码格式、分辨率、帧率、采样率不一致时，
   程序会自动切换为重新编码模式（统一缩放、转码为 H.264/AAC），
   该过程耗时较长，请耐心等待。

## License

本项目仅供学习与个人使用。
