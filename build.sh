#!/bin/bash
#
# build.sh
#
# Smart Shorts Toolkit macOS 打包脚本
#
# 功能：
#   1. 检查/创建 Python 虚拟环境
#   2. 安装依赖（requirements.txt）
#   3. 检查 FFmpeg 是否已安装（提示，不阻止打包）
#   4. 使用 PyInstaller + spec 文件打包为 "Smart Shorts Toolkit.app"
#
# 使用方式：
#   chmod +x build.sh
#   ./build.sh
#
# 打包完成后，应用位于:
#   dist/Smart Shorts Toolkit.app
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "============================================"
echo " Smart Shorts Toolkit - macOS 打包脚本"
echo "============================================"

# 1. 检查 Python 版本
PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "错误: 未找到 python3，请先安装 Python 3.12+"
    exit 1
fi

PY_VERSION=$("$PYTHON_BIN" -c "import sys; print('.'.join(map(str, sys.version_info[:2])))")
echo "检测到 Python 版本: $PY_VERSION"

# 2. 创建虚拟环境（如不存在）
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "正在创建虚拟环境: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "虚拟环境已存在: $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# 3. 安装依赖
echo "正在安装依赖（requirements.txt）..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. 检查 FFmpeg
echo ""
echo "检查 FFmpeg 是否已安装..."
if command -v ffmpeg &> /dev/null; then
    echo "✅ 检测到 ffmpeg: $(command -v ffmpeg)"
else
    echo "⚠️  未检测到 ffmpeg，应用运行时将无法处理音视频。"
    echo "    请运行: brew install ffmpeg"
fi

# 5. 清理旧的构建产物
echo ""
echo "清理旧的构建产物（build/ dist/）..."
rm -rf build dist

# 6. 执行 PyInstaller 打包
echo ""
echo "开始打包，使用 SmartShortsToolkit.spec..."
pyinstaller SmartShortsToolkit.spec --noconfirm

echo ""
echo "============================================"
if [ -d "dist/Smart Shorts Toolkit.app" ]; then
    echo "✅ 打包成功！"
    echo "应用位置: $PROJECT_DIR/dist/Smart Shorts Toolkit.app"
    echo ""
    echo "可以直接双击运行，或拖拽到 /Applications 目录安装。"
else
    echo "❌ 打包失败，请检查上方日志输出。"
    exit 1
fi
echo "============================================"
